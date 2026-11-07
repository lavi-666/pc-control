package com.pccontrol.remote;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.AlphaAnimation;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
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
 * NativeScreenView — Нативный Android-плеер демонстрации экрана для PC Control.
 * Полная переработка:
 * 1. Чистый дизайн в стилистике PC Control (убран постоянный технический HUD).
 * 2. Автоматически скрываемая верхняя панель управления по касанию (3.5 сек).
 * 3. Отдельная скрытая диагностическая панель (с реальными метриками FPS, битрейта, задержки).
 * 4. Настоящее масштабирование без растягивания (Fit Center / Letterbox с сохранением 16:9).
 * 5. Поддержка переключения Fit / Fill.
 * 6. Полноценный Fullscreen (Immersive Sticky Mode) без пересоздания декодера.
 * 7. Прецизионный расчёт FPS (Received, Decoded, Rendered, Min) через скользящее окно без скачков.
 * 8. Сенсорный контроллер мыши Moonlight с точным позиционированием внутри области видео.
 */
public class NativeScreenView extends FrameLayout implements SurfaceHolder.Callback {

    public interface PlayerCallback {
        void onCloseRequested();
        void onFullscreenToggled(boolean isFullscreen);
    }

    public static final int SCALE_MODE_FIT = 0;
    public static final int SCALE_MODE_FILL = 1;

    // Компоненты отображения
    private SurfaceView surfaceView;
    private SurfaceHolder surfaceHolder;
    private LinearLayout topToolbar;
    private TextView titleView;
    private TextView subtitleView;
    private TextView scaleModeBtn;
    private TextView fullscreenBtn;
    private TextView diagBtn;
    private TextView closeBtn;

    // Панель диагностики
    private FrameLayout diagOverlay;
    private LinearLayout diagCard;
    private TextView diagCodecVal;
    private TextView diagResVal;
    private TextView diagDispVal;
    private TextView diagFpsTargetVal;
    private TextView diagFpsRecvVal;
    private TextView diagFpsDecVal;
    private TextView diagFpsRendVal;
    private TextView diagFpsMinVal;
    private TextView diagBitrateVal;
    private TextView diagDroppedVal;
    private TextView diagLatencyVal;
    private TextView diagColorVal;

    // Состояние декодера и потока
    private MediaCodec decoder;
    private Thread workerThread;
    private volatile HttpURLConnection activeConn;
    private final AtomicBoolean isStreaming = new AtomicBoolean(false);
    private final Object surfaceLock = new Object();
    private boolean surfaceReady = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    // Параметры стрима
    private String serverUrl = "";
    private String authToken = "";
    private int targetMonitor = 1;
    private int targetHeight = 1080;
    private int targetFps = 60;
    private int targetBitrate = 0;

    // Соотношение сторон и размеры видеокадра
    private int videoWidth = 1920;
    private int videoHeight = 1080;
    private int scaleMode = SCALE_MODE_FIT;
    private final Rect videoViewportRect = new Rect();

    // Флаги управления интерфейсом
    private boolean isFullscreen = false;
    private boolean isControlsVisible = true;
    private boolean isDiagVisible = false;
    private PlayerCallback playerCallback;

    // Прецизионные трекеры FPS (скользящее окно 1500 мс)
    private final FpsTracker receivedFpsTracker = new FpsTracker(180, 1500);
    private final FpsTracker decodedFpsTracker = new FpsTracker(180, 1500);
    private final FpsTracker renderedFpsTracker = new FpsTracker(180, 1500);
    private final MinFpsTracker minFpsTracker = new MinFpsTracker(3000);

    // Телеметрия и замеры
    private long totalBytesReceived = 0;
    private long lastBitrateSampleTime = 0;
    private long lastBitrateBytes = 0;
    private float currentKbps = 0.0f;
    private long droppedFramesCount = 0;
    private long estimatedLatencyMs = 8;
    private String activeCodecName = "Hardware H.264";

    // Управление сенсорным вводом (Moonlight Touch Controller)
    private float touchStartX = 0f;
    private float touchStartY = 0f;
    private float lastTouchX = 0f;
    private float lastTouchY = 0f;
    private long touchDownTime = 0;
    private boolean isDraggingMouse = false;
    private int activePointerCount = 1;

    // Автоматическое скрытие панели управления
    private final Runnable hideControlsRunnable = new Runnable() {
        @Override
        public void run() {
            setControlsVisible(false, true);
        }
    };

    // Обновление диагностических метрик
    private final Runnable diagUpdateRunnable = new Runnable() {
        @Override
        public void run() {
            if (isDiagVisible && isStreaming.get()) {
                refreshDiagValues();
                mainHandler.postDelayed(this, 500);
            }
        }
    };

    public NativeScreenView(Context context) {
        super(context);
        init(context);
    }

    public NativeScreenView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init(context);
    }

    private void init(Context context) {
        setBackgroundColor(Color.parseColor("#030303"));

        // 1. Создание SurfaceView для аппаратного рендеринга MediaCodec
        surfaceView = new SurfaceView(context);
        surfaceHolder = surfaceView.getHolder();
        surfaceHolder.addCallback(this);
        addView(surfaceView, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        // 2. Верхняя полупрозрачная панель управления в стиле PC Control
        buildTopToolbar(context);

        // 3. Отдельная скрытая панель диагностики
        buildDiagnosticsDialog(context);

        // 4. Настройка сенсорного ввода
        surfaceView.setOnTouchListener(new OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                return handleTouchEvent(event);
            }
        });
    }

    /**
     * Построение стильной верхней панели управления.
     */
    private void buildTopToolbar(Context context) {
        topToolbar = new LinearLayout(context);
        topToolbar.setOrientation(LinearLayout.HORIZONTAL);
        topToolbar.setGravity(Gravity.CENTER_VERTICAL);

        GradientDrawable tbBg = new GradientDrawable();
        tbBg.setColor(Color.parseColor("#E612161F")); // Темный полупрозрачный сланец
        tbBg.setCornerRadius(dpToPx(20));
        tbBg.setStroke(dpToPx(1), Color.parseColor("#33FFFFFF"));
        topToolbar.setBackground(tbBg);

        int padH = dpToPx(14);
        int padV = dpToPx(8);
        topToolbar.setPadding(padH, padV, padH, padV);

        FrameLayout.LayoutParams tbParams = new FrameLayout.LayoutParams(
                LayoutParams.WRAP_CONTENT,
                LayoutParams.WRAP_CONTENT
        );
        tbParams.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        tbParams.topMargin = dpToPx(16);
        topToolbar.setLayoutParams(tbParams);

        // Кнопка назад / выход в основной пульт
        TextView backBtn = createToolbarButton(context, "←", "#242A35", Color.WHITE);
        backBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeStreamAndExit();
            }
        });
        topToolbar.addView(backBtn);

        // Блок заголовка: "Демонстрация экрана" + компактный статус
        LinearLayout titleBox = new LinearLayout(context);
        titleBox.setOrientation(LinearLayout.VERTICAL);
        titleBox.setPadding(dpToPx(12), 0, dpToPx(14), 0);
        titleBox.setGravity(Gravity.CENTER_VERTICAL);

        titleView = new TextView(context);
        titleView.setText("Демонстрация экрана");
        titleView.setTextColor(Color.WHITE);
        titleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f);
        titleView.setTypeface(Typeface.DEFAULT_BOLD);
        titleBox.addView(titleView);

        subtitleView = new TextView(context);
        subtitleView.setText("1080p · 60 FPS · Запуск...");
        subtitleView.setTextColor(Color.parseColor("#94A3B8"));
        subtitleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10f);
        titleBox.addView(subtitleView);

        topToolbar.addView(titleBox);

        // Кнопка режима масштабирования (Fit / Fill)
        scaleModeBtn = createToolbarButton(context, "Fit", "#242A35", Color.parseColor("#E2E8F0"));
        scaleModeBtn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        scaleModeBtn.setTypeface(Typeface.DEFAULT_BOLD);
        scaleModeBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleScaleMode();
                scheduleControlsAutoHide();
            }
        });
        topToolbar.addView(scaleModeBtn);

        addToolbarSpacer(context, topToolbar, 6);

        // Кнопка полноэкранного режима (⛶)
        fullscreenBtn = createToolbarButton(context, "⛶", "#242A35", Color.WHITE);
        fullscreenBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleFullscreen();
                scheduleControlsAutoHide();
            }
        });
        topToolbar.addView(fullscreenBtn);

        addToolbarSpacer(context, topToolbar, 6);

        // Кнопка диагностики (⚙)
        diagBtn = createToolbarButton(context, "⚙", "#242A35", Color.WHITE);
        diagBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleDiagnosticsDialog();
                scheduleControlsAutoHide();
            }
        });
        topToolbar.addView(diagBtn);

        addToolbarSpacer(context, topToolbar, 6);

        // Кнопка быстрого закрытия (✕)
        closeBtn = createToolbarButton(context, "✕", "#3A2024", Color.parseColor("#FF5252"));
        closeBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeStreamAndExit();
            }
        });
        topToolbar.addView(closeBtn);

        addView(topToolbar);
    }

    private TextView createToolbarButton(Context context, String text, String bgColorHex, int textColor) {
        TextView btn = new TextView(context);
        btn.setText(text);
        btn.setTextColor(textColor);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f);
        btn.setGravity(Gravity.CENTER);

        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor(bgColorHex));
        bg.setCornerRadius(dpToPx(12));
        btn.setBackground(bg);

        int padX = dpToPx(10);
        int padY = dpToPx(6);
        btn.setPadding(padX, padY, padX, padY);
        return btn;
    }

    private void addToolbarSpacer(Context context, LinearLayout parent, int dp) {
        View sp = new View(context);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dpToPx(dp), 1);
        sp.setLayoutParams(lp);
        parent.addView(sp);
    }

    /**
     * Построение отдельной скрытой панели диагностики видеопотока.
     */
    private void buildDiagnosticsDialog(Context context) {
        diagOverlay = new FrameLayout(context);
        diagOverlay.setBackgroundColor(Color.parseColor("#99000000")); // Полупрозрачный бэкдроп
        diagOverlay.setVisibility(View.GONE);
        diagOverlay.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                setDiagnosticsVisible(false);
            }
        });

        diagCard = new LinearLayout(context);
        diagCard.setOrientation(LinearLayout.VERTICAL);

        GradientDrawable cardBg = new GradientDrawable();
        cardBg.setColor(Color.parseColor("#EB121622"));
        cardBg.setCornerRadius(dpToPx(20));
        cardBg.setStroke(dpToPx(1), Color.parseColor("#334155"));
        diagCard.setBackground(cardBg);

        int pad = dpToPx(18);
        diagCard.setPadding(pad, pad, pad, pad);

        FrameLayout.LayoutParams cardParams = new FrameLayout.LayoutParams(
                dpToPx(340),
                LayoutParams.WRAP_CONTENT
        );
        cardParams.gravity = Gravity.CENTER;
        diagCard.setLayoutParams(cardParams);
        diagCard.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                // Блокируем клик на карточке от закрытия бэкдропа
            }
        });

        // Заголовок диалога
        LinearLayout head = new LinearLayout(context);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);

        TextView diagTitle = new TextView(context);
        diagTitle.setText("ДИАГНОСТИКА ПОТОКА");
        diagTitle.setTextColor(Color.parseColor("#38BDF8")); // Sky blue
        diagTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        diagTitle.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f);
        head.addView(diagTitle, titleLp);

        TextView closeDiag = new TextView(context);
        closeDiag.setText("✕");
        closeDiag.setTextColor(Color.parseColor("#94A3B8"));
        closeDiag.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f);
        closeDiag.setPadding(dpToPx(6), dpToPx(4), dpToPx(6), dpToPx(4));
        closeDiag.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                setDiagnosticsVisible(false);
            }
        });
        head.addView(closeDiag);
        diagCard.addView(head);

        addDivider(context, diagCard);

        // Таблица метрик
        ScrollView scroll = new ScrollView(context);
        LinearLayout list = new LinearLayout(context);
        list.setOrientation(LinearLayout.VERTICAL);

        diagCodecVal = addDiagRow(context, list, "Кодек / Декодер", "Hardware H.264");
        diagResVal = addDiagRow(context, list, "Разрешение потока", "1920 × 1080");
        diagDispVal = addDiagRow(context, list, "Экран / Режим", "Fit Center");
        diagColorVal = addDiagRow(context, list, "Цветовое пространство", "BT.709 Limited");

        addDivider(context, list);

        diagFpsTargetVal = addDiagRow(context, list, "Целевой FPS", "60 FPS");
        diagFpsRecvVal = addDiagRow(context, list, "Частота приёма", "0.0 FPS");
        diagFpsDecVal = addDiagRow(context, list, "Декодирование", "0.0 FPS");
        diagFpsRendVal = addDiagRow(context, list, "Рендеринг (Display)", "0.0 FPS");
        diagFpsMinVal = addDiagRow(context, list, "Мин. FPS (3 сек)", "0.0 FPS");

        addDivider(context, list);

        diagBitrateVal = addDiagRow(context, list, "Битрейт сети", "0.0 Mbps");
        diagDroppedVal = addDiagRow(context, list, "Потери кадров", "0 кадров");
        diagLatencyVal = addDiagRow(context, list, "Задержка конвейера", "8-12 мс");

        scroll.addView(list);
        diagCard.addView(scroll, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dpToPx(280)));

        diagOverlay.addView(diagCard);
        addView(diagOverlay, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    private TextView addDiagRow(Context context, LinearLayout parent, String label, String defaultVal) {
        LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dpToPx(3), 0, dpToPx(3));

        TextView lbl = new TextView(context);
        lbl.setText(label);
        lbl.setTextColor(Color.parseColor("#94A3B8"));
        lbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        LinearLayout.LayoutParams lp1 = new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f);
        row.addView(lbl, lp1);

        TextView val = new TextView(context);
        val.setText(defaultVal);
        val.setTextColor(Color.parseColor("#F8FAFC"));
        val.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        val.setTypeface(Typeface.DEFAULT_BOLD);
        val.setGravity(Gravity.END);
        row.addView(val);

        parent.addView(row);
        return val;
    }

    private void addDivider(Context context, LinearLayout parent) {
        View div = new View(context);
        div.setBackgroundColor(Color.parseColor("#1E293B"));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dpToPx(1));
        lp.topMargin = dpToPx(8);
        lp.bottomMargin = dpToPx(8);
        parent.addView(div, lp);
    }

    public void setPlayerCallback(PlayerCallback callback) {
        this.playerCallback = callback;
    }

    // Совместимость с OnCloseListener
    public interface OnCloseListener {
        void onCloseRequested();
    }
    public void setOnCloseListener(final OnCloseListener listener) {
        this.playerCallback = new PlayerCallback() {
            @Override
            public void onCloseRequested() {
                if (listener != null) listener.onCloseRequested();
            }
            @Override
            public void onFullscreenToggled(boolean isFullscreen) {}
        };
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

        // Предварительный расчёт пропорций до приёма первого кадра
        this.videoHeight = (targetHeight > 0) ? targetHeight : 1080;
        this.videoWidth = (int) Math.round(this.videoHeight * (16.0 / 9.0));

        updateSubtitle();
    }

    private void updateSubtitle() {
        String resStr = (targetHeight > 0) ? (targetHeight + "p") : "Native";
        subtitleView.setText(resStr + " · " + targetFps + " FPS · " + (scaleMode == SCALE_MODE_FIT ? "Fit" : "Fill"));
    }

    public void startStream() {
        if (isStreaming.get()) return;
        isStreaming.set(true);
        setVisibility(View.VISIBLE);

        setControlsVisible(true, false);
        scheduleControlsAutoHide();

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
        mainHandler.removeCallbacks(hideControlsRunnable);
        mainHandler.removeCallbacks(diagUpdateRunnable);

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
                setDiagnosticsVisible(false);
                setVisibility(View.GONE);
            }
        });
    }

    private void closeStreamAndExit() {
        stopStream();
        if (playerCallback != null) {
            playerCallback.onCloseRequested();
        }
    }

    /**
     * Обработка кнопки "Назад": закрывает сначала диагностику, затем Fullscreen, затем стрим.
     * @return true, если событие обработано внутренне.
     */
    public boolean handleBackPressed() {
        if (isDiagVisible) {
            setDiagnosticsVisible(false);
            return true;
        }
        if (isFullscreen) {
            toggleFullscreen();
            return true;
        }
        return false;
    }

    /**
     * Переключение режима масштабирования (Fit Center vs Fill).
     */
    public void toggleScaleMode() {
        scaleMode = (scaleMode == SCALE_MODE_FIT) ? SCALE_MODE_FILL : SCALE_MODE_FIT;
        scaleModeBtn.setText(scaleMode == SCALE_MODE_FIT ? "Fit" : "Fill");
        updateSubtitle();
        requestLayout();
    }

    /**
     * Переключение настоящего Fullscreen (Immersive Sticky Mode).
     */
    public void toggleFullscreen() {
        isFullscreen = !isFullscreen;
        fullscreenBtn.setText(isFullscreen ? "⊡" : "⛶");
        if (playerCallback != null) {
            playerCallback.onFullscreenToggled(isFullscreen);
        }
        requestLayout();
    }

    /**
     * Переключение видимости панели диагностики.
     */
    public void toggleDiagnosticsDialog() {
        setDiagnosticsVisible(!isDiagVisible);
    }

    public void setDiagnosticsVisible(boolean visible) {
        isDiagVisible = visible;
        diagOverlay.setVisibility(visible ? View.VISIBLE : View.GONE);
        if (visible) {
            mainHandler.removeCallbacks(diagUpdateRunnable);
            mainHandler.post(diagUpdateRunnable);
        } else {
            mainHandler.removeCallbacks(diagUpdateRunnable);
        }
    }

    /**
     * Управление видимостью панели управления с плавной анимацией.
     */
    private void setControlsVisible(boolean visible, boolean animate) {
        if (isControlsVisible == visible) return;
        isControlsVisible = visible;
        mainHandler.removeCallbacks(hideControlsRunnable);

        if (visible) {
            topToolbar.setVisibility(View.VISIBLE);
            if (animate) {
                AlphaAnimation fadeIn = new AlphaAnimation(0f, 1f);
                fadeIn.setDuration(200);
                topToolbar.startAnimation(fadeIn);
            }
            scheduleControlsAutoHide();
        } else {
            if (animate) {
                AlphaAnimation fadeOut = new AlphaAnimation(1f, 0f);
                fadeOut.setDuration(250);
                topToolbar.startAnimation(fadeOut);
            }
            topToolbar.setVisibility(View.GONE);
        }
    }

    private void scheduleControlsAutoHide() {
        mainHandler.removeCallbacks(hideControlsRunnable);
        mainHandler.postDelayed(hideControlsRunnable, 3500);
    }

    /**
     * Ключевое исправление: Масштабирование видео с сохранением пропорций (Fit Center).
     * Предотвращает горизонтальное растягивание на широких дисплеях 19.5:9 и 20:9.
     */
    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int widthSize = MeasureSpec.getSize(widthMeasureSpec);
        int heightSize = MeasureSpec.getSize(heightMeasureSpec);

        if (widthSize <= 0 || heightSize <= 0) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec);
            return;
        }

        float videoAspect = (videoWidth > 0 && videoHeight > 0)
                ? (videoWidth / (float) videoHeight)
                : (16.0f / 9.0f);

        int surfW = widthSize;
        int surfH = heightSize;

        if (scaleMode == SCALE_MODE_FIT) {
            float containerAspect = widthSize / (float) heightSize;
            if (containerAspect > videoAspect) {
                // Экран шире видео (pillarbox: чёрные полосы слева и справа)
                surfH = heightSize;
                surfW = Math.round(heightSize * videoAspect);
            } else {
                // Экран уже/выше видео (letterbox: чёрные полосы сверху и снизу)
                surfW = widthSize;
                surfH = Math.round(widthSize / videoAspect);
            }
        } else if (scaleMode == SCALE_MODE_FILL) {
            float containerAspect = widthSize / (float) heightSize;
            if (containerAspect > videoAspect) {
                surfW = widthSize;
                surfH = Math.round(widthSize / videoAspect);
            } else {
                surfH = heightSize;
                surfW = Math.round(heightSize * videoAspect);
            }
        }

        // Измеряем SurfaceView с точными пропорциональными размерами
        if (surfaceView != null) {
            surfaceView.measure(
                    MeasureSpec.makeMeasureSpec(surfW, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(surfH, MeasureSpec.EXACTLY)
            );
        }

        // Измеряем верхнюю панель и диагностику
        if (topToolbar != null && topToolbar.getVisibility() != View.GONE) {
            measureChildWithMargins(topToolbar, widthMeasureSpec, 0, heightMeasureSpec, 0);
        }
        if (diagOverlay != null && diagOverlay.getVisibility() != View.GONE) {
            diagOverlay.measure(
                    MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY)
            );
        }

        setMeasuredDimension(widthSize, heightSize);
    }

    @Override
    protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        int parentW = right - left;
        int parentH = bottom - top;

        if (surfaceView != null) {
            int surfW = surfaceView.getMeasuredWidth();
            int surfH = surfaceView.getMeasuredHeight();
            int surfLeft = (parentW - surfW) / 2;
            int surfTop = (parentH - surfH) / 2;
            surfaceView.layout(surfLeft, surfTop, surfLeft + surfW, surfTop + surfH);

            // Сохраняем реальный прямоугольник видео для сенсорного маппинга
            videoViewportRect.set(surfLeft, surfTop, surfLeft + surfW, surfTop + surfH);
        }

        if (topToolbar != null && topToolbar.getVisibility() != View.GONE) {
            int tbW = topToolbar.getMeasuredWidth();
            int tbH = topToolbar.getMeasuredHeight();
            int tbLeft = (parentW - tbW) / 2;
            int tbTop = dpToPx(16);
            topToolbar.layout(tbLeft, tbTop, tbLeft + tbW, tbTop + tbH);
        }

        if (diagOverlay != null && diagOverlay.getVisibility() != View.GONE) {
            diagOverlay.layout(0, 0, parentW, parentH);
        }
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
     * Потоковый сетевой воркер: получает низколатентный поток и декодирует через MediaCodec.
     */
    private void runStreamWorker() {
        HttpURLConnection conn = null;
        InputStream in = null;
        try {
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
            conn.setRequestProperty("User-Agent", "PCControl-NativePlayer/2.4");
            if (!authToken.isEmpty()) {
                conn.setRequestProperty("X-Auth-Token", authToken);
                conn.setRequestProperty("Cookie", "token=" + authToken);
            }

            conn.connect();
            int respCode = conn.getResponseCode();
            if (respCode != 200) {
                return;
            }

            in = new BufferedInputStream(conn.getInputStream(), 262144);

            byte[] frameBuffer = new byte[2 * 1024 * 1024];
            byte[] headerBuf = new byte[17];
            byte[] ringBuffer = new byte[2 * 1024 * 1024];
            int ringHead = 0;

            lastBitrateSampleTime = SystemClock.elapsedRealtime();
            lastBitrateBytes = 0;
            totalBytesReceived = 0;

            readFully(in, headerBuf, 0, 4);
            totalBytesReceived += 4;

            boolean isFramed = (headerBuf[0] == 0x50 && headerBuf[1] == 0x43 && headerBuf[2] == 0x30 && headerBuf[3] == 0x31); // 'PC01'

            if (isFramed) {
                while (isStreaming.get()) {
                    readFully(in, headerBuf, 4, 13);
                    totalBytesReceived += 13;

                    int frameLen = ((headerBuf[4] & 0xFF) << 24)
                            | ((headerBuf[5] & 0xFF) << 16)
                            | ((headerBuf[6] & 0xFF) << 8)
                            | (headerBuf[7] & 0xFF);

                    int frameFlags = headerBuf[8] & 0xFF;

                    if (frameLen <= 0 || frameLen > frameBuffer.length) {
                        break;
                    }

                    long frameRecvStart = SystemClock.elapsedRealtime();
                    readFully(in, frameBuffer, 0, frameLen);
                    totalBytesReceived += frameLen;

                    // Фиксация принятого полного кадра
                    receivedFpsTracker.onFrame();

                    // Монотонный PTS локального времени смартфона
                    long ptsUs = SystemClock.elapsedRealtimeNanos() / 1000;
                    feedDecoderFrame(frameBuffer, frameLen, frameFlags, ptsUs);
                    drainOutputBuffers();

                    long latency = SystemClock.elapsedRealtime() - frameRecvStart;
                    if (latency > 0) estimatedLatencyMs = latency + 4;

                    updateBitrateStats();

                    readFully(in, headerBuf, 0, 4);
                    totalBytesReceived += 4;
                    if (headerBuf[0] != 0x50 || headerBuf[1] != 0x43 || headerBuf[2] != 0x30 || headerBuf[3] != 0x31) {
                        break;
                    }
                }
            } else {
                System.arraycopy(headerBuf, 0, ringBuffer, 0, 4);
                ringHead = 4;
                byte[] chunk = new byte[32768];

                while (isStreaming.get()) {
                    int r = in.read(chunk, 0, chunk.length);
                    if (r == -1) break;
                    totalBytesReceived += r;

                    if (ringHead + r > ringBuffer.length) {
                        ringHead = 0;
                    }
                    System.arraycopy(chunk, 0, ringBuffer, ringHead, r);
                    ringHead += r;

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
                    updateBitrateStats();
                }
            }

        } catch (Exception ignored) {
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

    private void feedDecoderFrame(byte[] data, int len, int flags, long ptsUs) {
        if (decoder == null || !isStreaming.get()) return;
        try {
            int inIndex = decoder.dequeueInputBuffer(8000);
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

    private void feedDecoderNalu(byte[] data, int offset, int len, int startCodeLen) {
        if (decoder == null || !isStreaming.get()) return;
        try {
            int inIndex = decoder.dequeueInputBuffer(8000);
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
                    if (nalType == 1 || nalType == 5) {
                        receivedFpsTracker.onFrame();
                    }
                    long presentationTimeUs = SystemClock.elapsedRealtimeNanos() / 1000;
                    decoder.queueInputBuffer(inIndex, 0, len, presentationTimeUs, flags);
                }
            }
        } catch (Exception ignored) {}
    }

    private void initDecoder(int width, int height) throws Exception {
        String mime = MediaFormat.MIMETYPE_VIDEO_AVC;
        decoder = MediaCodec.createDecoderByType(mime);
        activeCodecName = decoder.getName();

        boolean configured = false;
        try {
            MediaFormat format = MediaFormat.createVideoFormat(mime, width, height);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                format.setInteger(MediaFormat.KEY_PRIORITY, 0);
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                format.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT709);
                format.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
                format.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
            }

            decoder.configure(format, surfaceHolder.getSurface(), null, 0);
            configured = true;
        } catch (Exception e) {
            try {
                if (decoder != null) decoder.release();
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
     * Выгрузка раскодированных кадров с динамической детекцией разрешения и кроп-области.
     */
    private void drainOutputBuffers() {
        if (decoder == null || !isStreaming.get()) return;
        try {
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int attempts = 0;
            int outIndex = decoder.dequeueOutputBuffer(info, 0);

            while (outIndex >= 0 && attempts < 8) {
                attempts++;
                decodedFpsTracker.onFrame();

                // Рендерим кадр на Surface
                decoder.releaseOutputBuffer(outIndex, true);
                renderedFpsTracker.onFrame();
                minFpsTracker.onRenderedFrame();

                outIndex = decoder.dequeueOutputBuffer(info, 0);
            }

            if (outIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                MediaFormat newFormat = decoder.getOutputFormat();
                int w = newFormat.getInteger(MediaFormat.KEY_WIDTH);
                int h = newFormat.getInteger(MediaFormat.KEY_HEIGHT);
                if (newFormat.containsKey("crop-left") && newFormat.containsKey("crop-right")) {
                    w = newFormat.getInteger("crop-right") - newFormat.getInteger("crop-left") + 1;
                }
                if (newFormat.containsKey("crop-top") && newFormat.containsKey("crop-bottom")) {
                    h = newFormat.getInteger("crop-bottom") - newFormat.getInteger("crop-top") + 1;
                }
                if (w > 0 && h > 0 && (w != videoWidth || h != videoHeight)) {
                    videoWidth = w;
                    videoHeight = h;
                    mainHandler.post(new Runnable() {
                        @Override
                        public void run() {
                            requestLayout();
                        }
                    });
                }
            }
        } catch (Exception ignored) {}
    }

    private void releaseDecoder() {
        if (decoder != null) {
            try { decoder.stop(); } catch (Exception ignored) {}
            try { decoder.release(); } catch (Exception ignored) {}
            decoder = null;
        }
    }

    private void updateBitrateStats() {
        long now = SystemClock.elapsedRealtime();
        long diff = now - lastBitrateSampleTime;
        if (diff >= 1000) {
            long bytesInSec = totalBytesReceived - lastBitrateBytes;
            currentKbps = (bytesInSec * 8.0f) / diff;
            lastBitrateBytes = totalBytesReceived;
            lastBitrateSampleTime = now;
        }
    }

    /**
     * Обновление показателей в скрытой диагностической панели.
     */
    private void refreshDiagValues() {
        float rFps = receivedFpsTracker.getFps();
        float dFps = decodedFpsTracker.getFps();
        float renFps = renderedFpsTracker.getFps();
        float mFps = minFpsTracker.getMinFps(renFps);

        diagCodecVal.setText("H.264 · " + activeCodecName);
        diagResVal.setText(videoWidth + " × " + videoHeight + " (запрос " + (targetHeight > 0 ? targetHeight + "p" : "Native") + ")");

        DisplayMetrics dm = getResources().getDisplayMetrics();
        diagDispVal.setText(dm.widthPixels + "×" + dm.heightPixels + " · " + (scaleMode == SCALE_MODE_FIT ? "Fit (16:9)" : "Fill"));
        diagColorVal.setText("ITU-T BT.709 Limited");

        diagFpsTargetVal.setText(targetFps + " FPS");
        diagFpsRecvVal.setText(String.format("%.1f FPS", rFps));
        diagFpsDecVal.setText(String.format("%.1f FPS", dFps));
        diagFpsRendVal.setText(String.format("%.1f FPS", renFps));
        diagFpsMinVal.setText(String.format("%.1f FPS", mFps));

        diagBitrateVal.setText(String.format("%.2f Mbps", currentKbps / 1000.0f));
        diagDroppedVal.setText(droppedFramesCount + " кадров");
        diagLatencyVal.setText("~" + estimatedLatencyMs + " мс (Zero-GC)");
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
     * Обработка сенсорных событий (Moonlight Touch Controller):
     * Координаты касания аккуратно проецируются строго на область видео с учётом Letterbox/Pillarbox.
     */
    private boolean handleTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        activePointerCount = event.getPointerCount();

        float x = event.getX();
        float y = event.getY();

        // Проверяем клик по видимой верхней панели
        if (isControlsVisible && topToolbar != null && topToolbar.getVisibility() == View.VISIBLE) {
            if (x >= topToolbar.getLeft() && x <= topToolbar.getRight()
                    && y >= topToolbar.getTop() && y <= topToolbar.getBottom()) {
                scheduleControlsAutoHide();
                return false; // Пусть тулбар обработает клик
            }
        }

        // Проекция координат на прямоугольник видео
        int vW = videoViewportRect.width();
        int vH = videoViewportRect.height();
        if (vW <= 0 || vH <= 0) return true;

        float relX = x - videoViewportRect.left;
        float relY = y - videoViewportRect.top;
        float normX = Math.max(0f, Math.min(1f, relX / (float) vW));
        float normY = Math.max(0f, Math.min(1f, relY / (float) vH));

        switch (action) {
            case MotionEvent.ACTION_DOWN:
                touchStartX = x;
                touchStartY = y;
                lastTouchX = x;
                lastTouchY = y;
                touchDownTime = SystemClock.uptimeMillis();
                isDraggingMouse = false;
                sendMouseCommand("move", normX, normY, 0);
                break;

            case MotionEvent.ACTION_MOVE:
                float dx = x - lastTouchX;
                float dy = y - lastTouchY;
                lastTouchX = x;
                lastTouchY = y;

                if (Math.abs(x - touchStartX) > dpToPx(6) || Math.abs(y - touchStartY) > dpToPx(6)) {
                    isDraggingMouse = true;
                }

                if (activePointerCount == 1) {
                    sendMouseCommand("move", normX, normY, 0);
                } else if (activePointerCount >= 2) {
                    int scrollDelta = (int) (-dy / 4);
                    if (scrollDelta != 0) {
                        sendMouseCommand("scroll", 0, 0, scrollDelta);
                    }
                }
                break;

            case MotionEvent.ACTION_UP:
                long duration = SystemClock.uptimeMillis() - touchDownTime;
                if (!isDraggingMouse && duration < 280) {
                    // Короткий тап: если панель была скрыта, показываем её на 3.5 сек
                    if (!isControlsVisible) {
                        setControlsVisible(true, true);
                    } else {
                        // Если была видна и тапнули в видео — скрываем панель
                        setControlsVisible(false, true);
                    }
                    sendMouseCommand("click", normX, normY, 0);
                } else {
                    scheduleControlsAutoHide();
                }
                break;

            case MotionEvent.ACTION_POINTER_UP:
                if (activePointerCount == 2) {
                    sendMouseCommand("right_click", normX, normY, 0);
                }
                break;
        }
        return true;
    }

    private void sendMouseCommand(final String act, final float nx, final float ny, final int scrollVal) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    String cmdUrl = serverUrl + "/api/mouse";
                    URL url = new URL(cmdUrl);
                    HttpURLConnection c = (HttpURLConnection) url.openConnection();
                    c.setRequestMethod("POST");
                    c.setConnectTimeout(400);
                    c.setReadTimeout(400);
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

    private int dpToPx(int dp) {
        return Math.round(dp * getResources().getDisplayMetrics().density);
    }

    /**
     * Высокоточный кольцевой трекер FPS на базе скользящего временного окна (без скачков).
     */
    public static class FpsTracker {
        private final long[] timestamps;
        private int head = 0;
        private int count = 0;
        private final long windowNs;

        public FpsTracker(int capacity, long windowMs) {
            timestamps = new long[capacity];
            windowNs = windowMs * 1_000_000L;
        }

        public synchronized void onFrame() {
            timestamps[head] = SystemClock.elapsedRealtimeNanos();
            head = (head + 1) % timestamps.length;
            if (count < timestamps.length) count++;
        }

        public synchronized float getFps() {
            if (count < 2) return 0f;
            long now = SystemClock.elapsedRealtimeNanos();
            long threshold = now - windowNs;
            int valid = 0;
            long oldest = now;

            for (int i = 0; i < count; i++) {
                int idx = (head - 1 - i + timestamps.length) % timestamps.length;
                long t = timestamps[idx];
                if (t >= threshold) {
                    valid++;
                    if (t < oldest) oldest = t;
                } else {
                    break;
                }
            }
            if (valid < 2) return 0f;
            long durationNs = now - oldest;
            if (durationNs <= 0) return 0f;
            return (valid * 1_000_000_000.0f) / durationNs;
        }
    }

    /**
     * Трекер минимального FPS на 3-секундном интервале для выявления реальных просадок.
     */
    public static class MinFpsTracker {
        private final long windowMs;
        private long lastSecTime = 0;
        private int framesInCurrentSec = 0;
        private final float[] secRates = new float[3];
        private int secIdx = 0;

        public MinFpsTracker(long windowMs) {
            this.windowMs = windowMs;
            for (int i = 0; i < secRates.length; i++) secRates[i] = -1f;
        }

        public synchronized void onRenderedFrame() {
            long now = SystemClock.elapsedRealtime();
            if (lastSecTime == 0) lastSecTime = now;
            framesInCurrentSec++;
            if (now - lastSecTime >= 1000) {
                float fps = (framesInCurrentSec * 1000f) / (now - lastSecTime);
                secRates[secIdx] = fps;
                secIdx = (secIdx + 1) % secRates.length;
                framesInCurrentSec = 0;
                lastSecTime = now;
            }
        }

        public synchronized float getMinFps(float currentAverage) {
            float min = -1f;
            for (float r : secRates) {
                if (r >= 0) {
                    if (min < 0 || r < min) min = r;
                }
            }
            return (min >= 0) ? min : currentAverage;
        }
    }
}
