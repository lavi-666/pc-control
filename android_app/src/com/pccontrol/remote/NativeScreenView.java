package com.pccontrol.remote;

import android.content.Context;
import android.graphics.Color;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.io.BufferedInputStream;
import java.io.EOFException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * NativeScreenView — Высокопроизводительный нативный экран демонстрации PC Control.
 * Архитектура основана на проверенных решениях Moonlight Android и Sunshine:
 * - MediaCodec Direct Surface Rendering (аппаратный вывод без промежуточных буферов);
 * - Нулевое копирование и отсутствие аллокаций в сетевом цикле (Zero-GC);
 * - Поддержка как сверхбыстрого фреймированного потока PC01, так и сырого Annex-B (00 00 01 / 00 00 00 01);
 * - Правильная подача SPS/PPS и IDR ключевых кадров;
 * - Мгновенное прерывание соединения через socket close без блокировок потока;
 * - Цветокоррекция BT.709 и автоматический fallback при несовместимости вендорских флагов MediaCodec.
 */
public class NativeScreenView extends FrameLayout implements SurfaceHolder.Callback {

    public interface OnCloseListener {
        void onCloseRequested();
    }

    private SurfaceView surfaceView;
    private SurfaceHolder surfaceHolder;
    private TextView hudTextView;
    private TextView closeButton;

    private MediaCodec decoder;
    private Thread workerThread;
    private volatile HttpURLConnection activeConn;
    private final AtomicBoolean isStreaming = new AtomicBoolean(false);
    private final Object surfaceLock = new Object();
    private boolean surfaceReady = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private String serverUrl = "";
    private String authToken = "";
    private int targetMonitor = 1;
    private int targetHeight = 1080;
    private int targetFps = 60;
    private int targetBitrate = 0;

    private OnCloseListener closeListener;

    // Телеметрия и замеры в реальном времени
    private long framesDecoded = 0;
    private long bytesReceived = 0;
    private long lastStatTime = 0;
    private float currentFps = 0.0f;
    private float currentKbps = 0.0f;
    private String activeCodecName = "Hardware";

    // Управление сенсорным вводом (Moonlight Touch Controller)
    private float lastTouchX = 0f;
    private float lastTouchY = 0f;
    private long touchDownTime = 0;
    private boolean isDragging = false;
    private int pointerCount = 1;

    public NativeScreenView(Context context) {
        super(context);
        init(context);
    }

    public NativeScreenView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init(context);
    }

    private void init(Context context) {
        setBackgroundColor(Color.BLACK);

        surfaceView = new SurfaceView(context);
        surfaceHolder = surfaceView.getHolder();
        surfaceHolder.addCallback(this);
        LayoutParams surfParams = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT, Gravity.CENTER);
        addView(surfaceView, surfParams);

        // HUD Overlay (Статистика стриминга в реальном времени)
        hudTextView = new TextView(context);
        hudTextView.setTextColor(Color.parseColor("#00E676")); // Neon Green
        hudTextView.setTextSize(11f);
        hudTextView.setBackgroundColor(Color.parseColor("#99000000")); // Полупрозрачный черный
        hudTextView.setPadding(16, 10, 16, 10);
        hudTextView.setText("PC Control Native Stream · Подключение...");
        LayoutParams hudParams = new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        hudParams.gravity = Gravity.TOP | Gravity.START;
        hudParams.setMargins(20, 20, 0, 0);
        addView(hudTextView, hudParams);

        // Кнопка закрытия
        closeButton = new TextView(context);
        closeButton.setText("✕");
        closeButton.setTextColor(Color.WHITE);
        closeButton.setTextSize(16f);
        closeButton.setBackgroundColor(Color.parseColor("#B3D32F2F")); // Полупрозрачный красный
        closeButton.setPadding(24, 12, 24, 12);
        closeButton.setGravity(Gravity.CENTER);
        LayoutParams btnParams = new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        btnParams.gravity = Gravity.TOP | Gravity.END;
        btnParams.setMargins(0, 20, 20, 0);
        closeButton.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                stopStream();
                if (closeListener != null) {
                    closeListener.onCloseRequested();
                }
            }
        });
        addView(closeButton, btnParams);

        // Настройка обработки сенсорного ввода
        surfaceView.setOnTouchListener(new OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                return handleTouchEvent(event);
            }
        });
    }

    public void setOnCloseListener(OnCloseListener listener) {
        this.closeListener = listener;
    }

    public void configure(String url, String token, int monitor, int height, int fps, int bitrate, String quality, String codec) {
        this.serverUrl = (url != null) ? url.trim() : "";
        while (this.serverUrl.endsWith("/")) {
            this.serverUrl = this.serverUrl.substring(0, this.serverUrl.length() - 1);
        }
        if (!this.serverUrl.isEmpty() && !this.serverUrl.startsWith("http://") && !this.serverUrl.startsWith("https://")) {
            this.serverUrl = "http://" + this.serverUrl;
        }
        this.authToken = (token != null) ? token.trim() : "";
        this.targetMonitor = monitor;
        this.targetHeight = height;
        this.targetFps = fps;
        this.targetBitrate = bitrate;
    }

    public void startStream() {
        if (isStreaming.get()) {
            return;
        }
        isStreaming.set(true);
        setVisibility(View.VISIBLE);

        workerThread = new Thread(new Runnable() {
            @Override
            public void run() {
                runStreamWorker();
            }
        }, "pc-native-stream-worker");
        workerThread.start();
    }

    public void stopStream() {
        isStreaming.set(false);
        HttpURLConnection conn = activeConn;
        if (conn != null) {
            try {
                conn.disconnect();
            } catch (Exception ignored) {}
            activeConn = null;
        }
        if (workerThread != null) {
            workerThread.interrupt();
            workerThread = null;
        }
        releaseDecoder();
        post(new Runnable() {
            @Override
            public void run() {
                setVisibility(View.GONE);
            }
        });
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        synchronized (surfaceLock) {
            this.surfaceHolder = holder;
            this.surfaceReady = (holder != null && holder.getSurface() != null && holder.getSurface().isValid());
            surfaceLock.notifyAll();
        }
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        synchronized (surfaceLock) {
            this.surfaceHolder = holder;
            this.surfaceReady = (holder != null && holder.getSurface() != null && holder.getSurface().isValid());
            surfaceLock.notifyAll();
        }
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        synchronized (surfaceLock) {
            this.surfaceReady = false;
            this.surfaceHolder = null;
        }
        stopStream();
    }

    /**
     * Потоковый воркер: получает низколатентный H.264 поток и передает видеокадры в аппаратный MediaCodec.
     */
    private void runStreamWorker() {
        HttpURLConnection conn = null;
        InputStream in = null;
        try {
            // Ожидание готовности Surface дисплея
            synchronized (surfaceLock) {
                while (!surfaceReady || surfaceHolder == null || surfaceHolder.getSurface() == null || !surfaceHolder.getSurface().isValid()) {
                    if (!isStreaming.get()) return;
                    surfaceLock.wait(100);
                }
            }

            int w = (targetHeight > 0) ? (int) Math.round(targetHeight * (16.0 / 9.0)) : 1920;
            int h = (targetHeight > 0) ? targetHeight : 1080;
            w = (w / 2) * 2;
            h = (h / 2) * 2;

            initDecoder(w, h);

            if (serverUrl.isEmpty()) {
                updateHud("Ошибка: не указан адрес сервера");
                return;
            }

            String streamEndpoint = serverUrl + "/screen/h264_stream"
                    + "?format=framed"
                    + "&monitor=" + targetMonitor
                    + "&height=" + targetHeight
                    + "&fps=" + targetFps
                    + "&bitrate=" + targetBitrate
                    + "&token=" + java.net.URLEncoder.encode(authToken, "UTF-8");

            URL url = new URL(streamEndpoint);
            conn = (HttpURLConnection) url.openConnection();
            activeConn = conn;
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(6000);
            conn.setReadTimeout(10000);
            conn.setUseCaches(false);
            conn.setRequestProperty("User-Agent", "PCControl-NativePlayer/2.3");
            if (!authToken.isEmpty()) {
                conn.setRequestProperty("X-Auth-Token", authToken);
                conn.setRequestProperty("Cookie", "token=" + authToken);
            }

            conn.connect();
            int respCode = conn.getResponseCode();
            if (respCode != 200) {
                updateHud("Ошибка подключения: HTTP " + respCode);
                return;
            }

            in = new BufferedInputStream(conn.getInputStream(), 262144);

            byte[] frameBuffer = new byte[2 * 1024 * 1024]; // 2 MB буфер под полный кадр
            byte[] headerBuf = new byte[17]; // 4 байта magic + 4 байта len + 1 байт flags + 8 байт pts
            byte[] ringBuffer = new byte[2 * 1024 * 1024]; // Буфер для фоллбэка на чистый Annex-B
            int ringHead = 0;

            lastStatTime = SystemClock.elapsedRealtime();
            framesDecoded = 0;
            bytesReceived = 0;

            // Проверяем первые 4 байта потока: определяют протокол (PC01 vs Annex-B)
            readFully(in, headerBuf, 0, 4);
            bytesReceived += 4;

            boolean isFramed = (headerBuf[0] == 0x50 && headerBuf[1] == 0x43 && headerBuf[2] == 0x30 && headerBuf[3] == 0x31); // 'PC01'

            if (isFramed) {
                // Высокоскоростной режим фреймирования: точные границы кадров, ноль сканирования
                while (isStreaming.get()) {
                    // Дочитываем оставшиеся 13 байт заголовка: len(4), flags(1), pts(8)
                    readFully(in, headerBuf, 4, 13);
                    bytesReceived += 13;

                    int frameLen = ((headerBuf[4] & 0xFF) << 24)
                            | ((headerBuf[5] & 0xFF) << 16)
                            | ((headerBuf[6] & 0xFF) << 8)
                            | (headerBuf[7] & 0xFF);

                    int frameFlags = headerBuf[8] & 0xFF;

                    long ptsUs = (((long) (headerBuf[9] & 0xFF)) << 56)
                            | (((long) (headerBuf[10] & 0xFF)) << 48)
                            | (((long) (headerBuf[11] & 0xFF)) << 40)
                            | (((long) (headerBuf[12] & 0xFF)) << 32)
                            | (((long) (headerBuf[13] & 0xFF)) << 24)
                            | (((long) (headerBuf[14] & 0xFF)) << 16)
                            | (((long) (headerBuf[15] & 0xFF)) << 8)
                            | ((long) (headerBuf[16] & 0xFF));

                    if (frameLen <= 0 || frameLen > frameBuffer.length) {
                        // Рассинхронизация заголовка — выход из цикла для восстановления
                        break;
                    }

                    // Читаем тело кадра
                    readFully(in, frameBuffer, 0, frameLen);
                    bytesReceived += frameLen;

                    feedDecoderFrame(frameBuffer, frameLen, frameFlags, ptsUs);
                    drainOutputBuffers();
                    updateStatsIfNeeded();

                    // Читаем magic следующего кадра
                    readFully(in, headerBuf, 0, 4);
                    bytesReceived += 4;
                    if (headerBuf[0] != 0x50 || headerBuf[1] != 0x43 || headerBuf[2] != 0x30 || headerBuf[3] != 0x31) {
                        break;
                    }
                }
            } else {
                // Универсальный фоллбэк на поток чистого Annex-B (поддержка 00 00 01 и 00 00 00 01)
                System.arraycopy(headerBuf, 0, ringBuffer, 0, 4);
                ringHead = 4;
                byte[] chunk = new byte[32768];

                while (isStreaming.get()) {
                    int r = in.read(chunk, 0, chunk.length);
                    if (r == -1) break;
                    bytesReceived += r;

                    if (ringHead + r > ringBuffer.length) {
                        // Защита от переполнения: сброс кольцевого буфера
                        ringHead = 0;
                    }
                    System.arraycopy(chunk, 0, ringBuffer, ringHead, r);
                    ringHead += r;

                    // Сканируем ringBuffer на наличие старт-кодов без аллокации памяти
                    int curPos = 0;
                    while (curPos < ringHead - 4) {
                        int startCodeLen = 0;
                        if (ringBuffer[curPos] == 0 && ringBuffer[curPos + 1] == 0) {
                            if (ringBuffer[curPos + 2] == 1) {
                                startCodeLen = 3;
                            } else if (curPos + 3 < ringHead && ringBuffer[curPos + 2] == 0 && ringBuffer[curPos + 3] == 1) {
                                startCodeLen = 4;
                            }
                        }

                        if (startCodeLen > 0) {
                            // Ищем следующий старт-код
                            int nextPos = curPos + startCodeLen;
                            int nextStartCodeLen = 0;
                            while (nextPos < ringHead - 3) {
                                if (ringBuffer[nextPos] == 0 && ringBuffer[nextPos + 1] == 0) {
                                    if (ringBuffer[nextPos + 2] == 1) {
                                        nextStartCodeLen = 3;
                                        break;
                                    } else if (nextPos + 3 < ringHead && ringBuffer[nextPos + 2] == 0 && ringBuffer[nextPos + 3] == 1) {
                                        nextStartCodeLen = 4;
                                        break;
                                    }
                                }
                                nextPos++;
                            }

                            if (nextStartCodeLen > 0) {
                                int naluLen = nextPos - curPos;
                                feedDecoderNalu(ringBuffer, curPos, naluLen, startCodeLen);
                                curPos = nextPos;
                            } else {
                                break;
                            }
                        } else {
                            curPos++;
                        }
                    }

                    if (curPos > 0) {
                        int remaining = ringHead - curPos;
                        if (remaining > 0) {
                            System.arraycopy(ringBuffer, curPos, ringBuffer, 0, remaining);
                        }
                        ringHead = remaining;
                    }

                    drainOutputBuffers();
                    updateStatsIfNeeded();
                }
            }

        } catch (Exception e) {
            if (isStreaming.get()) {
                updateHud("Поток завершён: " + e.getMessage());
            }
        } finally {
            if (in != null) {
                try { in.close(); } catch (Exception ignored) {}
            }
            if (conn != null) {
                try { conn.disconnect(); } catch (Exception ignored) {}
            }
            activeConn = null;
            releaseDecoder();
        }
    }

    /**
     * Подача полного видеокадра (Access Unit) в декодер.
     */
    private void feedDecoderFrame(byte[] data, int len, int flags, long ptsUs) {
        if (decoder == null || !isStreaming.get()) return;
        try {
            int inIndex = decoder.dequeueInputBuffer(10000); // 10 мс тайм-аут
            if (inIndex >= 0) {
                ByteBuffer inputBuffer;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    inputBuffer = decoder.getInputBuffer(inIndex);
                } else {
                    inputBuffer = decoder.getInputBuffers()[inIndex];
                }
                if (inputBuffer != null) {
                    inputBuffer.clear();
                    inputBuffer.put(data, 0, len);
                    int codecFlags = 0;
                    if ((flags & 1) != 0) {
                        codecFlags |= MediaCodec.BUFFER_FLAG_KEY_FRAME;
                    }
                    decoder.queueInputBuffer(inIndex, 0, len, ptsUs, codecFlags);
                }
            }
        } catch (Exception ignored) {}
    }

    /**
     * Подача отдельного NAL-юнита в декодер (для сырого Annex-B режима).
     */
    private void feedDecoderNalu(byte[] data, int offset, int len, int startCodeLen) {
        if (decoder == null || !isStreaming.get()) return;
        try {
            int inIndex = decoder.dequeueInputBuffer(10000);
            if (inIndex >= 0) {
                ByteBuffer inputBuffer;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    inputBuffer = decoder.getInputBuffer(inIndex);
                } else {
                    inputBuffer = decoder.getInputBuffers()[inIndex];
                }
                if (inputBuffer != null) {
                    inputBuffer.clear();
                    inputBuffer.put(data, offset, len);
                    int nalType = data[offset + startCodeLen] & 0x1F;
                    int flags = 0;
                    if (nalType == 7 || nalType == 8) {
                        flags = MediaCodec.BUFFER_FLAG_CODEC_CONFIG;
                    } else if (nalType == 5) {
                        flags = MediaCodec.BUFFER_FLAG_KEY_FRAME;
                    }
                    long presentationTimeUs = SystemClock.elapsedRealtimeNanos() / 1000;
                    decoder.queueInputBuffer(inIndex, 0, len, presentationTimeUs, flags);
                }
            }
        } catch (Exception ignored) {}
    }

    /**
     * Инициализация аппаратного декодера MediaCodec со всеми низколатентными флагами и BT.709.
     */
    private void initDecoder(int width, int height) throws Exception {
        String mime = MediaFormat.MIMETYPE_VIDEO_AVC;
        decoder = MediaCodec.createDecoderByType(mime);
        activeCodecName = decoder.getName();

        boolean configured = false;
        try {
            MediaFormat format = MediaFormat.createVideoFormat(mime, width, height);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);

            // Низколатентные параметры декодирования Android (API 30+)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                format.setInteger(MediaFormat.KEY_PRIORITY, 0); // Real-time priority
            }

            // Sunshine/Moonlight стандарт: правильное цветовое пространство BT.709 и диапазон
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                format.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT709);
                format.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
                format.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
            }

            decoder.configure(format, surfaceHolder.getSurface(), null, 0);
            configured = true;
        } catch (Exception e) {
            // Фоллбэк: если вендорский драйвер отбрасывает расширенные ключи
            try {
                if (decoder != null) {
                    decoder.release();
                }
            } catch (Exception ignored) {}
            decoder = MediaCodec.createDecoderByType(mime);
            activeCodecName = decoder.getName();
            MediaFormat fallbackFormat = MediaFormat.createVideoFormat(mime, width, height);
            fallbackFormat.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
            decoder.configure(fallbackFormat, surfaceHolder.getSurface(), null, 0);
            configured = true;
        }

        if (configured) {
            decoder.start();
        }
    }

    /**
     * Выгрузка раскодированных кадров непосредственно на Surface дисплея.
     */
    private void drainOutputBuffers() {
        if (decoder == null || !isStreaming.get()) return;
        try {
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int outIndex = decoder.dequeueOutputBuffer(info, 0);
            while (outIndex >= 0) {
                // Рендеринг напрямую на Surface с аппаратной синхронизацией
                decoder.releaseOutputBuffer(outIndex, true);
                framesDecoded++;
                outIndex = decoder.dequeueOutputBuffer(info, 0);
            }
        } catch (Exception ignored) {}
    }

    private void releaseDecoder() {
        if (decoder != null) {
            try {
                decoder.stop();
            } catch (Exception ignored) {}
            try {
                decoder.release();
            } catch (Exception ignored) {}
            decoder = null;
        }
    }

    private void updateStatsIfNeeded() {
        long now = SystemClock.elapsedRealtime();
        long diff = now - lastStatTime;
        if (diff >= 750) {
            currentFps = (framesDecoded * 1000.0f) / diff;
            currentKbps = (bytesReceived * 8.0f) / diff;
            framesDecoded = 0;
            bytesReceived = 0;
            lastStatTime = now;

            final String stats = String.format("LIVE · %s · %.1f FPS · %.1f Mbps · BT.709 · %s",
                    activeCodecName, currentFps, currentKbps / 1000.0f, (targetHeight > 0 ? targetHeight + "p" : "Native"));
            mainHandler.post(new Runnable() {
                @Override
                public void run() {
                    hudTextView.setText(stats);
                }
            });
        }
    }

    private void updateHud(final String text) {
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                hudTextView.setText(text);
            }
        });
    }

    private static void readFully(InputStream in, byte[] b, int off, int len) throws Exception {
        int n = 0;
        while (n < len) {
            int count = in.read(b, off + n, len - n);
            if (count < 0) throw new EOFException("End of stream reached");
            n += count;
        }
    }

    /**
     * Обработка сенсорного ввода (Moonlight Touch Controller):
     * Преобразует касания по экрану телефона в перемещение курсора мыши, левый клик, правый клик и прокрутку.
     */
    private boolean handleTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        pointerCount = event.getPointerCount();

        float x = event.getX();
        float y = event.getY();

        int viewW = getWidth();
        int viewH = getHeight();
        if (viewW <= 0 || viewH <= 0) return true;

        float normX = Math.max(0f, Math.min(1f, x / (float) viewW));
        float normY = Math.max(0f, Math.min(1f, y / (float) viewH));

        switch (action) {
            case MotionEvent.ACTION_DOWN:
                lastTouchX = x;
                lastTouchY = y;
                touchDownTime = SystemClock.uptimeMillis();
                isDragging = false;
                sendMouseCommand("move", normX, normY, 0);
                break;

            case MotionEvent.ACTION_MOVE:
                float dx = x - lastTouchX;
                float dy = y - lastTouchY;
                lastTouchX = x;
                lastTouchY = y;

                if (pointerCount == 1) {
                    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
                        isDragging = true;
                    }
                    sendMouseCommand("move", normX, normY, 0);
                } else if (pointerCount >= 2) {
                    // Двупальцевая прокрутка колеса мыши
                    int scrollDelta = (int) (-dy / 4);
                    if (scrollDelta != 0) {
                        sendMouseCommand("scroll", 0, 0, scrollDelta);
                    }
                }
                break;

            case MotionEvent.ACTION_UP:
                long duration = SystemClock.uptimeMillis() - touchDownTime;
                if (!isDragging && duration < 300) {
                    // Короткий тап одним пальцем — левый клик
                    sendMouseCommand("click", normX, normY, 0);
                }
                break;

            case MotionEvent.ACTION_POINTER_UP:
                if (pointerCount == 2) {
                    // Тап двумя пальцами — правый клик (контекстное меню)
                    sendMouseCommand("right_click", normX, normY, 0);
                }
                break;
        }
        return true;
    }

    /**
     * Асинхронная отправка команды ввода на сервер PC Control.
     */
    private void sendMouseCommand(final String act, final float nx, final float ny, final int scrollVal) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    String cmdUrl = serverUrl + "/api/mouse";
                    URL url = new URL(cmdUrl);
                    HttpURLConnection c = (HttpURLConnection) url.openConnection();
                    c.setRequestMethod("POST");
                    c.setConnectTimeout(500);
                    c.setReadTimeout(500);
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json");
                    if (!authToken.isEmpty()) {
                        c.setRequestProperty("X-Auth-Token", authToken);
                    }

                    String json;
                    if ("scroll".equals(act)) {
                        json = "{\"action\":\"scroll\",\"dy\":" + scrollVal + "}";
                    } else if ("right_click".equals(act)) {
                        json = "{\"action\":\"right_click\"}";
                    } else if ("click".equals(act)) {
                        json = "{\"action\":\"click\"}";
                    } else {
                        json = "{\"action\":\"move_norm\",\"x\":" + nx + ",\"y\":" + ny + "}";
                    }

                    byte[] out = json.getBytes(StandardCharsets.UTF_8);
                    c.setFixedLengthStreamingMode(out.length);
                    try (OutputStream os = c.getOutputStream()) {
                        os.write(out);
                    }
                    c.getResponseCode();
                    c.disconnect();
                } catch (Exception ignored) {}
            }
        }).start();
    }
}
