package com.pccontrol.remote;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

import java.io.BufferedInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * "Звук ПК" / "Микрофон" buttons of the main screen: plays the PC's WASAPI stream
 * (GET /audio → WAV PCM 16 bit, ?mic=1 = PC microphone) through AudioTrack with automatic
 * reconnection and latency trimming. Native replacement of the WebView WebRTC/&lt;audio&gt; path.
 */
final class PcAudioStream {
    interface Listener {
        /** state: 0 = connecting, 1 = playing, 2 = reconnecting, 3 = stopped, 4 = auth error, 5 = failed */
        void onState(int state, String detail);
    }

    static final int CONNECTING = 0, PLAYING = 1, RECONNECTING = 2, STOPPED = 3, AUTH = 4, FAILED = 5;

    private final boolean mic;
    private final Listener listener;
    private volatile Worker worker;

    PcAudioStream(boolean mic, Listener l) {
        this.mic = mic;
        this.listener = l;
    }

    boolean isRunning() {
        return worker != null;
    }

    void start(String baseUrl, String token) {
        stop();
        Worker w = new Worker(baseUrl, token);
        worker = w;
        w.start();
    }

    void stop() {
        Worker w = worker;
        worker = null;
        if (w != null) w.shutdown();
    }

    private final class Worker extends Thread {
        private final String base, token;
        private final AtomicBoolean running = new AtomicBoolean(true);
        private volatile HttpURLConnection conn;
        private AudioTrack track;

        Worker(String base, String token) {
            super(mic ? "pc-mic-audio" : "pc-system-audio");
            this.base = PcConn.stripSlash(base);
            this.token = token == null ? "" : token;
        }

        void shutdown() {
            running.set(false);
            HttpURLConnection c = conn;
            if (c != null) try { c.disconnect(); } catch (Exception ignored) {}
            interrupt();
        }

        private void emit(int st, String d) {
            if (running.get() || st == STOPPED) listener.onState(st, d);
        }

        @Override
        public void run() {
            int attempt = 0;
            int failures = 0;
            int trackRate = 0, trackCh = 0;
            try {
                while (running.get()) {
                    if (attempt > 0) {
                        emit(RECONNECTING, "");
                        try { Thread.sleep(Math.min(3000, 600L * attempt)); } catch (InterruptedException e) { break; }
                        if (!running.get()) break;
                    } else {
                        emit(CONNECTING, "");
                    }
                    attempt++;
                    HttpURLConnection c = null;
                    try {
                        String url = base + "/audio?t=" + System.currentTimeMillis() + (mic ? "&mic=1" : "")
                                + "&token=" + PcConn.encodeURIComponent(token);
                        c = (HttpURLConnection) new URL(url).openConnection();
                        conn = c;
                        c.setConnectTimeout(4000);
                        c.setReadTimeout(10000);
                        c.setRequestProperty("Accept", "audio/wav");
                        if (!PcHttp.acceptLanguage.isEmpty()) c.setRequestProperty("Accept-Language", PcHttp.acceptLanguage);
                        if (!token.isEmpty()) c.setRequestProperty("X-Auth-Token", PcConn.encodeURIComponent(token));
                        int code = c.getResponseCode();
                        if (code == 401) {
                            emit(AUTH, "");
                            break;
                        }
                        if (code != 200) {
                            failures++;
                            // 503 = the PC could not open the audio device: not a network hiccup (QA P-4)
                            if (failures >= 4 || code == 503) {
                                String msg = "";
                                try (InputStream es = c.getErrorStream()) {
                                    if (es != null) msg = PcJson.parseObj(new String(PcHttp.readAll(es, 65536), "UTF-8")).str("message");
                                } catch (Exception ignored) {
                                }
                                emit(FAILED, msg.isEmpty() ? ("HTTP " + code) : msg);
                                break;
                            }
                            continue;
                        }
                        String ct = c.getContentType();
                        if (ct != null && ct.contains("json")) { // safe mode / simulated stream
                            emit(FAILED, "safe mode");
                            break;
                        }
                        try (InputStream raw = c.getInputStream();
                             BufferedInputStream in = new BufferedInputStream(raw, 16384)) {
                            in.mark(64);
                            byte[] hdr = new byte[44];
                            int got = 0;
                            while (got < 44) {
                                int n = in.read(hdr, got, 44 - got);
                                if (n <= 0) break;
                                got += n;
                            }
                            int rate = 48000, ch = 2;
                            if (got == 44 && hdr[0] == 'R' && hdr[1] == 'I' && hdr[2] == 'F' && hdr[3] == 'F') {
                                int cc = (hdr[22] & 0xFF) | ((hdr[23] & 0xFF) << 8);
                                int sr = (hdr[24] & 0xFF) | ((hdr[25] & 0xFF) << 8) | ((hdr[26] & 0xFF) << 16) | ((hdr[27] & 0xFF) << 24);
                                if (cc >= 1 && cc <= 2) ch = cc;
                                if (sr >= 8000 && sr <= 192000) rate = sr;
                            } else {
                                in.reset();
                            }
                            if (track == null || rate != trackRate || ch != trackCh) {
                                releaseTrack();
                                int cfg = ch == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
                                int minBuf = AudioTrack.getMinBufferSize(rate, cfg, AudioFormat.ENCODING_PCM_16BIT);
                                track = new AudioTrack.Builder()
                                        .setAudioAttributes(new AudioAttributes.Builder()
                                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                                .setContentType(mic ? AudioAttributes.CONTENT_TYPE_SPEECH : AudioAttributes.CONTENT_TYPE_MUSIC)
                                                .build())
                                        .setAudioFormat(new AudioFormat.Builder()
                                                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                                .setSampleRate(rate).setChannelMask(cfg).build())
                                        .setBufferSizeInBytes(Math.max(minBuf * 2, 8192))
                                        .setTransferMode(AudioTrack.MODE_STREAM)
                                        .build();
                                track.play();
                                trackRate = rate;
                                trackCh = ch;
                            }
                            if (got == 0) {
                                // QA P-4: 200 with an empty body (older server whose audio device failed
                                // after answering) used to be retried forever as a "network drop".
                                failures++;
                                if (failures >= 4) {
                                    emit(FAILED, mic ? "@audio_mic_unavailable" : "@audio_pc_unavailable");
                                    break;
                                }
                                continue;
                            }
                            int frame = 2 * ch;
                            emit(PLAYING, (rate / 1000) + " kHz");
                            failures = 0;
                            byte[] buf = new byte[3840 + frame];
                            int carry = 0;
                            long written = 0;
                            long head0 = track.getPlaybackHeadPosition();
                            while (running.get()) {
                                int r = in.read(buf, carry, 3840);
                                if (r <= 0) break;
                                attempt = 1;
                                int avail = carry + r;
                                int whole = avail - (avail % frame);
                                if (whole > 0) {
                                    long played = track.getPlaybackHeadPosition() - head0;
                                    long latency = written / frame - played;
                                    if (latency > trackRate / 5) { // > 200 ms behind: drop the backlog
                                        // QA A-14: flush() while playing is a no-op - pause first.
                                        try {
                                            track.pause();
                                            track.flush();
                                            track.play();
                                        } catch (IllegalStateException ignored) {}
                                        head0 = track.getPlaybackHeadPosition();
                                        written = 0;
                                        // the backlog also waits in the socket buffer: skip what has
                                        // already arrived (whole frames, so the sample alignment stays)
                                        try {
                                            int backlog = in.available();
                                            backlog -= backlog % frame;
                                            if (backlog > 0) in.skip(backlog);
                                        } catch (Exception ignored) {}
                                    }
                                    int w = track.write(buf, 0, whole);
                                    if (w > 0) written += w;
                                }
                                carry = avail - whole;
                                if (carry > 0) System.arraycopy(buf, whole, buf, 0, carry);
                            }
                        }
                    } catch (Exception e) {
                        // network drop → reconnect
                    } finally {
                        conn = null;
                        if (c != null) try { c.disconnect(); } catch (Exception ignored) {}
                    }
                }
            } finally {
                releaseTrack();
                if (worker == this) worker = null;
                if (worker == null) listener.onState(STOPPED, ""); // not when already restarted
            }
        }

        private void releaseTrack() {
            if (track != null) {
                try { track.stop(); } catch (Exception ignored) {}
                try { track.release(); } catch (Exception ignored) {}
                track = null;
            }
        }
    }
}
