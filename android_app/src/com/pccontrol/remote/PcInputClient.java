package com.pccontrol.remote;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * Low-latency input transport PC Control (phone -> PC).
 *
 * One persistent, ordered TCP connection per player session (idea from Moonlight /
 * KDE Connect): a single chunked HTTP POST /api/input/stream on the existing server
 * port, so no extra firewall rule is needed. TCP_NODELAY, all pending frames of one
 * wake-up are written as one chunk (one TCP segment), consecutive relative mouse moves
 * and scroll deltas are merged at the queue tail only (event order is never changed).
 *
 * Reliability: PING every second while idle (server releases held inputs after
 * 3.5 s of silence), write-stall detection, automatic reconnect with backoff,
 * listener callback after every (re)connect so the UI can re-send held keys.
 * Falls back to the legacy JSON endpoints if the server has no stream endpoint.
 *
 * Pure Java (no android.* imports): unit/E2E-tested on a desktop JVM.
 */
public final class PcInputClient {

    public interface Listener {
        /** Called on the I/O thread. */
        void onInputStateChanged(int state, String detail);

        /** Called on the I/O thread after a new server session was opened. */
        void onInputSessionStarted();
    }

    public static final int STATE_STOPPED = 0;
    public static final int STATE_CONNECTING = 1;
    public static final int STATE_CONNECTED = 2;
    public static final int STATE_ERROR = 3;
    public static final int STATE_AUTH_ERROR = 4;
    public static final int STATE_LEGACY = 5;

    static final long HEARTBEAT_MS = 1000;
    static final long WRITE_STALL_MS = 2500;
    static final int CONNECT_TIMEOUT_MS = 3000;
    static final int MAX_QUEUE = 2048;

    private final Object configLock = new Object();
    private String serverUrl = "";
    private String token = "";
    private Listener listener;
    private Runner current;
    private volatile int state = STATE_STOPPED;
    private volatile String stateDetail = "";

    public volatile long framesSent = 0;
    public volatile long chunksSent = 0;
    public volatile long sessionsOpened = 0;

    public void configure(String url, String authToken) {
        synchronized (configLock) {
            String u = url == null ? "" : url.trim();
            while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
            boolean changed = !u.equals(serverUrl) || !(authToken == null ? "" : authToken).equals(token);
            serverUrl = u;
            token = authToken == null ? "" : authToken;
            if (changed && current != null) {
                current.stop(false);
                current = null;
                startLocked();
            }
        }
    }

    public void setListener(Listener l) {
        listener = l;
    }

    public int getState() {
        return state;
    }

    public String getStateDetail() {
        return stateDetail;
    }

    public boolean isRunning() {
        synchronized (configLock) {
            return current != null;
        }
    }

    public void start() {
        synchronized (configLock) {
            if (current != null) return;
            startLocked();
        }
    }

    private void startLocked() {
        if (serverUrl.isEmpty()) return;
        current = new Runner(serverUrl, token);
        Thread t = new Thread(current, "pc-input-stream");
        t.setDaemon(true);
        t.setPriority(Thread.MAX_PRIORITY - 1);
        t.start();
    }

    /** Releases everything on the PC and closes the stream gracefully. */
    public void stop() {
        synchronized (configLock) {
            if (current != null) {
                current.stop(true);
                current = null;
            }
        }
        setState(STATE_STOPPED, "");
    }

    // ------------------------------------------------------------------ API
    public void mouseMove(int dx, int dy) {
        if (dx == 0 && dy == 0) return;
        Runner r = runner();
        if (r != null) r.enqueue(Op.OP_REL, null, dx, dy, 0);
    }

    /** x, y normalised 0..1 inside the streamed monitor. */
    public void mouseAbs(float x, float y, int monitor) {
        int ix = Math.round(Math.max(0f, Math.min(1f, x)) * 65535f);
        int iy = Math.round(Math.max(0f, Math.min(1f, y)) * 65535f);
        Runner r = runner();
        if (r != null) r.enqueue(Op.OP_ABS, null, ix, iy, Math.max(0, Math.min(255, monitor)));
    }

    public void mouseButton(int button, boolean down) {
        raw(PcInputProtocol.mouseButton(button, down));
    }

    /** Wheel units (120 = one notch); fractional notches are accumulated by the server. */
    public void scroll(int vertical, int horizontal) {
        if (vertical == 0 && horizontal == 0) return;
        Runner r = runner();
        if (r != null) r.enqueue(Op.OP_SCROLL, null, vertical, horizontal, 0);
    }

    public void key(int vk, boolean down) {
        raw(PcInputProtocol.key(vk, down, PcInputProtocol.isExtendedVk(vk)));
    }

    public void unicode(int codePoint, boolean down) {
        raw(PcInputProtocol.unicode(codePoint, down));
    }

    public void text(String s) {
        if (s == null || s.isEmpty()) return;
        raw(PcInputProtocol.text(s));
    }

    public void hotkey(int[] vks) {
        raw(PcInputProtocol.hotkey(vks));
    }

    public void releaseAll() {
        raw(PcInputProtocol.releaseAll());
    }

    private void raw(byte[] frame) {
        Runner r = runner();
        if (r != null) r.enqueue(Op.OP_RAW, frame, 0, 0, 0);
    }

    private Runner runner() {
        synchronized (configLock) {
            return current;
        }
    }

    private void setState(int s, String detail) {
        state = s;
        stateDetail = detail == null ? "" : detail;
        Listener l = listener;
        if (l != null) {
            try {
                l.onInputStateChanged(s, stateDetail);
            } catch (Exception ignored) {}
        }
    }

    // ------------------------------------------------------------------ queue op
    static final class Op {
        static final int OP_RAW = 0, OP_REL = 1, OP_ABS = 2, OP_SCROLL = 3;
        int type;
        byte[] frame;
        int a, b, c;

        byte[] encode() {
            switch (type) {
                case OP_REL: return PcInputProtocol.mouseRel(a, b);
                case OP_ABS: return PcInputProtocol.mouseAbs(a, b, c);
                case OP_SCROLL: return PcInputProtocol.scroll(a, b);
                default: return frame;
            }
        }
    }

    // ------------------------------------------------------------------ connection runner
    private final class Runner implements Runnable {
        private final String url;
        private final String authToken;
        private final Object lock = new Object();
        private final ArrayList<Op> queue = new ArrayList<>();
        private volatile boolean running = true;
        private volatile boolean graceful = false;
        private volatile boolean connectionDead = false;
        private volatile long writeStartedNanos = 0;
        private Socket socket;

        Runner(String url, String authToken) {
            this.url = url;
            this.authToken = authToken;
        }

        void enqueue(int type, byte[] frame, int a, int b, int c) {
            synchronized (lock) {
                if (!running) return;
                int n = queue.size();
                Op tail = n > 0 ? queue.get(n - 1) : null;
                if (tail != null && tail.type == type) {
                    if (type == Op.OP_REL && fits(tail.a + a) && fits(tail.b + b)) {
                        tail.a += a;
                        tail.b += b;
                        lock.notifyAll();
                        return;
                    }
                    if (type == Op.OP_SCROLL && fits(tail.a + a) && fits(tail.b + b)) {
                        tail.a += a;
                        tail.b += b;
                        lock.notifyAll();
                        return;
                    }
                    if (type == Op.OP_ABS && tail.c == c) {
                        tail.a = a;
                        tail.b = b;
                        lock.notifyAll();
                        return;
                    }
                }
                if (n >= MAX_QUEUE) {
                    // Link is stalled: drop the oldest pointer motion, never key/button events.
                    for (int i = 0; i < n; i++) {
                        int t = queue.get(i).type;
                        if (t == Op.OP_REL || t == Op.OP_ABS || t == Op.OP_SCROLL) {
                            queue.remove(i);
                            break;
                        }
                    }
                    if (queue.size() >= MAX_QUEUE) return;
                }
                Op op = new Op();
                op.type = type;
                op.frame = frame;
                op.a = a;
                op.b = b;
                op.c = c;
                queue.add(op);
                lock.notifyAll();
            }
        }

        void stop(boolean gracefulEnd) {
            synchronized (lock) {
                graceful = gracefulEnd;
                running = false;
                lock.notifyAll();
            }
            if (!gracefulEnd) closeSocket();
        }

        @Override
        public void run() {
            long backoff = 0;
            while (running) {
                if (backoff > 0) {
                    sleepInterruptibly(backoff);
                    if (!running) break;
                }
                setState(STATE_CONNECTING, url);
                int pre = preflight();
                if (!running) break;
                if (pre == 404) {
                    setState(STATE_LEGACY, "legacy JSON endpoints");
                    runLegacy();
                    return;
                }
                if (pre == 401 || pre == 403) {
                    setState(STATE_AUTH_ERROR, "HTTP " + pre);
                    dropQueue();
                    backoff = 3000;
                    continue;
                }
                if (pre != 200) {
                    setState(STATE_ERROR, pre < 0 ? "no connection" : "HTTP " + pre);
                    dropQueue();
                    backoff = backoff == 0 ? 300 : Math.min(2000, backoff * 2);
                    continue;
                }
                try {
                    openStream();
                    sessionsOpened++;
                    backoff = 0;
                    setState(STATE_CONNECTED, url);
                    Listener l = listener;
                    if (l != null) {
                        try {
                            l.onInputSessionStarted();
                        } catch (Exception ignored) {}
                    }
                    pump();
                } catch (IOException e) {
                    if (running) {
                        setState(STATE_ERROR, e.getClass().getSimpleName());
                        backoff = 300;
                    }
                } finally {
                    closeSocket();
                }
                if (running) dropQueue();
            }
        }

        private void pump() throws IOException {
            OutputStream out = socket.getOutputStream();
            long lastWrite = System.nanoTime();
            ArrayList<byte[]> frames = new ArrayList<>();
            while (true) {
                boolean stopping;
                frames.clear();
                synchronized (lock) {
                    while (queue.isEmpty() && running && !connectionDead) {
                        long idleMs = (System.nanoTime() - lastWrite) / 1_000_000L;
                        long wait = HEARTBEAT_MS - idleMs;
                        if (wait <= 0) break;
                        try {
                            lock.wait(wait);
                        } catch (InterruptedException e) {
                            Thread.currentThread().interrupt();
                            throw new IOException("interrupted");
                        }
                    }
                    for (Op op : queue) frames.add(op.encode());
                    queue.clear();
                    stopping = !running;
                }
                if (connectionDead) throw new IOException("server closed the input stream");
                if (stopping) {
                    if (!graceful) return;
                    frames.add(PcInputProtocol.releaseAll());
                    frames.add(PcInputProtocol.end());
                } else if (frames.isEmpty()) {
                    frames.add(PcInputProtocol.ping());
                }
                writeChunk(out, frames);
                lastWrite = System.nanoTime();
                if (stopping) {
                    writeStartedNanos = System.nanoTime();
                    out.write("0\r\n\r\n".getBytes(StandardCharsets.US_ASCII));
                    out.flush();
                    writeStartedNanos = 0;
                    return;
                }
            }
        }

        private void writeChunk(OutputStream out, ArrayList<byte[]> frames) throws IOException {
            int total = 0;
            for (byte[] f : frames) total += f.length;
            ByteArrayOutputStream buf = new ByteArrayOutputStream(total + 16);
            buf.write((Integer.toHexString(total) + "\r\n").getBytes(StandardCharsets.US_ASCII));
            for (byte[] f : frames) buf.write(f, 0, f.length);
            buf.write('\r');
            buf.write('\n');
            writeStartedNanos = System.nanoTime();
            buf.writeTo(out);
            out.flush();
            writeStartedNanos = 0;
            framesSent += frames.size();
            chunksSent++;
        }

        // -------------------------------------------------------------- HTTP plumbing
        private String hostHeader(URL u) {
            int port = u.getPort();
            return port > 0 ? u.getHost() + ":" + port : u.getHost();
        }

        private Socket connectSocket(URL u) throws IOException {
            boolean tls = "https".equalsIgnoreCase(u.getProtocol());
            int port = u.getPort() > 0 ? u.getPort() : (tls ? 443 : 80);
            Socket s = new Socket();
            s.setTcpNoDelay(true);
            s.setKeepAlive(true);
            s.connect(new InetSocketAddress(u.getHost(), port), CONNECT_TIMEOUT_MS);
            if (tls) {
                SSLSocket ssl = (SSLSocket) ((SSLSocketFactory) SSLSocketFactory.getDefault())
                        .createSocket(s, u.getHost(), port, true);
                ssl.startHandshake();
                return ssl;
            }
            return s;
        }

        private String basePath(URL u) {
            String p = u.getPath();
            if (p == null) return "";
            while (p.endsWith("/")) p = p.substring(0, p.length() - 1);
            return p;
        }

        /** GET /api/input/info. Returns HTTP status, or -1 when the server is unreachable. */
        private int preflight() {
            Socket s = null;
            try {
                URL u = new URL(url);
                s = connectSocket(u);
                s.setSoTimeout(CONNECT_TIMEOUT_MS);
                String req = "GET " + basePath(u) + "/api/input/info HTTP/1.1\r\n"
                        + "Host: " + hostHeader(u) + "\r\n"
                        + "X-Auth-Token: " + authToken + "\r\n"
                        + "Connection: close\r\n\r\n";
                OutputStream o = s.getOutputStream();
                o.write(req.getBytes(StandardCharsets.UTF_8));
                o.flush();
                String status = readLine(s.getInputStream());
                if (status == null) return -1;
                String[] parts = status.split(" ");
                return parts.length >= 2 ? Integer.parseInt(parts[1].trim()) : -1;
            } catch (Exception e) {
                return -1;
            } finally {
                if (s != null) {
                    try {
                        s.close();
                    } catch (IOException ignored) {}
                }
            }
        }

        private void openStream() throws IOException {
            URL u = new URL(url);
            Socket s = connectSocket(u);
            synchronized (lock) {
                socket = s;
                connectionDead = false;
            }
            String req = "POST " + basePath(u) + "/api/input/stream HTTP/1.1\r\n"
                    + "Host: " + hostHeader(u) + "\r\n"
                    + "X-Auth-Token: " + authToken + "\r\n"
                    + "Content-Type: application/octet-stream\r\n"
                    + "Transfer-Encoding: chunked\r\n\r\n";
            OutputStream o = s.getOutputStream();
            o.write(req.getBytes(StandardCharsets.UTF_8));
            ArrayList<byte[]> hello = new ArrayList<>();
            hello.add(PcInputProtocol.hello());
            writeChunk(o, hello);
            s.setSoTimeout(500);
            Thread reader = new Thread(new Runnable() {
                @Override
                public void run() {
                    readerLoop(s);
                }
            }, "pc-input-stream-reader");
            reader.setDaemon(true);
            reader.start();
        }

        /** Any bytes from the server mean it answered = our session is over (error or close). */
        private void readerLoop(Socket s) {
            byte[] buf = new byte[512];
            try {
                InputStream in = s.getInputStream();
                while (true) {
                    try {
                        int n = in.read(buf);
                        if (n != 0) break;
                    } catch (SocketTimeoutException timeout) {
                        long ws = writeStartedNanos;
                        if (ws != 0 && (System.nanoTime() - ws) / 1_000_000L > WRITE_STALL_MS) {
                            break; // writes are stuck (Wi-Fi gone): force reconnect
                        }
                        if (s.isClosed()) return;
                    }
                }
            } catch (IOException ignored) {
            }
            synchronized (lock) {
                if (socket == s) {
                    connectionDead = true;
                    lock.notifyAll();
                }
            }
            try {
                s.close();
            } catch (IOException ignored) {}
        }

        private void closeSocket() {
            Socket s;
            synchronized (lock) {
                s = socket;
                socket = null;
            }
            if (s != null) {
                try {
                    s.close();
                } catch (IOException ignored) {}
            }
        }

        private void dropQueue() {
            // Events queued for a dead session are dropped: the server already released
            // everything; the UI re-sends held keys in onInputSessionStarted().
            synchronized (lock) {
                queue.clear();
            }
        }

        private void sleepInterruptibly(long ms) {
            synchronized (lock) {
                long end = System.currentTimeMillis() + ms;
                while (running) {
                    long left = end - System.currentTimeMillis();
                    if (left <= 0) break;
                    try {
                        lock.wait(left);
                    } catch (InterruptedException e) {
                        return;
                    }
                }
            }
        }

        // -------------------------------------------------------------- legacy fallback
        private void runLegacy() {
            int scrollAcc = 0;
            while (running) {
                ArrayList<Op> ops = new ArrayList<>();
                synchronized (lock) {
                    while (queue.isEmpty() && running) {
                        try {
                            lock.wait(500);
                        } catch (InterruptedException e) {
                            return;
                        }
                    }
                    ops.addAll(queue);
                    queue.clear();
                }
                for (Op op : ops) {
                    try {
                        scrollAcc = sendLegacy(op, scrollAcc);
                    } catch (Exception ignored) {}
                }
            }
            if (graceful) {
                try {
                    postJson("/api/keyboard", "{\"action\":\"release_all\"}");
                } catch (Exception ignored) {}
            }
        }

        private int sendLegacy(Op op, int scrollAcc) throws IOException {
            byte[] f = op.frame;
            switch (op.type) {
                case Op.OP_REL:
                    postJson("/api/mouse", "{\"action\":\"move_rel\",\"dx\":" + op.a + ",\"dy\":" + op.b
                            + ",\"sensitivity\":1.0,\"accel\":false}");
                    return scrollAcc;
                case Op.OP_ABS:
                    postJson("/api/mouse", "{\"action\":\"move_norm\",\"x\":" + (op.a / 65535f) + ",\"y\":"
                            + (op.b / 65535f) + ",\"monitor\":" + op.c + "}");
                    return scrollAcc;
                case Op.OP_SCROLL:
                    scrollAcc += op.a;
                    int ticks = scrollAcc / PcInputProtocol.WHEEL_DELTA;
                    if (ticks != 0) {
                        scrollAcc -= ticks * PcInputProtocol.WHEEL_DELTA;
                        postJson("/api/mouse", "{\"action\":\"scroll\",\"dy\":" + ticks + "}");
                    }
                    return scrollAcc;
                default:
                    break;
            }
            int type = f[0] & 0xFF;
            if (type == PcInputProtocol.FRAME_MOUSE_BTN) {
                String b = f[4] == 2 ? "right" : (f[4] == 3 ? "middle" : "left");
                postJson("/api/mouse", "{\"action\":\"" + (f[5] != 0 ? "down" : "up") + "\",\"button\":\"" + b + "\"}");
            } else if (type == PcInputProtocol.FRAME_KEY) {
                int vk = (f[4] & 0xFF) | ((f[5] & 0xFF) << 8);
                postJson("/api/keyboard", "{\"action\":\"" + (f[6] != 0 ? "key_down" : "key_up") + "\",\"vk\":" + vk + "}");
            } else if (type == PcInputProtocol.FRAME_UNICODE) {
                if (f[8] != 0) {
                    int cp = (f[4] & 0xFF) | ((f[5] & 0xFF) << 8) | ((f[6] & 0xFF) << 16);
                    postJson("/api/keyboard", "{\"action\":\"text\",\"text\":" + jsonString(new String(Character.toChars(cp))) + "}");
                }
            } else if (type == PcInputProtocol.FRAME_TEXT) {
                String t = new String(f, 4, f.length - 4, StandardCharsets.UTF_8);
                postJson("/api/keyboard", "{\"action\":\"text\",\"text\":" + jsonString(t) + "}");
            } else if (type == PcInputProtocol.FRAME_HOTKEY) {
                int n = f[4] & 0xFF;
                for (int i = 0; i < n; i++) {
                    int vk = (f[5 + i * 2] & 0xFF) | ((f[6 + i * 2] & 0xFF) << 8);
                    postJson("/api/keyboard", "{\"action\":\"key_down\",\"vk\":" + vk + "}");
                }
                for (int i = n - 1; i >= 0; i--) {
                    int vk = (f[5 + i * 2] & 0xFF) | ((f[6 + i * 2] & 0xFF) << 8);
                    postJson("/api/keyboard", "{\"action\":\"key_up\",\"vk\":" + vk + "}");
                }
            } else if (type == PcInputProtocol.FRAME_RELEASE_ALL) {
                postJson("/api/keyboard", "{\"action\":\"release_all\"}");
            }
            return scrollAcc;
        }

        private void postJson(String path, String json) throws IOException {
            HttpURLConnection c = (HttpURLConnection) new URL(url + path).openConnection();
            boolean ok = false;
            try {
                c.setRequestMethod("POST");
                c.setConnectTimeout(1500);
                c.setReadTimeout(1500);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("X-Auth-Token", authToken);
                byte[] body = json.getBytes(StandardCharsets.UTF_8);
                c.setFixedLengthStreamingMode(body.length);
                OutputStream o = c.getOutputStream();
                o.write(body);
                o.close();
                int code = c.getResponseCode();
                // Read the body to the end and close the stream WITHOUT disconnect(): the
                // socket goes back to the keep-alive pool. disconnect() after every event
                // forced a new TCP connection per mouse move (very jerky on the old server).
                InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
                if (in != null) {
                    byte[] buf = new byte[256];
                    while (in.read(buf) >= 0) { /* drain */ }
                    in.close();
                }
                ok = true;
            } finally {
                if (!ok) c.disconnect();
            }
        }
    }

    static boolean fits(int v) {
        return v >= -32768 && v <= 32767;
    }

    static String jsonString(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '"' || ch == '\\') {
                sb.append('\\').append(ch);
            } else if (ch < 0x20) {
                sb.append(String.format("\\u%04x", (int) ch));
            } else {
                sb.append(ch);
            }
        }
        return sb.append('"').toString();
    }

    private static String readLine(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        int c;
        while ((c = in.read()) != -1) {
            if (c == '\n') break;
            if (c != '\r') sb.append((char) c);
            if (sb.length() > 512) break;
        }
        return c == -1 && sb.length() == 0 ? null : sb.toString();
    }
}
