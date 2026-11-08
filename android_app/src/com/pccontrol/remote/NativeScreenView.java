package com.pccontrol.remote;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.TextUtils;
import android.util.AttributeSet;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.AccelerateInterpolator;
import android.view.animation.AlphaAnimation;
import android.view.animation.DecelerateInterpolator;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedInputStream;
import java.io.EOFException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * NativeScreenView — Нативный Android-плеер демонстрации экрана и режим «Управление ПК» для PC Control.
 *
 * Поддерживает 2 режима работы:
 * 1. MODE_VIEW (Демонстрация экрана): просмотр экрана без захвата сенсорного ввода.
 * 2. MODE_PC_CONTROL (Управление ПК):
 *    - Прозрачный виртуальный тачпад поверх видео
 *    - Плавающая шестерёнка (⚙) и стрелочка (◀/▶) с выдвижным меню быстрых функций
 *    - 4 быстрых переключателя: Клавиатура, Микрофон (телефон -> ПК), Звук ПК, Тачпад
 *    - Анимированный Split-Screen редактор настроек (живое уменьшение видео слева, параметры справа)
 *    - Настраиваемый тачпад с живым предпросмотром и перетаскиванием 8 маркеров на экране
 *    - Собственная встроенная экранная клавиатура (EN, RU, UK, 123/Symbols) с модификаторами
 *    - Индивидуальная настройка прозрачности 14 элементов интерфейса
 *    - Низколатентный неблокирующий диспетчер ввода (coalescing mouse queue)
 */
public class NativeScreenView extends FrameLayout implements SurfaceHolder.Callback {

    public static final int MODE_VIEW = 0;
    public static final int MODE_PC_CONTROL = 1;

    public static final int SCALE_MODE_FIT = 0;
    public static final int SCALE_MODE_FILL = 1;

    public interface PlayerCallback {
        void onCloseRequested();
        void onFullscreenToggled(boolean isFullscreen);
        void onSettingsChanged(int monitor, int height, int fps, int bitrate);
    }

    // Режим работы
    private int operatingMode = MODE_VIEW;

    // Контейнер видео для плавного сплит-масштабирования без пересоздания декодера
    private FrameLayout videoContainer;
    private SurfaceView surfaceView;
    private SurfaceHolder surfaceHolder;

    // Верхняя панель управления (для MODE_VIEW)
    private LinearLayout topToolbar;
    private TextView titleView;
    private TextView subtitleView;
    private TextView scaleModeBtn;
    private PcUi.IconBtn fullscreenBtn;
    private PcUi.IconBtn settingsBtn;
    private PcUi.IconBtn closeBtn;

    // Плавающие элементы управления (для MODE_PC_CONTROL)
    private FrameLayout floatingControlsGroup;
    private PcUi.IconBtn floatingGearBtn;
    private PcUi.IconBtn floatingArrowBtn;
    private boolean isQuickDrawerOpen = false;


    // Отдельные кнопки «Мышь» и «Клавиатура» (режим «Управление ПК» и панель демонстрации)
    private PcUi.IconBtn floatingMouseBtn;
    private PcUi.IconBtn floatingKbdBtn;
    private PcUi.IconBtn toolbarMouseBtn;
    private PcUi.IconBtn toolbarKbdBtn;

    private boolean isTouchpadEnabled = true;      // мышь в режиме «Управление ПК»
    private boolean isViewMouseEnabled = false;    // мышь в режиме «Демонстрация экрана»
    private boolean isKeyboardVisible = false;
    private volatile boolean isMicStreaming = false;

    // Сплит-панель настроек с анимацией уменьшения экрана
    private FrameLayout splitSettingsContainer;
    private LinearLayout splitSettingsCard;
    private ScrollView splitSettingsScroll;
    private boolean isSplitSettingsOpen = false;
    private int activeSettingsSection = 0; // 0=Главное, 1=Экран, 2=Качество, 3=FPS, 4=Тачпад, 5=Клавиатура, 6=Прозрачность

    // Настраиваемая геометрия тачпада (в нормализованных долях 0.0 .. 1.0)
    private float tpNormX = 0.55f;
    private float tpNormY = 0.10f;
    private float tpNormW = 0.42f;
    private float tpNormH = 0.80f;
    private float mouseSensitivity = 1.0f;
    private boolean mouseAccel = true;
    private boolean isMouseAbsolute = false;
    private float scrollSpeed = 1.0f;
    private boolean invertScroll = false;
    private int opacityTpZone = 0;   // зона тачпада по умолчанию полностью прозрачна (но работает)

    // Цвет (оттенок) отдельных элементов интерфейса — настраивается в «Прозрачность и цвета»
    private static final int DEF_COL_TP_ZONE = PcUi.PC_ACCENT;
    private static final int DEF_COL_TP_BORDER = PcUi.PC_ACCENT;
    private int colTpZone = DEF_COL_TP_ZONE;
    private int colGear = PcUi.TEXT;
    private int colArrow = PcUi.TEXT;
    private int colMenu = PcUi.TEXT;
    private int colKbdText = PcUi.TEXT;
    private int colTpBorder = DEF_COL_TP_BORDER;

    // Оверлей визуального редактирования тачпада прямо на экране
    private TouchpadVisualEditorView touchpadVisualEditor;
    private TouchpadZoneView touchpadZoneView;
    private boolean isTouchpadEditing = false;

    // Ввод: постоянный поток событий на ПК, распознавание жестов, собственная клавиатура
    private final PcInputClient inputClient = new PcInputClient();
    private PcTouchpadEngine touchpadEngine;
    private boolean touchGestureOwned = false;
    private final int[] tpIds = new int[10];
    private final float[] tpXs = new float[10];
    private final float[] tpYs = new float[10];

    // Собственная встроенная клавиатура PC Control
    private PcKeyboardLogic keyboardLogic;
    private PcKeyboardView keyboardView;
    private LinearLayout keyboardPanel;
    private GradientDrawable keyboardPanelBg;
    private int kbdWidthPct = 100;
    private int kbdHeightDp = 220;
    private int kbdLayoutIdx = 0; // 0=EN, 1=RU, 2=UK
    private float kbdPosX = 0.5f; // центр клавиатуры по горизонтали (доля ширины)
    private int kbdOffsetYDp = 8; // отступ от нижнего края
    private boolean kbdHaptics = true;
    private boolean kbdGameKeys = false;

    // Настройки прозрачности элементов (0..100%)
    private int opacityGear = 85;
    private int opacityArrow = 85;
    private int opacityQuickDrawer = 90;
    private int opacityBtnKeyboard = 100;
    private int opacityBtnMic = 100;
    private int opacityBtnSound = 100;
    private int opacityBtnTouchpad = 100;
    private int opacitySettings = 95;
    private int opacityDiag = 90;
    private int opacityKbdBg = 92;
    private int opacityKbdKeys = 95;
    private int opacityKbdSpecial = 95;
    private int opacityTpBorder = 80;
    private int opacityTpCenter = 80;

    // Позиция плавающей шестерёнки
    private float gearPosX = -1f;
    private float gearPosY = -1f;

    // Звук ПК (WASAPI Loopback)
    private boolean isAudioEnabled = true;
    private int audioVolume = 80;
    private boolean isAudioMuted = false;
    private volatile String audioStatus = "Выключен";
    private volatile int audioStatusColor = PcUi.SUBTEXT;
    private AudioPlayerThread audioThread = null;
    private final Object audioLock = new Object();

    // Микрофон телефона -> ПК
    private MicSenderThread micSenderThread = null;
    private final Object micLock = new Object();

    // Диагностика
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
    private boolean isDiagVisible = false;

    // Ошибки
    private FrameLayout errorOverlay;
    private TextView errorTitleView;
    private TextView errorMsgView;
    private TextView errorRetryBtn;
    private TextView errorCloseBtn;
    private boolean isErrorVisible = false;

    // Декодер и сетевой поток
    private volatile MediaCodec decoder;
    private Thread decoderOutputThread;
    private final Object decoderLock = new Object();
    // Wi-Fi без энергосбережения на время трансляции (как в Moonlight): без него пакеты
    // ввода/видео уходят пачками, курсор и картинка двигаются рывками.
    private android.net.wifi.WifiManager.WifiLock streamWifiLock;
    private Thread workerThread;
    private volatile HttpURLConnection activeConn;
    private final AtomicBoolean isStreaming = new AtomicBoolean(false);
    private final Object surfaceLock = new Object();
    private volatile boolean surfaceReady = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    // Параметры стрима
    private String serverUrl = "";
    private String authToken = "";
    private int targetMonitor = 1;
    private int targetHeight = 1080;
    private int targetFps = 60;
    private int targetBitrate = 0;

    private int videoWidth = 1920;
    private int videoHeight = 1080;
    private int scaleMode = SCALE_MODE_FIT;
    private final Rect videoViewportRect = new Rect();

    private boolean isFullscreen = false;
    private boolean isControlsVisible = true;
    private PlayerCallback playerCallback;

    // Трекеры FPS
    private final FpsTracker receivedFpsTracker = new FpsTracker(180, 1500);
    private final FpsTracker decodedFpsTracker = new FpsTracker(180, 1500);
    private final FpsTracker renderedFpsTracker = new FpsTracker(180, 1500);
    private final MinFpsTracker minFpsTracker = new MinFpsTracker(3000);

    // Телеметрия
    private long totalBytesReceived = 0;
    private long lastBitrateSampleTime = 0;
    private long lastBitrateBytes = 0;
    private float currentKbps = 0.0f;
    private long droppedFramesCount = 0;
    private long estimatedLatencyMs = 8;
    private String activeCodecName = "Hardware H.264";

    private final Runnable hideControlsRunnable = new Runnable() {
        @Override
        public void run() {
            setControlsVisible(false, true);
        }
    };

    private final Runnable diagUpdateRunnable = new Runnable() {
        @Override
        public void run() {
            if (isDiagVisible && isStreaming.get()) {
                refreshDiagValues();
                mainHandler.postDelayed(this, 300);
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
        loadPreferences();
        initInputEngine();

        // 1. Контейнер для масштабирования видео при сплит-экране настроек
        videoContainer = new FrameLayout(context);
        surfaceView = new SurfaceView(context);
        surfaceHolder = surfaceView.getHolder();
        surfaceHolder.addCallback(this);
        videoContainer.addView(surfaceView, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        // Контур прозрачного тачпада (видимость настраивается)
        touchpadZoneView = new TouchpadZoneView(context);
        touchpadZoneView.setVisibility(View.GONE);
        videoContainer.addView(touchpadZoneView, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        // Оверлей визуального редактирования зоны тачпада
        touchpadVisualEditor = new TouchpadVisualEditorView(context);
        touchpadVisualEditor.setVisibility(View.GONE);
        videoContainer.addView(touchpadVisualEditor, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        addView(videoContainer, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        // 2. Верхняя панель управления (для MODE_VIEW)
        buildTopToolbar(context);

        // 3. Плавающие кнопки и быстрое меню (для MODE_PC_CONTROL)
        buildFloatingControls(context);

        // 4. Собственная экранная клавиатура PC Control
        buildCustomKeyboard(context);

        // 5. Анимированная сплит-панель настроек
        buildSplitSettings(context);

        // 6. Диагностика и оверлей ошибок
        buildDiagnosticsDialog(context);
        buildErrorDialog(context);

        // Сенсорное управление: слушатель на всём контейнере видео (а не на SurfaceView,
        // который в режиме Fit меньше экрана — касания в чёрных полях раньше терялись,
        // а координаты зоны тачпада не совпадали с координатами касания).
        videoContainer.setOnTouchListener(new OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                return handleTouchEvent(event);
            }
        });
        updateQuickActionStates();
    }

    // -----------------------------------------------------------------------
    // ВВОД: ПОТОК СОБЫТИЙ НА ПК, ЖЕСТЫ ТАЧПАДА
    // -----------------------------------------------------------------------
    private void initInputEngine() {
        touchpadEngine = new PcTouchpadEngine(new PcTouchpadEngine.Sink() {
            @Override public void move(int dx, int dy) { inputClient.mouseMove(dx, dy); }
            @Override public void moveAbs(float x, float y) { inputClient.mouseAbs(x, y, targetMonitor); }
            @Override public void button(int button, boolean down) { inputClient.mouseButton(button, down); }
            @Override public void scroll(int vertical, int horizontal) { inputClient.scroll(vertical, horizontal); }
            @Override public void feedback(int kind) {
                if (videoContainer != null) {
                    videoContainer.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS);
                }
            }
        }, new PcTouchpadEngine.Scheduler() {
            @Override public void postDelayed(Runnable r, long delayMs) { mainHandler.postDelayed(r, delayMs); }
            @Override public void cancel(Runnable r) { mainHandler.removeCallbacks(r); }
        });
        applyTouchpadConfig();

        inputClient.setListener(new PcInputClient.Listener() {
            @Override
            public void onInputStateChanged(int state, String detail) {
                mainHandler.post(new Runnable() {
                    @Override public void run() { updateQuickActionStates(); }
                });
            }

            @Override
            public void onInputSessionStarted() {
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        // После переподключения сервер начинает с чистого состояния:
                        // повторно отправляем удерживаемые сейчас клавиши и кнопку мыши.
                        if (keyboardLogic != null) keyboardLogic.resync();
                        if (touchpadEngine != null) touchpadEngine.resync();
                    }
                });
            }
        });
    }

    private void applyTouchpadConfig() {
        if (touchpadEngine == null) return;
        float density = getResources().getDisplayMetrics().density;
        touchpadEngine.configure(density, mouseSensitivity, mouseAccel, scrollSpeed, invertScroll, isMouseAbsolute);
    }

    /** «Демонстрация экрана» — только просмотр: мышь и клавиатура работают лишь в «Управлении ПК». */
    private boolean isMouseActive() {
        return operatingMode == MODE_PC_CONTROL && isTouchpadEnabled;
    }

    private void toggleMouseControl() {
        if (operatingMode != MODE_PC_CONTROL) return;
        isTouchpadEnabled = !isTouchpadEnabled;
        if (!isMouseActive() && touchpadEngine != null) {
            touchpadEngine.cancel();
            touchGestureOwned = false;
        }
        if (isMouseActive()) ensureInputClient();
        updateQuickActionStates();
        updateTouchpadZoneVisibility();
        Toast.makeText(getContext(), isMouseActive() ? "Управление мышью включено" : "Управление мышью выключено", Toast.LENGTH_SHORT).show();
    }

    /** Открывает поток ввода на ПК (только «Управление ПК» и только во время трансляции). */
    private void ensureInputClient() {
        if (operatingMode == MODE_PC_CONTROL && isStreaming.get() && !inputClient.isRunning()) {
            inputClient.start();
        }
    }

    private void updateTouchpadZoneVisibility() {
        if (touchpadZoneView == null) return;
        boolean show = isMouseActive() && !isMouseAbsolute && !isTouchpadEditing && opacityTpZone > 0
                && !isSplitSettingsOpen;
        touchpadZoneView.setVisibility(show ? View.VISIBLE : View.GONE);
        touchpadZoneView.invalidate();
    }

    /** Полупрозрачный контур зоны тачпада поверх видео. */
    private class TouchpadZoneView extends View {
        private final android.graphics.Paint fill = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
        private final android.graphics.Paint stroke = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
        private final RectF r = new RectF();

        TouchpadZoneView(Context c) {
            super(c);
            stroke.setStyle(android.graphics.Paint.Style.STROKE);
            stroke.setStrokeWidth(dpToPx(1));
            setWillNotDraw(false);
        }

        @Override
        protected void onDraw(android.graphics.Canvas canvas) {
            int w = getWidth();
            int h = getHeight();
            if (w <= 0 || h <= 0) return;
            float a = opacityTpZone / 100f;
            r.set(tpNormX * w, tpNormY * h, (tpNormX + tpNormW) * w, (tpNormY + tpNormH) * h);
            fill.setColor(colTpZone);
            fill.setAlpha((int) (a * 0.35f * 255));
            canvas.drawRoundRect(r, dpToPx(16), dpToPx(16), fill);
            stroke.setColor(colTpZone);
            stroke.setAlpha((int) (a * 255));
            canvas.drawRoundRect(r, dpToPx(16), dpToPx(16), stroke);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasWindowFocus) {
        super.onWindowFocusChanged(hasWindowFocus);
        if (!hasWindowFocus) {
            // Шторка уведомлений, системный диалог, переход в другое приложение: не оставляем на ПК
            // зажатых кнопок мыши, клавиш и зафиксированных модификаторов (Ctrl/Alt/Win/Shift).
            releaseLocalInputState(true);
        }
    }

    /** Отпускает всё, что удерживается пальцами (кнопка мыши, клавиши). */
    private void releaseLocalInputState(boolean includeLatchedModifiers) {
        if (touchpadEngine != null) touchpadEngine.cancel();
        touchGestureOwned = false;
        if (keyboardView != null) keyboardView.releaseAllPointers();
        if (includeLatchedModifiers && keyboardLogic != null) keyboardLogic.releaseAll();
    }

    public void setOperatingMode(int mode) {
        this.operatingMode = mode;
        post(new Runnable() {
            @Override
            public void run() {
                applyOperatingModeUI();
            }
        });
    }

    private void applyOperatingModeUI() {
        if (operatingMode == MODE_PC_CONTROL) {
            if (topToolbar != null) topToolbar.setVisibility(View.GONE);
            if (floatingControlsGroup != null) {
                floatingControlsGroup.setVisibility(View.VISIBLE);
                applyOpacities();
            }
            if (titleView != null) titleView.setText("Управление ПК");
            if (isStreaming.get()) ensureInputClient();
        } else {
            // Демонстрация экрана — только просмотр: никакого ввода на ПК
            if (floatingControlsGroup != null) floatingControlsGroup.setVisibility(View.GONE);
            if (floatingMenuStrip != null) floatingMenuStrip.setVisibility(View.GONE);
            if (floatingArrowBtn != null) floatingArrowBtn.setRotation(0f);
            isQuickDrawerOpen = false;
            if (isKeyboardVisible) showCustomKeyboard(false);
            releaseLocalInputState(true);
            if (inputClient.isRunning()) inputClient.stop();
            // Микрофон — функция «Управления ПК»: в демонстрации нет кнопки, чтобы его выключить
            if (isMicStreaming) stopMicStreaming();
            isViewMouseEnabled = false;
            if (topToolbar != null) topToolbar.setVisibility(View.VISIBLE);
            if (titleView != null) titleView.setText("Демонстрация экрана");
        }
        updateQuickActionStates();
        updateTouchpadZoneVisibility();
        requestLayout();
    }

    // -----------------------------------------------------------------------
    // ПЛАВАЮЩИЕ КНОПКИ И ВЫДВИЖНОЕ МЕНЮ БЫСТРЫХ ФУНКЦИЙ (MODE_PC_CONTROL)
    // -----------------------------------------------------------------------
    /**
     * Плавающее управление «Управления ПК» (правый верхний угол):
     *   [Настройки][Звук ПК][Микрофон][Полный экран][Клавиатура][Мышь] [◀] [⚙]
     * Меню по умолчанию закрыто; шестерёнка или стрелка плавно выдвигают его влево.
     */
    private LinearLayout floatingMenuStrip;
    private PcUi.IconBtn floatingSettingsBtn;
    private PcUi.IconBtn floatingFsBtn;
    private PcUi.IconBtn floatingMicBtn;
    private PcUi.IconBtn floatingSoundBtn;

    private void buildFloatingControls(Context context) {
        floatingControlsGroup = new FrameLayout(context);
        floatingControlsGroup.setVisibility(View.GONE);
        floatingControlsGroup.setClipChildren(false);
        floatingControlsGroup.setClipToPadding(false);

        // Шестерёнка: открывает полноценные настройки демонстрации и управления ПК
        // (выдвижное меню быстрых функций — только по стрелке). Можно перетащить в другое место.
        floatingGearBtn = new PcUi.IconBtn(context, PcIcons.GEAR, 46, 22, true, "Настройки");
        floatingGearBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleSplitSettings();
            }
        });
        floatingGearBtn.setOnTouchListener(new OnTouchListener() {
            private float startRawX, startRawY;
            private int initialRight, initialTop;
            private boolean isMoving = false;

            @Override
            public boolean onTouch(View v, MotionEvent ev) {
                PcUi.pressFeedback(v, ev);
                switch (ev.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        startRawX = ev.getRawX();
                        startRawY = ev.getRawY();
                        initialRight = floatingControlsGroup.getRight();
                        initialTop = floatingControlsGroup.getTop();
                        isMoving = false;
                        return false;
                    case MotionEvent.ACTION_MOVE: {
                        float dx = ev.getRawX() - startRawX;
                        float dy = ev.getRawY() - startRawY;
                        if (isMoving || Math.abs(dx) > dpToPx(8) || Math.abs(dy) > dpToPx(8)) {
                            if (!isMoving) {
                                isMoving = true;
                                v.setPressed(false);
                                v.cancelLongPress();
                            }
                            int gW = floatingControlsGroup.getWidth();
                            int gH = floatingControlsGroup.getHeight();
                            // Позиция = ПРАВЫЙ край группы (меню растёт влево, шестерёнка стоит на месте)
                            gearPosX = Math.max(gW + dpToPx(8), Math.min(getWidth() - dpToPx(8), initialRight + dx));
                            gearPosY = Math.max(dpToPx(8), Math.min(getHeight() - gH - dpToPx(8), initialTop + dy));
                            requestLayout();
                        }
                        return isMoving;
                    }
                    case MotionEvent.ACTION_UP:
                    case MotionEvent.ACTION_CANCEL:
                        if (isMoving) {
                            isMoving = false;
                            savePreferences();
                            return true;
                        }
                        return false;
                }
                return false;
            }
        });

        // Стрелка слева от шестерёнки, направлена влево (куда выдвигается меню)
        floatingArrowBtn = new PcUi.IconBtn(context, PcIcons.CHEVRON_LEFT, 40, 20, true, "Развернуть меню");
        floatingArrowBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleQuickDrawer();
            }
        });

        // Выдвижное меню (по умолчанию скрыто)
        floatingMenuStrip = new LinearLayout(context);
        floatingMenuStrip.setOrientation(LinearLayout.HORIZONTAL);
        floatingMenuStrip.setGravity(Gravity.CENTER_VERTICAL);
        floatingMenuStrip.setClipChildren(false);
        floatingMenuStrip.setVisibility(View.GONE);

        // Настройки открываются шестерёнкой, поэтому отдельной кнопки настроек в меню нет
        floatingSettingsBtn = null;
        floatingSoundBtn = menuButton(context, PcIcons.HEADPHONES, "Звук ПК", new Runnable() {
            @Override public void run() { setAudioEnabled(!isAudioEnabled); updateQuickActionStates(); }
        });
        floatingMicBtn = menuButton(context, PcIcons.MIC, "Микрофон", new Runnable() {
            @Override public void run() { toggleMicStreaming(); }
        });
        floatingFsBtn = menuButton(context, isFullscreen ? PcIcons.FULLSCREEN_EXIT : PcIcons.FULLSCREEN, "Полноэкранный режим", new Runnable() {
            @Override public void run() { toggleFullscreen(); }
        });
        floatingKbdBtn = menuButton(context, PcIcons.KEYBOARD, "Клавиатура", new Runnable() {
            @Override public void run() { toggleCustomKeyboard(); }
        });
        floatingMouseBtn = menuButton(context, PcIcons.MOUSE, "Мышь (тачпад)", new Runnable() {
            @Override public void run() { toggleMouseControl(); }
        });
        View[] items = {floatingSoundBtn, floatingMicBtn, floatingFsBtn, floatingKbdBtn, floatingMouseBtn};
        for (View b : items) {
            floatingMenuStrip.addView(b);
            addToolbarSpacer(context, floatingMenuStrip, 8);
        }

        LinearLayout headRow = new LinearLayout(context);
        headRow.setOrientation(LinearLayout.HORIZONTAL);
        headRow.setGravity(Gravity.CENTER_VERTICAL);
        headRow.setClipChildren(false);
        headRow.addView(floatingMenuStrip);
        headRow.addView(floatingArrowBtn);
        addToolbarSpacer(context, headRow, 8);
        headRow.addView(floatingGearBtn);

        floatingControlsGroup.addView(headRow);
        addView(floatingControlsGroup, new FrameLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT));

        applyUserTints();
        updateQuickActionStates();
    }

    private PcUi.IconBtn menuButton(Context context, String[] icon, String description, final Runnable action) {
        PcUi.IconBtn b = new PcUi.IconBtn(context, icon, 44, 20, true, description);
        b.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                action.run();
            }
        });
        return b;
    }

    private static int toggleState(boolean active, boolean error, int idle) {
        if (error) return PcUi.ST_ERROR;
        return active ? PcUi.ST_ACTIVE : idle;
    }

    private void updateQuickActionStates() {
        int st = inputClient.getState();
        boolean inputError = inputClient.isRunning()
                && (st == PcInputClient.STATE_ERROR || st == PcInputClient.STATE_AUTH_ERROR);
        boolean mouseOn = isMouseActive();
        if (floatingMouseBtn != null) floatingMouseBtn.setState(toggleState(mouseOn, mouseOn && inputError, PcUi.ST_FLOATING));
        if (floatingKbdBtn != null) floatingKbdBtn.setState(toggleState(isKeyboardVisible, isKeyboardVisible && inputError, PcUi.ST_FLOATING));
        if (floatingMicBtn != null) floatingMicBtn.setState(toggleState(isMicStreaming, false, PcUi.ST_FLOATING));
        if (floatingSoundBtn != null) floatingSoundBtn.setState(toggleState(isAudioEnabled, false, PcUi.ST_FLOATING));
        if (floatingFsBtn != null) floatingFsBtn.setState(toggleState(isFullscreen, false, PcUi.ST_FLOATING));
        if (floatingSettingsBtn != null) floatingSettingsBtn.setState(toggleState(isSplitSettingsOpen, false, PcUi.ST_FLOATING));
        if (floatingArrowBtn != null) floatingArrowBtn.setState(isQuickDrawerOpen ? PcUi.ST_ACTIVE : PcUi.ST_FLOATING);
        // Шестерёнка отражает только состояние настроек, стрелка — только состояние меню
        if (floatingGearBtn != null) floatingGearBtn.setState(isSplitSettingsOpen ? PcUi.ST_ACTIVE : PcUi.ST_FLOATING);
        maybeWarnLegacyServer(st);
    }

    private boolean legacyWarningShown = false;

    /** Старый сервер (нет /api/input/stream): мышь работает, но медленно — подсказываем перезапуск. */
    private void maybeWarnLegacyServer(int state) {
        if (state == PcInputClient.STATE_LEGACY && !legacyWarningShown) {
            legacyWarningShown = true;
            Toast.makeText(getContext(), "Сервер PC Control на ПК устарел: мышь работает в медленном режиме. "
                    + "Перезапустите сервер на ПК.", Toast.LENGTH_LONG).show();
        }
    }

    /** Плавно выдвигает меню влево (кнопки выезжают из-под стрелки по очереди) или задвигает обратно. */
    private void toggleQuickDrawer() {
        if (floatingMenuStrip == null) return;
        isQuickDrawerOpen = !isQuickDrawerOpen;
        floatingArrowBtn.animate().rotation(isQuickDrawerOpen ? 180f : 0f).setDuration(240)
                .setInterpolator(new DecelerateInterpolator()).start();
        floatingArrowBtn.setContentDescription(isQuickDrawerOpen ? "Свернуть меню" : "Развернуть меню");
        final int n = floatingMenuStrip.getChildCount();
        final float step = dpToPx(52);
        floatingMenuStrip.animate().cancel();
        if (isQuickDrawerOpen) {
            floatingMenuStrip.setVisibility(View.VISIBLE);
            floatingMenuStrip.setAlpha(0f);
            floatingMenuStrip.animate().alpha(opacityQuickDrawer / 100f).setDuration(200).setListener(null).start();
            int k = 0;
            for (int i = n - 1; i >= 0; i--) {
                View c = floatingMenuStrip.getChildAt(i);
                if (!(c instanceof PcUi.IconBtn)) continue;
                c.animate().cancel();
                // выезжает из-под стрелки: чем дальше кнопка, тем больше путь
                c.setTranslationX(step * (k + 1));
                c.setScaleX(0.6f);
                c.setScaleY(0.6f);
                c.animate().translationX(0f).scaleX(1f).scaleY(1f)
                        .setStartDelay(k * 25L).setDuration(260)
                        .setInterpolator(new DecelerateInterpolator(1.6f)).start();
                k++;
            }
        } else {
            int k = 0;
            for (int i = n - 1; i >= 0; i--) {
                View c = floatingMenuStrip.getChildAt(i);
                if (!(c instanceof PcUi.IconBtn)) continue;
                c.animate().cancel();
                c.animate().translationX(step * (k + 1)).scaleX(0.6f).scaleY(0.6f)
                        .setStartDelay(0).setDuration(200)
                        .setInterpolator(new AccelerateInterpolator()).start();
                k++;
            }
            floatingMenuStrip.animate().alpha(0f).setDuration(200)
                    .setListener(new AnimatorListenerAdapter() {
                        @Override
                        public void onAnimationEnd(Animator animation) {
                            if (!isQuickDrawerOpen) {
                                floatingMenuStrip.setVisibility(View.GONE);
                                for (int i = 0; i < floatingMenuStrip.getChildCount(); i++) {
                                    View c = floatingMenuStrip.getChildAt(i);
                                    c.setTranslationX(0f);
                                    c.setScaleX(1f);
                                    c.setScaleY(1f);
                                }
                            }
                        }
                    }).start();
        }
        updateQuickActionStates();
    }

    // -----------------------------------------------------------------------
    // АНИМИРОВАННЫЙ SPLIT-SCREEN РЕДАКТОР НАСТРОЕК (стиль окна настроек приложения)
    // -----------------------------------------------------------------------
    private GradientDrawable settingsCardBg;
    private LinearLayout settingsBody;

    private void buildSplitSettings(Context context) {
        splitSettingsContainer = new FrameLayout(context);
        splitSettingsContainer.setVisibility(View.GONE);
        // .settings-modal-backdrop: rgba(0,0,0,0.76)
        splitSettingsContainer.setBackgroundColor(0xC2000000);

        splitSettingsScroll = new ScrollView(context);
        splitSettingsScroll.setVerticalScrollBarEnabled(false);
        splitSettingsScroll.setClipToPadding(false);
        int m = dpToPx(12);
        splitSettingsScroll.setPadding(m, m, m, m);

        splitSettingsCard = new LinearLayout(context);
        splitSettingsCard.setOrientation(LinearLayout.VERTICAL);
        // .settings-modal: #121212, border rgba(255,255,255,.13), radius 22, padding 18
        settingsCardBg = PcUi.shape(PcUi.SURFACE, dpToPx(22), PcUi.BORDER_STRONG, dpToPx(1));
        splitSettingsCard.setBackground(settingsCardBg);
        int pad = dpToPx(18);
        splitSettingsCard.setPadding(pad, pad, pad, pad);

        splitSettingsScroll.addView(splitSettingsCard, new ScrollView.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        splitSettingsContainer.addView(splitSettingsScroll, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        addView(splitSettingsContainer, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
        applyOpacities();
    }

    private void toggleSplitSettings() {
        if (isSplitSettingsOpen) {
            closeSplitSettingsWithAnimation();
        } else {
            openSplitSettingsWithAnimation(0);
        }
    }

    /**
     * Плавная анимация: уменьшение живого видео (scale=0.5) со сдвигом вправо, выезд панели слева.
     */
    private void openSplitSettingsWithAnimation(int section) {
        isSplitSettingsOpen = true;
        activeSettingsSection = section;
        updateQuickActionStates();
        // Меню быстрых функций не трогаем: оно скрывается вместе с плавающими кнопками
        // и после закрытия настроек возвращается в том же состоянии.
        renderSplitSettingsContent();

        // Скрываем плавающие кнопки и клавиатуру на время настроек (клавиши при этом отпускаются)
        if (floatingControlsGroup != null) floatingControlsGroup.setVisibility(View.GONE);
        if (keyboardPanel != null && keyboardPanel.getVisibility() == View.VISIBLE) {
            if (keyboardView != null) keyboardView.releaseAllPointers();
            keyboardPanel.animate().cancel();
            keyboardPanel.setVisibility(View.GONE);
        }
        releaseLocalInputState(false);
        if (touchpadZoneView != null) touchpadZoneView.setVisibility(View.GONE);

        splitSettingsContainer.animate().cancel();
        splitSettingsContainer.setVisibility(View.VISIBLE);
        splitSettingsContainer.setAlpha(0f);
        splitSettingsCard.setTranslationX(-dpToPx(28));

        int parentW = getWidth();

        videoContainer.animate()
                .scaleX(0.50f)
                .scaleY(0.50f)
                .translationX(parentW * 0.24f)
                .setDuration(280)
                .setInterpolator(new AccelerateDecelerateInterpolator())
                .start();

        splitSettingsCard.animate().translationX(0f).setDuration(280)
                .setInterpolator(new DecelerateInterpolator()).start();
        splitSettingsContainer.animate()
                .alpha(1f)
                .setDuration(240)
                .setListener(new AnimatorListenerAdapter() {
                    @Override
                    public void onAnimationEnd(Animator animation) {
                        requestLayout();
                    }
                })
                .start();
    }

    private void closeSplitSettingsWithAnimation() {
        isSplitSettingsOpen = false;
        leaveTouchpadEditor();
        // Раньше прозрачность, цвета, чувствительность и т. п. сохранялись только кнопками
        // «Применить»/«Сохранить» (а в разделе «Прозрачность и цвета» такой кнопки нет) —
        // после перезапуска изменения терялись. Сохраняем при любом закрытии настроек.
        savePreferences();
        updateQuickActionStates();

        videoContainer.animate()
                .scaleX(1.0f)
                .scaleY(1.0f)
                .translationX(0f)
                .translationY(0f)
                .setDuration(260)
                .setInterpolator(new DecelerateInterpolator())
                .start();

        splitSettingsCard.animate().translationX(-dpToPx(28)).setDuration(220)
                .setInterpolator(new AccelerateInterpolator()).start();
        splitSettingsContainer.animate()
                .alpha(0f)
                .setDuration(220)
                .setListener(new AnimatorListenerAdapter() {
                    @Override
                    public void onAnimationEnd(Animator animation) {
                        if (isSplitSettingsOpen) return;
                        splitSettingsContainer.setVisibility(View.GONE);
                        splitSettingsCard.setTranslationX(0f);
                        if (operatingMode == MODE_PC_CONTROL && floatingControlsGroup != null) {
                            floatingControlsGroup.setVisibility(View.VISIBLE);
                        }
                        if (isKeyboardVisible && keyboardPanel != null) {
                            keyboardPanel.setVisibility(View.VISIBLE);
                            keyboardPanel.setAlpha(1f);
                            keyboardPanel.setTranslationY(0f);
                        }
                        applyTouchpadConfig();
                        updateTouchpadZoneVisibility();
                        updateQuickActionStates();
                        requestLayout();
                    }
                })
                .start();
    }

    private void leaveTouchpadEditor() {
        touchpadBoundsListener = null;
        if (touchpadVisualEditor != null) touchpadVisualEditor.setVisibility(View.GONE);
        isTouchpadEditing = false;
    }

    private void openSettingsSection(int section) {
        if (section != 4) leaveTouchpadEditor();
        activeSettingsSection = section;
        renderSplitSettingsContent();
    }

    private void renderSplitSettingsContent() {
        splitSettingsCard.removeAllViews();
        Context ctx = getContext();
        int s = activeSettingsSection;

        // Шапка как у окна «Настройки» приложения: значок/назад, заголовок, круглая ✕
        LinearLayout head = new LinearLayout(ctx);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        if (s == 0) {
            android.widget.ImageView tile = new android.widget.ImageView(ctx);
            tile.setImageDrawable(new PcIconDrawable(PcIcons.GEAR, PcUi.RED, dpToPx(16)));
            tile.setScaleType(android.widget.ImageView.ScaleType.CENTER);
            tile.setBackground(PcUi.shape(PcUi.RED_SOFT, dpToPx(8), 0, 0));
            head.addView(tile, new LinearLayout.LayoutParams(dpToPx(28), dpToPx(28)));
        } else {
            PcUi.IconBtn back = new PcUi.IconBtn(ctx, PcIcons.CHEVRON_LEFT, 30, 18, true, "Назад к разделам");
            back.setBackground(PcUi.oval(0x14FFFFFF, 0, 0));
            back.setOnClickListener(new OnClickListener() {
                @Override
                public void onClick(View v) {
                    openSettingsSection(0);
                }
            });
            head.addView(back);
        }
        TextView title = PcUi.text(ctx, getSectionTitle(s), 16f, PcUi.TEXT, Typeface.DEFAULT_BOLD);
        title.setSingleLine(true);
        title.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f);
        tlp.leftMargin = dpToPx(10);
        tlp.rightMargin = dpToPx(8);
        head.addView(title, tlp);

        PcUi.IconBtn closeX = new PcUi.IconBtn(ctx, PcIcons.CLOSE, 30, 16, true, "Закрыть настройки");
        closeX.setBackground(PcUi.oval(0x14FFFFFF, 0, 0));
        closeX.icon.setColor(0x99FFFFFF);
        closeX.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeSplitSettingsWithAnimation();
            }
        });
        head.addView(closeX);
        splitSettingsCard.addView(head);

        TextView sub = PcUi.text(ctx, getSectionSubtitle(s), 12f, PcUi.SUBTEXT, null);
        sub.setPadding(0, dpToPx(12), 0, dpToPx(4));
        sub.setLineSpacing(0, 1.15f);
        splitSettingsCard.addView(sub);

        settingsBody = new LinearLayout(ctx);
        settingsBody.setOrientation(LinearLayout.VERTICAL);
        splitSettingsCard.addView(settingsBody, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        if (s == 0) buildMainSettingsMenu(ctx);
        else if (s == 1) buildScreenSettingsSection(ctx);
        else if (s == 2) buildQualitySettingsSection(ctx);
        else if (s == 3) buildFpsSettingsSection(ctx);
        else if (s == 4) buildTouchpadSettingsSection(ctx);
        else if (s == 5) buildKeyboardSettingsSection(ctx);
        else if (s == 6) buildOpacitySettingsSection(ctx);

        // .settings-pane{animation:fadeIn .2s} — fade + 4dp lift
        settingsBody.setAlpha(0f);
        settingsBody.setTranslationY(dpToPx(4));
        settingsBody.animate().alpha(1f).translationY(0f).setDuration(200)
                .setInterpolator(new DecelerateInterpolator()).start();
        if (splitSettingsScroll != null) splitSettingsScroll.scrollTo(0, 0);
    }

    private String getSectionTitle(int s) {
        switch (s) {
            case 1: return "Экран";
            case 2: return "Качество изображения";
            case 3: return "Частота кадров";
            case 4: return "Тачпад и мышь";
            case 5: return "Клавиатура ПК";
            case 6: return "Прозрачность и цвета";
            default: return "Настройки";
        }
    }

    private String getSectionSubtitle(int s) {
        switch (s) {
            case 1: return "Какой монитор ПК транслировать.";
            case 2: return "Разрешение и битрейт видеопотока.";
            case 3: return "Частота кадров трансляции.";
            case 4: return "Перетаскивайте зону и её маркеры прямо на видео справа.";
            case 5: return "Собственная клавиатура PC Control — системная клавиатура Android не используется.";
            case 6: return "Прозрачность и цвет каждого элемента управления.";
            default: return operatingMode == MODE_PC_CONTROL ? "Управление ПК · трансляция, мышь и клавиатура" : "Демонстрация экрана · трансляция";
        }
    }

    private void buildMainSettingsMenu(final Context ctx) {
        addNav(ctx, PcIcons.MONITOR, "Экран", "Выбор монитора", 1);
        addNav(ctx, PcIcons.IMAGE, "Качество изображения", "Разрешение и битрейт", 2);
        addNav(ctx, PcIcons.CLOCK, "Частота кадров", "30 · 60 · 90 FPS", 3);
        if (operatingMode == MODE_PC_CONTROL) {
            // Ввод настраивается только в «Управлении ПК»; в демонстрации — лишь параметры видео
            addNav(ctx, PcIcons.MOUSE, "Тачпад и мышь", "Зона, чувствительность, прокрутка", 4);
            addNav(ctx, PcIcons.KEYBOARD, "Клавиатура ПК", "Размер, положение, язык", 5);
            addNav(ctx, PcIcons.EYE, "Прозрачность и цвета", "Зона тачпада, шестерёнка, меню, клавиатура", 6);
        }

        settingsBody.addView(PcUi.divider(ctx));
        PcUi.Btn diagBtn = new PcUi.Btn(ctx, PcIcons.CHART, "Диагностика потока", true);
        diagBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeSplitSettingsWithAnimation();
                setDiagnosticsVisible(true);
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        lp.topMargin = dpToPx(8);
        settingsBody.addView(diagBtn, lp);
    }

    private void addNav(Context ctx, String[] icon, String title, String subtitle, final int section) {
        settingsBody.addView(PcUi.navRow(ctx, icon, title, subtitle, new OnClickListener() {
            @Override
            public void onClick(View v) {
                openSettingsSection(section);
            }
        }));
    }

    private interface TouchpadBoundsListener {
        void onBoundsChanged(float x, float y, float w, float h);
    }
    private TouchpadBoundsListener touchpadBoundsListener;

    // ---- построители строк раздела -------------------------------------------------
    private interface SliderChange {
        /** Applies the value and returns the text shown on the right of the label. */
        String onChange(int value);
    }

    private static final class SliderRow {
        PcUi.ValueRow row;
        SeekBar bar;
        int min;

        void set(int value, String text) {
            bar.setProgress(Math.max(0, value - min));
            row.set(text);
        }
    }

    private void addTitle(String text) {
        settingsBody.addView(PcUi.sectionTitle(getContext(), text));
    }

    private void addHint(String text) {
        TextView t = PcUi.text(getContext(), text, 12f, PcUi.SUBTEXT, null);
        t.setLineSpacing(0, 1.15f);
        t.setPadding(dpToPx(2), 0, 0, dpToPx(4));
        settingsBody.addView(t);
    }

    private SliderRow addValueSlider(String label, int min, int max, int current, final SliderChange ch) {
        Context ctx = getContext();
        final SliderRow r = new SliderRow();
        r.min = min;
        r.row = new PcUi.ValueRow(ctx, label, "");
        settingsBody.addView(r.row);
        r.bar = PcUi.slider(ctx, min, max, current, new PcUi.SliderListener() {
            @Override
            public void onValue(int value) {
                r.row.set(ch.onChange(value));
            }
        });
        settingsBody.addView(r.bar);
        return r;
    }

    private PcUi.Seg addSeg(String label, String[] options, int selected, PcUi.SegListener l) {
        Context ctx = getContext();
        if (label != null) {
            TextView t = PcUi.text(ctx, label, 12.5f, PcUi.SUBTEXT, PcUi.medium());
            t.setPadding(dpToPx(2), dpToPx(10), 0, dpToPx(6));
            settingsBody.addView(t);
        }
        PcUi.Seg seg = new PcUi.Seg(ctx, options, selected, l);
        settingsBody.addView(seg, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        return seg;
    }

    private void addButtonRow(View... buttons) {
        Context ctx = getContext();
        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (int i = 0; i < buttons.length; i++) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f);
            if (i > 0) lp.leftMargin = dpToPx(8);
            row.addView(buttons[i], lp);
        }
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        rlp.topMargin = dpToPx(8);
        settingsBody.addView(row, rlp);
    }

    private PcUi.Btn smallBtn(String text, final Runnable r) {
        PcUi.Btn b = new PcUi.Btn(getContext(), null, text, false);
        b.setPadding(dpToPx(6), dpToPx(9), dpToPx(6), dpToPx(9));
        b.label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f);
        b.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                r.run();
            }
        });
        return b;
    }

    private PcUi.Btn actionBtn(String[] icon, String text, int state, final Runnable r) {
        PcUi.Btn b = new PcUi.Btn(getContext(), icon, text, false);
        b.setState(state);
        b.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                r.run();
            }
        });
        return b;
    }

    private static String pct(float v) {
        return Math.round(v * 100) + "%";
    }

    private static String fmt1(float v) {
        return String.format(java.util.Locale.US, "%.1f×", v);
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛ: ТАЧПАД (СИНХРОНИЗИРОВАННЫЙ РЕДАКТОР С ЖИВЫМ ПРЕВЬЮ)
    // -----------------------------------------------------------------------
    private void buildTouchpadSettingsSection(Context ctx) {
        isTouchpadEditing = true;
        final float initX = tpNormX;
        final float initY = tpNormY;
        final float initW = tpNormW;
        final float initH = tpNormH;

        if (touchpadVisualEditor != null) {
            touchpadVisualEditor.setVisibility(View.VISIBLE);
            touchpadVisualEditor.invalidate();
        }

        addTitle("Зона тачпада");
        final SliderRow wRow = addValueSlider("Ширина", 15, 95, Math.round(tpNormW * 100), new SliderChange() {
            @Override
            public String onChange(int val) {
                tpNormW = Math.min(val / 100f, 1f - tpNormX);
                invalidateTouchpadEditor();
                return pct(tpNormW);
            }
        });
        wRow.row.set(pct(tpNormW));
        final SliderRow hRow = addValueSlider("Высота", 15, 95, Math.round(tpNormH * 100), new SliderChange() {
            @Override
            public String onChange(int val) {
                tpNormH = Math.min(val / 100f, 1f - tpNormY);
                invalidateTouchpadEditor();
                return pct(tpNormH);
            }
        });
        hRow.row.set(pct(tpNormH));

        touchpadBoundsListener = new TouchpadBoundsListener() {
            @Override
            public void onBoundsChanged(float x, float y, float w, float h) {
                wRow.set(Math.round(w * 100), pct(w));
                hRow.set(Math.round(h * 100), pct(h));
            }
        };

        addTitle("Точная подстройка (±1%)");
        addButtonRow(
                smallBtn("X −", new Runnable() { @Override public void run() { tpNormX = Math.max(0f, tpNormX - 0.01f); invalidateTouchpadEditor(); } }),
                smallBtn("X +", new Runnable() { @Override public void run() { tpNormX = Math.min(1f - tpNormW, tpNormX + 0.01f); invalidateTouchpadEditor(); } }),
                smallBtn("Y −", new Runnable() { @Override public void run() { tpNormY = Math.max(0f, tpNormY - 0.01f); invalidateTouchpadEditor(); } }),
                smallBtn("Y +", new Runnable() { @Override public void run() { tpNormY = Math.min(1f - tpNormH, tpNormY + 0.01f); invalidateTouchpadEditor(); } }));
        addButtonRow(
                smallBtn("Шир −", new Runnable() { @Override public void run() {
                    tpNormW = Math.max(0.15f, tpNormW - 0.01f); wRow.set(Math.round(tpNormW * 100), pct(tpNormW)); invalidateTouchpadEditor(); } }),
                smallBtn("Шир +", new Runnable() { @Override public void run() {
                    tpNormW = Math.min(1f - tpNormX, tpNormW + 0.01f); wRow.set(Math.round(tpNormW * 100), pct(tpNormW)); invalidateTouchpadEditor(); } }),
                smallBtn("Выс −", new Runnable() { @Override public void run() {
                    tpNormH = Math.max(0.15f, tpNormH - 0.01f); hRow.set(Math.round(tpNormH * 100), pct(tpNormH)); invalidateTouchpadEditor(); } }),
                smallBtn("Выс +", new Runnable() { @Override public void run() {
                    tpNormH = Math.min(1f - tpNormY, tpNormH + 0.01f); hRow.set(Math.round(tpNormH * 100), pct(tpNormH)); invalidateTouchpadEditor(); } }));

        addTitle("Мышь");
        SliderRow sens = addValueSlider("Чувствительность", 2, 30, Math.round(mouseSensitivity * 10), new SliderChange() {
            @Override
            public String onChange(int val) {
                mouseSensitivity = val / 10f;
                applyTouchpadConfig();
                return fmt1(mouseSensitivity);
            }
        });
        sens.row.set(fmt1(mouseSensitivity));
        addSeg("Режим", new String[]{"Тачпад", "Прямое касание"}, isMouseAbsolute ? 1 : 0, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                isMouseAbsolute = i == 1;
                applyTouchpadConfig();
            }
        });
        addSeg("Ускорение указателя", new String[]{"Вкл", "Выкл"}, mouseAccel ? 0 : 1, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                mouseAccel = i == 0;
                applyTouchpadConfig();
            }
        });

        addTitle("Прокрутка двумя пальцами");
        SliderRow sc = addValueSlider("Скорость прокрутки", 3, 30, Math.round(scrollSpeed * 10), new SliderChange() {
            @Override
            public String onChange(int val) {
                scrollSpeed = val / 10f;
                applyTouchpadConfig();
                return fmt1(scrollSpeed);
            }
        });
        sc.row.set(fmt1(scrollSpeed));
        addSeg("Направление", new String[]{"Естественное", "Обратное"}, invertScroll ? 1 : 0, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                invertScroll = i == 1;
                applyTouchpadConfig();
            }
        });

        addTitle("Отображение");
        SliderRow zone = addValueSlider("Видимость зоны на видео", 0, 100, opacityTpZone, new SliderChange() {
            @Override
            public String onChange(int val) {
                opacityTpZone = val;
                return val + "%";
            }
        });
        zone.row.set(opacityTpZone + "%");
        addHint("0% — зона не видна поверх изображения ПК, но работает.");
        addColorRow("Цвет зоны", colTpZone, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colTpZone = c; applyUserTints(); }
        });

        settingsBody.addView(PcUi.divider(ctx));
        addButtonRow(
                actionBtn(PcIcons.RESET, "Сброс", PcUi.ST_NORMAL, new Runnable() {
                    @Override
                    public void run() {
                        tpNormX = 0.55f;
                        tpNormY = 0.10f;
                        tpNormW = 0.42f;
                        tpNormH = 0.80f;
                        mouseSensitivity = 1.0f;
                        mouseAccel = true;
                        isMouseAbsolute = false;
                        scrollSpeed = 1.0f;
                        invertScroll = false;
                        opacityTpZone = 0;
                        applyTouchpadConfig();
                        savePreferences();
                        renderSplitSettingsContent();
                    }
                }),
                actionBtn(null, "Отмена", PcUi.ST_NORMAL, new Runnable() {
                    @Override
                    public void run() {
                        tpNormX = initX;
                        tpNormY = initY;
                        tpNormW = initW;
                        tpNormH = initH;
                        closeSplitSettingsWithAnimation();
                        Toast.makeText(getContext(), "Изменения зоны тачпада отменены", Toast.LENGTH_SHORT).show();
                    }
                }));
        addButtonRow(actionBtn(PcIcons.CHECK, "Применить", PcUi.ST_PRIMARY, new Runnable() {
            @Override
            public void run() {
                savePreferences();
                closeSplitSettingsWithAnimation();
                Toast.makeText(getContext(), "Настройки тачпада сохранены", Toast.LENGTH_SHORT).show();
            }
        }));
    }

    private void invalidateTouchpadEditor() {
        if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛ: КЛАВИАТУРА (СОБСТВЕННАЯ КЛАВИАТУРА И ПАРАМЕТРЫ)
    // -----------------------------------------------------------------------
    private void buildKeyboardSettingsSection(Context ctx) {
        addTitle("Размер");
        addValueSlider("Высота", 140, 360, kbdHeightDp, new SliderChange() {
            @Override
            public String onChange(int val) {
                kbdHeightDp = val;
                requestLayout();
                return val + " dp";
            }
        }).row.set(kbdHeightDp + " dp");
        addValueSlider("Ширина", 40, 100, kbdWidthPct, new SliderChange() {
            @Override
            public String onChange(int val) {
                kbdWidthPct = val;
                requestLayout();
                return val + "%";
            }
        }).row.set(kbdWidthPct + "%");

        addTitle("Положение");
        addHint("Клавиатуру можно перетащить за полоску сверху.");
        addValueSlider("По горизонтали", 0, 100, Math.round(kbdPosX * 100), new SliderChange() {
            @Override
            public String onChange(int val) {
                kbdPosX = val / 100f;
                requestLayout();
                return val + "%";
            }
        }).row.set(Math.round(kbdPosX * 100) + "%");
        addValueSlider("Отступ снизу", 0, 400, kbdOffsetYDp, new SliderChange() {
            @Override
            public String onChange(int val) {
                kbdOffsetYDp = val;
                requestLayout();
                return val + " dp";
            }
        }).row.set(kbdOffsetYDp + " dp");

        addTitle("Прозрачность");
        addValueSlider("Подложка", 0, 100, opacityKbdBg, new SliderChange() {
            @Override
            public String onChange(int val) {
                opacityKbdBg = val;
                applyOpacities();
                return val + "%";
            }
        }).row.set(opacityKbdBg + "%");
        addValueSlider("Клавиши", 15, 100, opacityKbdKeys, new SliderChange() {
            @Override
            public String onChange(int val) {
                opacityKbdKeys = val;
                applyOpacities();
                return val + "%";
            }
        }).row.set(opacityKbdKeys + "%");

        addTitle("Ввод");
        addSeg("Язык (переключается и клавишей на клавиатуре)", new String[]{"EN", "RU", "UK"}, kbdLayoutIdx, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                kbdLayoutIdx = i;
                if (keyboardLogic != null) keyboardLogic.setLang(i);
            }
        });
        addSeg("Буквенные клавиши", new String[]{"Текст (Unicode)", "Клавиши (игры)"}, kbdGameKeys ? 1 : 0, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                kbdGameKeys = i == 1;
                if (keyboardLogic != null) keyboardLogic.setGameKeys(kbdGameKeys);
            }
        });
        addSeg("Вибрация", new String[]{"Вкл", "Выкл"}, kbdHaptics ? 0 : 1, new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                kbdHaptics = i == 0;
                if (keyboardView != null) keyboardView.setHaptics(kbdHaptics);
            }
        });

        settingsBody.addView(PcUi.divider(ctx));
        addButtonRow(actionBtn(PcIcons.KEYBOARD, "Проверить", PcUi.ST_NORMAL, new Runnable() {
            @Override
            public void run() {
                savePreferences();
                closeSplitSettingsWithAnimation();
                showCustomKeyboard(true);
            }
        }), actionBtn(PcIcons.CHECK, "Сохранить", PcUi.ST_PRIMARY, new Runnable() {
            @Override
            public void run() {
                savePreferences();
                Toast.makeText(getContext(), "Настройки клавиатуры сохранены", Toast.LENGTH_SHORT).show();
            }
        }));
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛ: ПРОЗРАЧНОСТЬ (14 ИНДИВИДУАЛЬНЫХ СЛАЙДЕРОВ С ЖИВЫМ ПРИМЕНЕНИЕМ)
    // -----------------------------------------------------------------------
    private interface OpacitySetter {
        void set(int v);
    }

    private void addColorRow(String label, int selected, PcUi.ColorListener l) {
        TextView t = PcUi.text(getContext(), label, 12.5f, PcUi.SUBTEXT, PcUi.medium());
        t.setPadding(dpToPx(2), dpToPx(10), 0, 0);
        settingsBody.addView(t);
        settingsBody.addView(PcUi.colorPicker(getContext(), selected, l));
    }

    private void buildOpacitySettingsSection(Context ctx) {
        addTitle("Зона тачпада");
        addHint("По умолчанию 0% — зона не видна поверх изображения ПК, но работает.");
        addValueSlider("Видимость зоны", 0, 100, opacityTpZone, new SliderChange() {
            @Override
            public String onChange(int val) {
                opacityTpZone = val;
                updateTouchpadZoneVisibility();
                return val + "%";
            }
        }).row.set(opacityTpZone + "%");
        addColorRow("Цвет зоны", colTpZone, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colTpZone = c; applyUserTints(); }
        });

        addTitle("Шестерёнка");
        addOpacitySlider("Прозрачность", opacityGear, new OpacitySetter() { @Override public void set(int v) { opacityGear = v; } });
        addColorRow("Цвет", colGear, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colGear = c; applyUserTints(); }
        });

        addTitle("Стрелка меню");
        addOpacitySlider("Прозрачность", opacityArrow, new OpacitySetter() { @Override public void set(int v) { opacityArrow = v; } });
        addColorRow("Цвет", colArrow, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colArrow = c; applyUserTints(); }
        });

        addTitle("Выдвижное меню");
        addOpacitySlider("Всё меню", opacityQuickDrawer, new OpacitySetter() { @Override public void set(int v) { opacityQuickDrawer = v; } });
        addOpacitySlider("Кнопка «Мышь»", opacityBtnTouchpad, new OpacitySetter() { @Override public void set(int v) { opacityBtnTouchpad = v; } });
        addOpacitySlider("Кнопка «Клавиатура»", opacityBtnKeyboard, new OpacitySetter() { @Override public void set(int v) { opacityBtnKeyboard = v; } });
        addOpacitySlider("Кнопка «Микрофон»", opacityBtnMic, new OpacitySetter() { @Override public void set(int v) { opacityBtnMic = v; } });
        addOpacitySlider("Кнопка «Звук ПК»", opacityBtnSound, new OpacitySetter() { @Override public void set(int v) { opacityBtnSound = v; } });
        addColorRow("Цвет значков меню", colMenu, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colMenu = c; applyUserTints(); }
        });

        addTitle("Клавиатура");
        addOpacitySlider("Подложка клавиатуры", opacityKbdBg, new OpacitySetter() { @Override public void set(int v) { opacityKbdBg = v; } });
        addOpacitySlider("Клавиши", opacityKbdKeys, new OpacitySetter() { @Override public void set(int v) { opacityKbdKeys = v; } });
        addOpacitySlider("Ряд спец-клавиш", opacityKbdSpecial, new OpacitySetter() { @Override public void set(int v) { opacityKbdSpecial = v; } });
        addColorRow("Цвет букв", colKbdText, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colKbdText = c; applyUserTints(); }
        });

        addTitle("Панели");
        addOpacitySlider("Фон панели настроек", opacitySettings, new OpacitySetter() { @Override public void set(int v) { opacitySettings = v; } });
        addOpacitySlider("Панель диагностики", opacityDiag, new OpacitySetter() { @Override public void set(int v) { opacityDiag = v; } });

        addTitle("Редактор тачпада");
        addOpacitySlider("Рамка зоны", opacityTpBorder, new OpacitySetter() { @Override public void set(int v) { opacityTpBorder = v; } });
        addOpacitySlider("Значок перемещения", opacityTpCenter, new OpacitySetter() { @Override public void set(int v) { opacityTpCenter = v; } });
        addColorRow("Цвет рамки", colTpBorder, new PcUi.ColorListener() {
            @Override public void onColor(int c) { colTpBorder = c; applyUserTints(); }
        });

        settingsBody.addView(PcUi.divider(ctx));
        addButtonRow(actionBtn(PcIcons.GEAR, "Кнопки в правый верхний угол", PcUi.ST_NORMAL, new Runnable() {
            @Override
            public void run() {
                gearPosX = -1f;
                gearPosY = -1f;
                savePreferences();
                requestLayout();
                Toast.makeText(getContext(), "Кнопки возвращены в правый верхний угол", Toast.LENGTH_SHORT).show();
            }
        }));
        addButtonRow(actionBtn(PcIcons.RESET, "Сбросить прозрачность и цвета", PcUi.ST_NORMAL, new Runnable() {
            @Override
            public void run() {
                resetDefaultOpacities();
                resetDefaultColors();
                opacityTpZone = 0;
                updateTouchpadZoneVisibility();
                savePreferences();
                renderSplitSettingsContent();
            }
        }));
    }

    private void addOpacitySlider(String label, int currentVal, final OpacitySetter setter) {
        addValueSlider(label, 10, 100, currentVal, new SliderChange() {
            @Override
            public String onChange(int val) {
                setter.set(val);
                applyOpacities();
                return val + "%";
            }
        }).row.set(currentVal + "%");
    }

    private void applyOpacities() {
        if (floatingGearBtn != null) floatingGearBtn.setAlpha(opacityGear / 100f);
        if (floatingArrowBtn != null) floatingArrowBtn.setAlpha(opacityArrow / 100f);
        // Выдвижное меню: общая прозрачность + отдельная у каждой кнопки
        if (floatingMenuStrip != null && floatingMenuStrip.getVisibility() == View.VISIBLE) {
            floatingMenuStrip.animate().cancel();
            floatingMenuStrip.setAlpha(opacityQuickDrawer / 100f);
        }
        if (floatingKbdBtn != null) floatingKbdBtn.setAlpha(opacityBtnKeyboard / 100f);
        if (floatingMicBtn != null) floatingMicBtn.setAlpha(opacityBtnMic / 100f);
        if (floatingSoundBtn != null) floatingSoundBtn.setAlpha(opacityBtnSound / 100f);
        if (floatingMouseBtn != null) floatingMouseBtn.setAlpha(opacityBtnTouchpad / 100f);
        applyUserTints();
        // Прозрачность панели настроек — только у фона, текст и ползунки остаются читаемыми
        if (settingsCardBg != null) settingsCardBg.setAlpha(Math.round(opacitySettings / 100f * 255));
        if (diagCard != null) diagCard.setAlpha(opacityDiag / 100f);
        if (keyboardPanelBg != null) keyboardPanelBg.setAlpha(Math.round(opacityKbdBg / 100f * 255));
        if (keyboardView != null) keyboardView.setKeyOpacity(opacityKbdKeys / 100f, opacityKbdSpecial / 100f);
        if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
        if (touchpadZoneView != null) touchpadZoneView.invalidate();
    }

    /** Применяет выбранные пользователем цвета к элементам интерфейса. */
    private void applyUserTints() {
        if (floatingGearBtn != null) floatingGearBtn.setTint(colGear);
        if (floatingArrowBtn != null) floatingArrowBtn.setTint(colArrow);
        PcUi.IconBtn[] menu = {floatingSettingsBtn, floatingSoundBtn, floatingMicBtn, floatingFsBtn, floatingKbdBtn, floatingMouseBtn};
        for (PcUi.IconBtn b : menu) if (b != null) b.setTint(colMenu);
        if (keyboardView != null) keyboardView.setKeyTextColor(colKbdText);
        if (touchpadZoneView != null) touchpadZoneView.invalidate();
        if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
    }

    private void resetDefaultColors() {
        colTpZone = DEF_COL_TP_ZONE;
        colGear = PcUi.TEXT;
        colArrow = PcUi.TEXT;
        colMenu = PcUi.TEXT;
        colKbdText = PcUi.TEXT;
        colTpBorder = DEF_COL_TP_BORDER;
        applyUserTints();
    }

    private void resetDefaultOpacities() {
        opacityGear = 85;
        opacityArrow = 85;
        opacityQuickDrawer = 90;
        opacityBtnKeyboard = 100;
        opacityBtnMic = 100;
        opacityBtnSound = 100;
        opacityBtnTouchpad = 100;
        opacitySettings = 95;
        opacityDiag = 90;
        opacityKbdBg = 92;
        opacityKbdKeys = 95;
        opacityKbdSpecial = 95;
        opacityTpBorder = 80;
        opacityTpCenter = 80;
        applyOpacities();
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛЫ: ЭКРАН, КАЧЕСТВО, FPS (как .seg-group в панели демонстрации приложения)
    // -----------------------------------------------------------------------
    private static int indexOf(int[] arr, int v) {
        for (int i = 0; i < arr.length; i++) if (arr[i] == v) return i;
        return -1;
    }

    private void buildScreenSettingsSection(Context ctx) {
        final int[] mIds = {1, 2, 0};
        addSeg("Экран", new String[]{"Экран 1", "Экран 2", "Все экраны"}, indexOf(mIds, targetMonitor), new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                applyVideoSettings(mIds[i], targetHeight, targetFps, targetBitrate);
            }
        });
    }

    private void buildQualitySettingsSection(Context ctx) {
        final int[] rVals = {480, 720, 1080, 0};
        addSeg("Разрешение", new String[]{"480p", "720p", "1080p", "Исходное"}, indexOf(rVals, targetHeight), new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                applyVideoSettings(targetMonitor, rVals[i], targetFps, targetBitrate);
            }
        });
        final int[] bVals = {0, 5, 15, 30, 50};
        addSeg("Битрейт", new String[]{"Авто", "5M", "15M", "30M", "50M"}, indexOf(bVals, targetBitrate), new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                applyVideoSettings(targetMonitor, targetHeight, targetFps, bVals[i]);
            }
        });
    }

    private void buildFpsSettingsSection(Context ctx) {
        final int[] fVals = {30, 60, 90};
        addSeg("Частота", new String[]{"30", "60", "90"}, indexOf(fVals, targetFps), new PcUi.SegListener() {
            @Override
            public void onSelect(int i) {
                applyVideoSettings(targetMonitor, targetHeight, fVals[i], targetBitrate);
            }
        });
    }

    // -----------------------------------------------------------------------
    // СОБСТВЕННАЯ ЭКРАННАЯ КЛАВИАТУРА PC CONTROL
    // -----------------------------------------------------------------------
    private void buildCustomKeyboard(Context context) {
        keyboardLogic = new PcKeyboardLogic(new PcKeyboardLogic.Output() {
            @Override public void key(int vk, boolean down) { inputClient.key(vk, down); }
            @Override public void unicode(int codePoint, boolean down) { inputClient.unicode(codePoint, down); }
            @Override public void hotkey(int[] vks) { inputClient.hotkey(vks); }
            @Override public void onKeyboardChanged() {
                if (keyboardView != null) keyboardView.rebuild();
                if (keyboardLogic != null && keyboardLogic.getLang() != kbdLayoutIdx) {
                    kbdLayoutIdx = keyboardLogic.getLang();
                    savePreferences(); // язык, выбранный клавишей EN/RU/UK, сохраняется между сеансами
                }
            }
            @Override public void onHideRequested() { showCustomKeyboard(false); }
        });
        keyboardLogic.setLang(Math.max(0, Math.min(2, kbdLayoutIdx)));
        keyboardLogic.setGameKeys(kbdGameKeys);

        keyboardPanel = new LinearLayout(context);
        keyboardPanel.setOrientation(LinearLayout.VERTICAL);
        // Подложка как у карточек приложения (.card): #121212, рамка rgba(255,255,255,.13), радиус 18
        keyboardPanelBg = PcUi.shape(PcUi.SURFACE, dpToPx(18), PcUi.BORDER_STRONG, dpToPx(1));
        keyboardPanel.setBackground(keyboardPanelBg);
        int pad = dpToPx(6);
        keyboardPanel.setPadding(pad, 0, pad, pad);
        keyboardPanel.setVisibility(View.GONE);

        // Полоска-ручка: перетаскивание клавиатуры по экрану
        FrameLayout handle = new FrameLayout(context);
        View grip = new View(context);
        grip.setBackground(PcUi.shape(PcUi.MUTED, dpToPx(2), 0, 0));
        handle.addView(grip, new FrameLayout.LayoutParams(dpToPx(44), dpToPx(4), Gravity.CENTER));
        handle.setOnTouchListener(new OnTouchListener() {
            private float startRawX, startRawY, startPosX;
            private int startOffset;

            @Override
            public boolean onTouch(View v, MotionEvent ev) {
                int parentW = Math.max(1, getWidth());
                switch (ev.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        startRawX = ev.getRawX();
                        startRawY = ev.getRawY();
                        startPosX = kbdPosX;
                        startOffset = kbdOffsetYDp;
                        return true;
                    case MotionEvent.ACTION_MOVE: {
                        float density = getResources().getDisplayMetrics().density;
                        kbdPosX = Math.max(0f, Math.min(1f, startPosX + (ev.getRawX() - startRawX) / parentW));
                        kbdOffsetYDp = Math.max(0, Math.min(Math.round(getHeight() / density),
                                startOffset - Math.round((ev.getRawY() - startRawY) / density)));
                        requestLayout();
                        return true;
                    }
                    case MotionEvent.ACTION_UP:
                    case MotionEvent.ACTION_CANCEL:
                        savePreferences();
                        return true;
                }
                return true;
            }
        });
        keyboardPanel.addView(handle, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dpToPx(20)));

        keyboardView = new PcKeyboardView(context, keyboardLogic);
        keyboardView.setHaptics(kbdHaptics);
        keyboardPanel.addView(keyboardView, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f));

        addView(keyboardPanel, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, Gravity.BOTTOM));
        applyOpacities();
    }

    private void toggleCustomKeyboard() {
        showCustomKeyboard(!isKeyboardVisible);
    }

    /** Плавное открытие (выезд снизу + проявление) и закрытие клавиатуры. */
    private void showCustomKeyboard(boolean show) {
        if (show && operatingMode != MODE_PC_CONTROL) return; // в демонстрации ввода нет
        isKeyboardVisible = show;
        if (keyboardPanel != null) {
            keyboardPanel.animate().cancel();
            if (show) {
                ensureInputClient();
                if (keyboardView != null) keyboardView.rebuild();
                keyboardPanel.setVisibility(View.VISIBLE);
                float h = keyboardPanel.getHeight() > 0 ? keyboardPanel.getHeight() : dpToPx(kbdHeightDp);
                keyboardPanel.setAlpha(0f);
                keyboardPanel.setTranslationY(h * 0.35f);
                keyboardPanel.animate()
                        .alpha(1f)
                        .translationY(0f)
                        .setDuration(220)
                        .setInterpolator(new DecelerateInterpolator())
                        .setListener(null)
                        .start();
            } else {
                // При закрытии отпускаем всё: и клавиши под пальцами, и зафиксированные модификаторы
                if (keyboardView != null) keyboardView.releaseAllPointers();
                if (keyboardLogic != null) keyboardLogic.releaseAll();
                if (keyboardPanel.getVisibility() == View.VISIBLE) {
                    keyboardPanel.animate()
                            .alpha(0f)
                            .translationY(keyboardPanel.getHeight() * 0.35f)
                            .setDuration(180)
                            .setInterpolator(new AccelerateInterpolator())
                            .setListener(new AnimatorListenerAdapter() {
                                @Override
                                public void onAnimationEnd(Animator animation) {
                                    if (!isKeyboardVisible) {
                                        keyboardPanel.setVisibility(View.GONE);
                                        keyboardPanel.setTranslationY(0f);
                                    }
                                }
                            })
                            .start();
                }
            }
        }
        updateQuickActionStates();
    }

    // -----------------------------------------------------------------------
    // ВИЗУАЛЬНЫЙ РЕДАКТОР ТАЧПАДА НА ЭКРАНЕ (8 маркеров и центральный якорь)
    // -----------------------------------------------------------------------
    private class TouchpadVisualEditorView extends View {
        private final RectF zoneRect = new RectF();
        private int activeHandle = -1; // -1=none, 0=center, 1..8=handles
        private float lastX, lastY;

        public TouchpadVisualEditorView(Context context) {
            super(context);
        }

        @Override
        protected void onDraw(android.graphics.Canvas canvas) {
            super.onDraw(canvas);
            int w = getWidth();
            int h = getHeight();
            if (w <= 0 || h <= 0) return;

            zoneRect.set(tpNormX * w, tpNormY * h, (tpNormX + tpNormW) * w, (tpNormY + tpNormH) * h);

            // Полупрозрачная заливка рабочей области
            android.graphics.Paint fillPaint = new android.graphics.Paint();
            fillPaint.setColor((colTpBorder & 0x00FFFFFF) | 0x26000000);
            fillPaint.setStyle(android.graphics.Paint.Style.FILL);
            canvas.drawRoundRect(zoneRect, dpToPx(16), dpToPx(16), fillPaint);

            // Рамка зоны тачпада
            android.graphics.Paint borderPaint = new android.graphics.Paint();
            borderPaint.setColor(colTpBorder);
            borderPaint.setAlpha((int) ((opacityTpBorder / 100f) * 255));
            borderPaint.setStyle(android.graphics.Paint.Style.STROKE);
            borderPaint.setStrokeWidth(dpToPx(2));
            canvas.drawRoundRect(zoneRect, dpToPx(16), dpToPx(16), borderPaint);

            // Центральный маркер перетаскивания (✥)
            android.graphics.Paint textPaint = new android.graphics.Paint();
            textPaint.setColor(Color.WHITE);
            textPaint.setTextSize(dpToPx(20));
            textPaint.setTextAlign(android.graphics.Paint.Align.CENTER);
            textPaint.setAlpha((int) ((opacityTpCenter / 100f) * 255));
            canvas.drawText("✥", zoneRect.centerX(), zoneRect.centerY() + dpToPx(7), textPaint);

            // Угловые и краевые маркеры изменения размеров (8 кружков)
            android.graphics.Paint handlePaint = new android.graphics.Paint();
            handlePaint.setColor(Color.WHITE);
            handlePaint.setStyle(android.graphics.Paint.Style.FILL);

            float r = dpToPx(6);
            canvas.drawCircle(zoneRect.left, zoneRect.top, r, handlePaint);
            canvas.drawCircle(zoneRect.right, zoneRect.top, r, handlePaint);
            canvas.drawCircle(zoneRect.left, zoneRect.bottom, r, handlePaint);
            canvas.drawCircle(zoneRect.right, zoneRect.bottom, r, handlePaint);
            canvas.drawCircle(zoneRect.centerX(), zoneRect.top, r, handlePaint);
            canvas.drawCircle(zoneRect.centerX(), zoneRect.bottom, r, handlePaint);
            canvas.drawCircle(zoneRect.left, zoneRect.centerY(), r, handlePaint);
            canvas.drawCircle(zoneRect.right, zoneRect.centerY(), r, handlePaint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            float x = event.getX();
            float y = event.getY();
            int w = getWidth();
            int h = getHeight();

            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    lastX = x;
                    lastY = y;
                    float touchRadius = dpToPx(24);
                    // Определение маркера: 0=Центр, 1..8=Границы
                    if (Math.hypot(x - zoneRect.centerX(), y - zoneRect.centerY()) < touchRadius * 1.5) {
                        activeHandle = 0; // Перетаскивание всего тачпада
                    } else if (Math.hypot(x - zoneRect.right, y - zoneRect.bottom) < touchRadius) {
                        activeHandle = 4; // Правый нижний угол
                    } else if (Math.hypot(x - zoneRect.left, y - zoneRect.bottom) < touchRadius) {
                        activeHandle = 3; // Левый нижний угол
                    } else if (Math.hypot(x - zoneRect.right, y - zoneRect.top) < touchRadius) {
                        activeHandle = 2; // Правый верхний угол
                    } else if (Math.hypot(x - zoneRect.left, y - zoneRect.top) < touchRadius) {
                        activeHandle = 1; // Левый верхний угол
                    } else if (Math.abs(x - zoneRect.right) < touchRadius) {
                        activeHandle = 6; // Правая граница
                    } else if (Math.abs(x - zoneRect.left) < touchRadius) {
                        activeHandle = 5; // Левая граница
                    } else if (Math.abs(y - zoneRect.bottom) < touchRadius) {
                        activeHandle = 8; // Нижняя граница
                    } else if (Math.abs(y - zoneRect.top) < touchRadius) {
                        activeHandle = 7; // Верхняя граница
                    } else {
                        activeHandle = 0;
                    }
                    return true;

                case MotionEvent.ACTION_MOVE:
                    float dx = (x - lastX) / (float) w;
                    float dy = (y - lastY) / (float) h;
                    lastX = x;
                    lastY = y;

                    if (activeHandle == 0) {
                        // 0: Перемещение центра
                        tpNormX = Math.max(0f, Math.min(1f - tpNormW, tpNormX + dx));
                        tpNormY = Math.max(0f, Math.min(1f - tpNormH, tpNormY + dy));
                    } else if (activeHandle == 1) {
                        // 1: Левый верхний угол
                        float newX = Math.max(0f, Math.min(tpNormX + tpNormW - 0.15f, tpNormX + dx));
                        float newY = Math.max(0f, Math.min(tpNormY + tpNormH - 0.15f, tpNormY + dy));
                        tpNormW += (tpNormX - newX);
                        tpNormH += (tpNormY - newY);
                        tpNormX = newX;
                        tpNormY = newY;
                    } else if (activeHandle == 2) {
                        // 2: Правый верхний угол
                        float newY = Math.max(0f, Math.min(tpNormY + tpNormH - 0.15f, tpNormY + dy));
                        tpNormH += (tpNormY - newY);
                        tpNormY = newY;
                        tpNormW = Math.max(0.15f, Math.min(1f - tpNormX, tpNormW + dx));
                    } else if (activeHandle == 3) {
                        // 3: Левый нижний угол
                        float newX = Math.max(0f, Math.min(tpNormX + tpNormW - 0.15f, tpNormX + dx));
                        tpNormW += (tpNormX - newX);
                        tpNormX = newX;
                        tpNormH = Math.max(0.15f, Math.min(1f - tpNormY, tpNormH + dy));
                    } else if (activeHandle == 4) {
                        // 4: Правый нижний угол
                        tpNormW = Math.max(0.15f, Math.min(1f - tpNormX, tpNormW + dx));
                        tpNormH = Math.max(0.15f, Math.min(1f - tpNormY, tpNormH + dy));
                    } else if (activeHandle == 5) {
                        // 5: Левая граница
                        float newX = Math.max(0f, Math.min(tpNormX + tpNormW - 0.15f, tpNormX + dx));
                        tpNormW += (tpNormX - newX);
                        tpNormX = newX;
                    } else if (activeHandle == 6) {
                        // 6: Правая граница
                        tpNormW = Math.max(0.15f, Math.min(1f - tpNormX, tpNormW + dx));
                    } else if (activeHandle == 7) {
                        // 7: Верхняя граница
                        float newY = Math.max(0f, Math.min(tpNormY + tpNormH - 0.15f, tpNormY + dy));
                        tpNormH += (tpNormY - newY);
                        tpNormY = newY;
                    } else if (activeHandle == 8) {
                        // 8: Нижняя граница
                        tpNormH = Math.max(0.15f, Math.min(1f - tpNormY, tpNormH + dy));
                    }
                    invalidate();
                    if (touchpadBoundsListener != null) {
                        touchpadBoundsListener.onBoundsChanged(tpNormX, tpNormY, tpNormW, tpNormH);
                    }
                    return true;

                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    activeHandle = -1;
                    return true;
            }
            return super.onTouchEvent(event);
        }
    }

    // -----------------------------------------------------------------------
    // МУЛЬТИТАЧ: ПРОЗРАЧНЫЙ ТАЧПАД / ПРЯМОЕ КАСАНИЕ (жесты — PcTouchpadEngine)
    // -----------------------------------------------------------------------
    private boolean handleTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        int w = videoContainer.getWidth();
        int h = videoContainer.getHeight();

        // Открыта панель настроек: касание живого видео закрывает её
        if (isSplitSettingsOpen && !isTouchpadEditing) {
            if (action == MotionEvent.ACTION_UP) closeSplitSettingsWithAnimation();
            return true;
        }

        if (!isMouseActive() || isTouchpadEditing || w <= 0 || h <= 0) {
            touchGestureOwned = false;
            if (operatingMode == MODE_VIEW) {
                // В режиме просмотра тапы скрывают/показывают тулбар
                if (action == MotionEvent.ACTION_UP) setControlsVisible(!isControlsVisible, true);
                return true;
            }
            return false;
        }

        if (action == MotionEvent.ACTION_DOWN) {
            float x = event.getX();
            float y = event.getY();
            boolean inside;
            if (isMouseAbsolute) {
                // Прямое касание: рабочая область = видимая картинка ПК
                inside = videoViewportRect.width() > 0 && videoViewportRect.contains((int) x, (int) y);
                touchpadEngine.setViewport(videoViewportRect.left, videoViewportRect.top,
                        videoViewportRect.width(), videoViewportRect.height());
            } else {
                inside = x >= tpNormX * w && x <= (tpNormX + tpNormW) * w
                        && y >= tpNormY * h && y <= (tpNormY + tpNormH) * h;
            }
            touchGestureOwned = inside;
            if (inside) ensureInputClient();
        }

        if (!touchGestureOwned) {
            if (operatingMode == MODE_VIEW && action == MotionEvent.ACTION_UP) {
                setControlsVisible(!isControlsVisible, true);
            }
            return operatingMode == MODE_VIEW;
        }

        int n = Math.min(event.getPointerCount(), tpIds.length);
        for (int i = 0; i < n; i++) {
            tpIds[i] = event.getPointerId(i);
            tpXs[i] = event.getX(i);
            tpYs[i] = event.getY(i);
        }
        int actionIndex = Math.min(event.getActionIndex(), n - 1);
        // Константы ACTION_* движка совпадают с MotionEvent
        touchpadEngine.onTouch(action, actionIndex, n, tpIds, tpXs, tpYs, event.getEventTime());

        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            touchGestureOwned = false;
        }
        return true;
    }

    // -----------------------------------------------------------------------
    // МИКРОФОН ТЕЛЕФОНА -> WINDOWS PC (MicSenderThread)
    // -----------------------------------------------------------------------
    private void toggleMicStreaming() {
        if (isMicStreaming) {
            stopMicStreaming();
        } else {
            startMicStreaming();
        }
    }

    /** Нажали «Микрофон», но разрешения ещё не было: после ответа пользователя включаем сами. */
    private boolean pendingMicStart = false;
    /** Предыдущий поток микрофона: новый ждёт его завершения (на многих телефонах одновременно может писать только один AudioRecord). */
    private MicSenderThread lastMicThread = null;

    private void startMicStreaming() {
        if (!isStreaming.get() || operatingMode != MODE_PC_CONTROL) {
            Toast.makeText(getContext(), "Микрофон работает только во время «Управления ПК»", Toast.LENGTH_SHORT).show();
            return;
        }
        MainActivity act = MainActivity.getInstance();
        if (act != null && !act.checkOrRequestRecordAudioPermission()) {
            pendingMicStart = true;
            Toast.makeText(getContext(), "Разрешите доступ к микрофону — передача начнётся автоматически", Toast.LENGTH_LONG).show();
            return;
        }

        synchronized (micLock) {
            if (isMicStreaming) return;
            isMicStreaming = true;
            micSenderThread = new MicSenderThread(lastMicThread);
            lastMicThread = micSenderThread;
            micSenderThread.start();
        }
        updateQuickActionStates();
        Toast.makeText(getContext(), "Подключение микрофона к ПК…", Toast.LENGTH_SHORT).show();
    }

    /** Ответ на системный запрос разрешения RECORD_AUDIO (вызывается из MainActivity). */
    public void onRecordAudioPermissionResult(boolean granted) {
        if (!pendingMicStart) return;
        pendingMicStart = false;
        if (granted) {
            startMicStreaming();
        } else {
            Toast.makeText(getContext(), "Без разрешения на запись звука микрофон телефона не работает", Toast.LENGTH_LONG).show();
        }
    }

    private void stopMicStreaming() {
        synchronized (micLock) {
            isMicStreaming = false;
            pendingMicStart = false;
            if (micSenderThread != null) {
                micSenderThread.shutdown();
                micSenderThread = null;
            }
        }
        updateQuickActionStates();
    }

    /** Ошибка из потока микрофона: выключаем кнопку, только если это всё ещё текущий поток. */
    private void failMic(final MicSenderThread from, final String message) {
        post(new Runnable() {
            @Override public void run() {
                boolean current;
                synchronized (micLock) {
                    current = (micSenderThread == from);
                }
                if (!current) return; // пользователь уже выключил/перезапустил микрофон
                stopMicStreaming();
                if (message != null) Toast.makeText(getContext(), message, Toast.LENGTH_LONG).show();
            }
        });
    }

    /**
     * Телефон → ПК: AudioRecord (16 бит, моно) → HTTP chunked POST /api/mic/stream → сервер
     * проигрывает звук в виртуальный кабель (VB-CABLE «CABLE Input»), и в Windows он доступен
     * как микрофон «CABLE Output». Без виртуального кабеля сервер отвечает 400.
     */
    private class MicSenderThread extends Thread {
        private final AtomicBoolean active = new AtomicBoolean(true);
        private final MicSenderThread previous;

        MicSenderThread(MicSenderThread previous) {
            super("pc-control-mic-sender");
            this.previous = previous;
        }

        /** Проверка до захвата микрофона: пароль, версия сервера и наличие виртуального кабеля. */
        private String precheck() {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(serverUrl + "/api/mic/status").openConnection();
                c.setConnectTimeout(4000);
                c.setReadTimeout(6000);
                if (!authToken.isEmpty()) c.setRequestProperty("X-Auth-Token", authToken);
                int code = c.getResponseCode();
                if (code == 401) return "Микрофон: неверный пароль сервера";
                if (code == 404) return "Сервер PC Control на ПК устарел — обновите его, чтобы передавать микрофон";
                if (code != 200) return "Микрофон: сервер ответил ошибкой " + code;
                StringBuilder sb = new StringBuilder();
                try (InputStream in = c.getInputStream()) {
                    byte[] b = new byte[2048];
                    int n;
                    while ((n = in.read(b)) > 0) sb.append(new String(b, 0, n, StandardCharsets.UTF_8));
                }
                org.json.JSONObject st = new org.json.JSONObject(sb.toString());
                if (!st.optBoolean("virtual_cable_detected", false) && !st.optBoolean("active", false)) {
                    return "На ПК не найден виртуальный аудиокабель (VB-CABLE). Установите его — "
                            + "тогда голос с телефона появится в Windows как микрофон «CABLE Output».";
                }
                return null;
            } catch (Exception e) {
                return "Микрофон: нет связи с ПК";
            } finally {
                if (c != null) try { c.disconnect(); } catch (Exception ignored) {}
            }
        }

        private AudioRecord openRecorder(int sampleRate) {
            int channelConfig = AudioFormat.CHANNEL_IN_MONO;
            int fmt = AudioFormat.ENCODING_PCM_16BIT;
            int min = AudioRecord.getMinBufferSize(sampleRate, channelConfig, fmt);
            if (min <= 0) return null;
            int bufferSize = Math.max(min * 2, sampleRate / 5); // ≥ 100 мс
            // VOICE_COMMUNICATION включает эхоподавление: звук ПК из динамика телефона
            // не возвращается обратно на ПК. Если источник недоступен — обычный MIC.
            int[] sources = {MediaRecorder.AudioSource.VOICE_COMMUNICATION, MediaRecorder.AudioSource.MIC};
            for (int src : sources) {
                AudioRecord r = null;
                try {
                    r = new AudioRecord(src, sampleRate, channelConfig, fmt, bufferSize);
                    if (r.getState() == AudioRecord.STATE_INITIALIZED) return r;
                } catch (Exception ignored) {}
                if (r != null) try { r.release(); } catch (Exception ignored) {}
            }
            return null;
        }

        @Override
        public void run() {
            if (previous != null) {
                previous.shutdown();
                try { previous.join(1500); } catch (InterruptedException e) { return; }
            }
            if (!active.get()) return;

            String problem = precheck();
            if (problem != null) {
                if (active.get()) failMic(this, problem);
                return;
            }
            if (!active.get()) return;

            AudioRecord recorder = null;
            HttpURLConnection conn = null;
            boolean userStopped = false;
            try {
                int sampleRate = 48000;
                recorder = openRecorder(sampleRate);
                if (recorder == null) {
                    sampleRate = 16000;
                    recorder = openRecorder(sampleRate);
                }
                if (recorder == null) {
                    failMic(this, "Микрофон телефона занят другим приложением или недоступен");
                    return;
                }
                recorder.startRecording();
                if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                    failMic(this, "Микрофон телефона занят другим приложением");
                    return;
                }

                // 20 мс звука на пакет — небольшая задержка без лишних накладных расходов
                int chunk = sampleRate / 50 * 2;
                conn = (HttpURLConnection) new URL(serverUrl + "/api/mic/stream?rate=" + sampleRate + "&channels=1").openConnection();
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setConnectTimeout(4000);
                conn.setReadTimeout(8000);
                conn.setChunkedStreamingMode(chunk);
                conn.setRequestProperty("Content-Type", "application/octet-stream");
                if (!authToken.isEmpty()) conn.setRequestProperty("X-Auth-Token", authToken);

                boolean announced = false;
                try (OutputStream os = conn.getOutputStream()) {
                    byte[] buf = new byte[chunk];
                    while (active.get() && isStreaming.get()) {
                        int read = recorder.read(buf, 0, buf.length);
                        if (read > 0) {
                            os.write(buf, 0, read);
                            os.flush();
                            if (!announced) {
                                announced = true;
                                post(new Runnable() {
                                    @Override public void run() {
                                        if (isMicStreaming) Toast.makeText(getContext(), "Микрофон телефона передаётся на ПК", Toast.LENGTH_SHORT).show();
                                    }
                                });
                            }
                        } else if (read < 0) {
                            throw new java.io.IOException("AudioRecord.read " + read);
                        }
                    }
                }
                userStopped = !active.get();
                int code = conn.getResponseCode();
                if (code == 400) {
                    failMic(this, "На ПК не найден виртуальный аудиокабель (VB-CABLE)");
                } else if (code == 401) {
                    failMic(this, "Микрофон: неверный пароль сервера");
                } else if (code != 200 && !userStopped) {
                    failMic(this, "Микрофон: сервер ответил ошибкой " + code);
                }
            } catch (Exception e) {
                if (active.get() && isStreaming.get()) {
                    // Сервер мог ответить ошибкой до конца передачи — пробуем прочитать код
                    String msg = "Передача микрофона прервалась (нет связи с ПК)";
                    try {
                        if (conn != null && conn.getResponseCode() == 400) msg = "На ПК не найден виртуальный аудиокабель (VB-CABLE)";
                    } catch (Exception ignored) {}
                    failMic(this, msg);
                }
            } finally {
                if (recorder != null) {
                    try { recorder.stop(); } catch (Exception ignored) {}
                    try { recorder.release(); } catch (Exception ignored) {}
                }
                if (conn != null) try { conn.disconnect(); } catch (Exception ignored) {}
            }
        }

        void shutdown() {
            active.set(false);
        }
    }

    // -----------------------------------------------------------------------
    // СТАНДАРТНЫЙ АУДИОДВИЖОК WASAPI LOOPBACK (AudioPlayerThread)
    // -----------------------------------------------------------------------
    private class AudioPlayerThread extends Thread {
        private final AtomicBoolean running = new AtomicBoolean(true);
        private AudioTrack audioTrack;

        public AudioPlayerThread() {
            super("pc-control-wasapi-audio");
        }

        @Override
        public void run() {
            int audioFormat = AudioFormat.ENCODING_PCM_16BIT;
            int frameBytes = 4; // 16 бит × каналы (по заголовку WAV)
            int trackRate = 0, trackChannels = 0;

            try {

                int attempt = 0;
                // Переподключение при обрыве сети: раньше звук ПК пропадал до конца сеанса
                while (running.get() && isStreaming.get()) {
                    if (attempt > 0) {
                        updateAudioStatusOnMain("Переподключение...", Color.parseColor("#38BDF8"));
                        try { Thread.sleep(Math.min(3000, 600L * attempt)); } catch (InterruptedException e) { break; }
                        if (!running.get() || !isStreaming.get()) break;
                    } else {
                        updateAudioStatusOnMain("Подключение...", Color.parseColor("#38BDF8"));
                    }
                    attempt++;
                    refreshStreamVolume();
                    HttpURLConnection c = null;
                    try {
                        String aUrl = serverUrl + "/audio?token=" + URLEncoder.encode(authToken, "UTF-8") + "&t=" + System.currentTimeMillis();
                        c = (HttpURLConnection) new URL(aUrl).openConnection();
                        c.setConnectTimeout(4000);
                        c.setReadTimeout(10000);
                        c.setRequestProperty("Accept", "audio/wav");
                        int code = c.getResponseCode();
                        if (code == 401) {
                            updateAudioStatusOnMain("Ошибка пароля", PcUi.DANGER);
                            break;
                        }
                        if (code != 200) {
                            updateAudioStatusOnMain("Ошибка (" + code + ")", PcUi.DANGER);
                            continue;
                        }
                        try (InputStream raw = c.getInputStream();
                             BufferedInputStream bis = new BufferedInputStream(raw, 16384)) {

                            // Заголовок WAV: частота и число каналов берутся из него (звуковая карта
                            // ПК может работать на 44,1 кГц — раньше всё играло как 48 кГц стерео).
                            bis.mark(64);
                            byte[] hdr = new byte[44];
                            int rHdr = 0;
                            while (rHdr < 44) {
                                int n = bis.read(hdr, rHdr, 44 - rHdr);
                                if (n <= 0) break;
                                rHdr += n;
                            }
                            int rate = 48000, channels = 2;
                            if (rHdr == 44 && hdr[0] == 'R' && hdr[1] == 'I' && hdr[2] == 'F' && hdr[3] == 'F'
                                    && hdr[8] == 'W' && hdr[9] == 'A' && hdr[10] == 'V' && hdr[11] == 'E') {
                                int ch = (hdr[22] & 0xFF) | ((hdr[23] & 0xFF) << 8);
                                int sr = (hdr[24] & 0xFF) | ((hdr[25] & 0xFF) << 8)
                                        | ((hdr[26] & 0xFF) << 16) | ((hdr[27] & 0xFF) << 24);
                                if (ch >= 1 && ch <= 2) channels = ch;
                                if (sr >= 8000 && sr <= 192000) rate = sr;
                            } else {
                                bis.reset();
                            }
                            if (audioTrack == null || rate != trackRate || channels != trackChannels) {
                                if (audioTrack != null) {
                                    try { audioTrack.stop(); audioTrack.release(); } catch (Exception ignored) {}
                                }
                                int cfgOut = channels == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
                                int minBuf = AudioTrack.getMinBufferSize(rate, cfgOut, audioFormat);
                                audioTrack = new AudioTrack(AudioManager.STREAM_MUSIC, rate, cfgOut, audioFormat,
                                        Math.max(minBuf * 2, 8192), AudioTrack.MODE_STREAM);
                                // Громкость задаёт ползунок «Громкость демонстрации» (0–200 %) —
                                // программное усиление PcAudioGain; сам AudioTrack на полной громкости.
                                audioTrack.setVolume(1.0f);
                                audioTrack.play();
                                trackRate = rate;
                                trackChannels = channels;
                            }
                            frameBytes = 2 * channels;
                            updateAudioStatusOnMain("Подключен (" + (rate / 1000) + " kHz)", Color.parseColor("#22C55E"));

                            byte[] chunk = new byte[1920 + frameBytes];
                            int carry = 0;
                            long totalBytesWritten = 0;
                            long startHead = audioTrack.getPlaybackHeadPosition();

                            while (running.get() && isStreaming.get()) {
                                int r = bis.read(chunk, carry, 1920);
                                if (r <= 0) break;
                                attempt = 1; // поток идёт — следующий обрыв переподключаем быстро
                                int avail = carry + r;
                                // Сеть отдаёт куски произвольной длины: пишем только целые кадры,
                                // хвост переносим. Иначе AudioTrack отбрасывал кусок и все
                                // последующие сэмплы сдвигались — вместо звука шёл шум.
                                int whole = avail - (avail % frameBytes);
                                if (whole > 0) {
                                    gain.apply(chunk, whole, PcAudioGain.percentToGain(streamVolumePercent, streamVolumeMuted));

                                    // Компенсация дрифта (порог 100 мс)
                                    long playHead = audioTrack.getPlaybackHeadPosition() - startHead;
                                    long latencyFrames = totalBytesWritten / frameBytes - playHead;
                                    if (latencyFrames > trackRate / 10) {
                                        audioTrack.flush();
                                        startHead = audioTrack.getPlaybackHeadPosition();
                                        totalBytesWritten = 0;
                                    }

                                    int written = audioTrack.write(chunk, 0, whole);
                                    if (written > 0) totalBytesWritten += written;
                                }
                                carry = avail - whole;
                                if (carry > 0) System.arraycopy(chunk, whole, chunk, 0, carry);
                            }
                        }
                    } catch (Exception e) {
                        // обрыв — переподключимся на следующей итерации
                    } finally {
                        if (c != null) try { c.disconnect(); } catch (Exception ignored) {}
                    }
                }
                updateAudioStatusOnMain("Отключен", PcUi.SUBTEXT);
            } catch (Exception e) {
                updateAudioStatusOnMain("Отключен", PcUi.SUBTEXT);
            } finally {
                if (audioTrack != null) {
                    try {
                        audioTrack.stop();
                        audioTrack.release();
                    } catch (Exception ignored) {}
                    audioTrack = null;
                }
            }
        }

        private final PcAudioGain gain = new PcAudioGain();

        public void shutdown() {
            running.set(false);
            interrupt();
        }
    }

    // Громкость демонстрации (общая с ползунком приложения, хранится на ПК: /screen/volume)
    private volatile int streamVolumePercent = 50;
    private volatile boolean streamVolumeMuted = false;

    /** Читает с ПК громкость демонстрации, выбранную ползунком в приложении (0–200 %). */
    private void refreshStreamVolume() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(serverUrl + "/screen/volume").openConnection();
            c.setConnectTimeout(3000);
            c.setReadTimeout(3000);
            if (!authToken.isEmpty()) c.setRequestProperty("X-Auth-Token", authToken);
            if (c.getResponseCode() != 200) return;
            StringBuilder sb = new StringBuilder();
            try (InputStream in = c.getInputStream()) {
                byte[] b = new byte[512];
                int n;
                while ((n = in.read(b)) > 0) sb.append(new String(b, 0, n, StandardCharsets.UTF_8));
            }
            org.json.JSONObject o = new org.json.JSONObject(sb.toString());
            streamVolumePercent = Math.max(0, Math.min(PcAudioGain.MAX_PERCENT, o.optInt("percent", streamVolumePercent)));
            streamVolumeMuted = o.optBoolean("muted", false);
        } catch (Exception ignored) {
        } finally {
            if (c != null) try { c.disconnect(); } catch (Exception ignored) {}
        }
    }

    /** Громкость из интерфейса приложения (мост WebView), применяется сразу. */
    public void setStreamVolume(int percent, boolean muted) {
        streamVolumePercent = Math.max(0, Math.min(PcAudioGain.MAX_PERCENT, percent));
        streamVolumeMuted = muted;
    }

    private void updateAudioStatusOnMain(final String status, final int color) {
        audioStatus = status;
        audioStatusColor = color;
    }

    private void setAudioEnabled(boolean enabled) {
        this.isAudioEnabled = enabled;
        savePreferences();
        if (enabled) {
            startAudioStream();
        } else {
            stopAudioStream();
            updateAudioStatusOnMain("Выключен", PcUi.SUBTEXT);
        }
    }

    private void startAudioStream() {
        synchronized (audioLock) {
            stopAudioStream();
            audioThread = new AudioPlayerThread();
            audioThread.start();
        }
    }

    private void stopAudioStream() {
        synchronized (audioLock) {
            if (audioThread != null) {
                audioThread.shutdown();
                audioThread = null;
            }
        }
    }

    // -----------------------------------------------------------------------
    // СОХРАНЕНИЕ И ВОССТАНОВЛЕНИЕ НАСТРОЕК (SharedPreferences)
    // -----------------------------------------------------------------------
    private void loadPreferences() {
        try {
            SharedPreferences sp = getContext().getSharedPreferences("pc_control_settings", Context.MODE_PRIVATE);
            scaleMode = sp.getInt("scale_mode", SCALE_MODE_FIT);
            targetMonitor = sp.getInt("target_monitor", 1);
            targetHeight = sp.getInt("target_height", 1080);
            targetFps = sp.getInt("target_fps", 60);
            targetBitrate = sp.getInt("target_bitrate", 0);
            isAudioEnabled = sp.getBoolean("audio_enabled", true);
            audioVolume = sp.getInt("audio_volume", 80);

            tpNormX = sp.getFloat("tp_x", 0.55f);
            tpNormY = sp.getFloat("tp_y", 0.10f);
            tpNormW = sp.getFloat("tp_w", 0.42f);
            tpNormH = sp.getFloat("tp_h", 0.80f);
            mouseSensitivity = sp.getFloat("mouse_sens", 1.0f);
            mouseAccel = sp.getBoolean("mouse_accel", true);
            isMouseAbsolute = sp.getBoolean("mouse_abs", false);

            opacityGear = sp.getInt("op_gear", 85);
            opacityArrow = sp.getInt("op_arrow", 85);
            opacityQuickDrawer = sp.getInt("op_quick", 90);
            opacityBtnKeyboard = sp.getInt("op_b_kbd", 100);
            opacityBtnMic = sp.getInt("op_b_mic", 100);
            opacityBtnSound = sp.getInt("op_b_snd", 100);
            opacityBtnTouchpad = sp.getInt("op_b_tp", 100);
            opacitySettings = sp.getInt("op_sett", 95);
            opacityDiag = sp.getInt("op_diag", 90);
            opacityKbdBg = sp.getInt("op_kbd_bg", 92);
            opacityKbdKeys = sp.getInt("op_kbd_keys", 95);
            opacityKbdSpecial = sp.getInt("op_kbd_sp", 95);
            opacityTpBorder = sp.getInt("op_tp_bord", 80);
            opacityTpCenter = sp.getInt("op_tp_cent", 80);

            scrollSpeed = sp.getFloat("scroll_speed", 1.0f);
            invertScroll = sp.getBoolean("scroll_invert", false);
            opacityTpZone = sp.getInt("op_tp_zone", 0);
            colTpZone = sp.getInt("col_tp_zone", DEF_COL_TP_ZONE);
            colGear = sp.getInt("col_gear", PcUi.TEXT);
            colArrow = sp.getInt("col_arrow", PcUi.TEXT);
            colMenu = sp.getInt("col_menu", PcUi.TEXT);
            colKbdText = sp.getInt("col_kbd", PcUi.TEXT);
            colTpBorder = sp.getInt("col_tp_bord", DEF_COL_TP_BORDER);

            kbdWidthPct = Math.max(40, Math.min(100, sp.getInt("kbd_w", 100)));
            kbdHeightDp = Math.max(140, Math.min(360, sp.getInt("kbd_h", 220)));
            kbdLayoutIdx = sp.getInt("kbd_layout", 0);
            if (kbdLayoutIdx < 0 || kbdLayoutIdx > 2) kbdLayoutIdx = 0; // старое значение 3 = символы
            kbdPosX = sp.getFloat("kbd_x", 0.5f);
            kbdOffsetYDp = sp.getInt("kbd_off_y", 8);
            kbdHaptics = sp.getBoolean("kbd_haptics", true);
            kbdGameKeys = sp.getBoolean("kbd_game_keys", false);

            gearPosX = sp.getFloat("gear_x", -1f);
            gearPosY = sp.getFloat("gear_y", -1f);
            if (sp.getInt("ui_rev", 0) < 3) {
                // Раньше перетаскивание сохраняло координату с двойным смещением (setX + layout):
                // один раз возвращаем кнопки в положение по умолчанию — правый верхний угол.
                gearPosX = -1f;
                gearPosY = -1f;
                sp.edit().putInt("ui_rev", 3).remove("gear_x").remove("gear_y").apply();
            }
            if (sp.getInt("ui_rev", 0) < 4) {
                // v2.3.4: зона тачпада по умолчанию невидима; позиция шестерёнки теперь хранится
                // по правому краю (меню выдвигается влево) — возвращаем в правый верхний угол.
                opacityTpZone = 0;
                gearPosX = -1f;
                gearPosY = -1f;
                sp.edit().putInt("ui_rev", 4).putInt("op_tp_zone", 0).remove("gear_x").remove("gear_y").apply();
            }
        } catch (Exception ignored) {}
    }

    private void savePreferences() {
        try {
            SharedPreferences sp = getContext().getSharedPreferences("pc_control_settings", Context.MODE_PRIVATE);
            sp.edit()
                    .putInt("scale_mode", scaleMode)
                    .putInt("target_monitor", targetMonitor)
                    .putInt("target_height", targetHeight)
                    .putInt("target_fps", targetFps)
                    .putInt("target_bitrate", targetBitrate)
                    .putBoolean("audio_enabled", isAudioEnabled)
                    .putInt("audio_volume", audioVolume)
                    .putFloat("tp_x", tpNormX)
                    .putFloat("tp_y", tpNormY)
                    .putFloat("tp_w", tpNormW)
                    .putFloat("tp_h", tpNormH)
                    .putFloat("mouse_sens", mouseSensitivity)
                    .putBoolean("mouse_accel", mouseAccel)
                    .putBoolean("mouse_abs", isMouseAbsolute)
                    .putInt("op_gear", opacityGear)
                    .putInt("op_arrow", opacityArrow)
                    .putInt("op_quick", opacityQuickDrawer)
                    .putInt("op_b_kbd", opacityBtnKeyboard)
                    .putInt("op_b_mic", opacityBtnMic)
                    .putInt("op_b_snd", opacityBtnSound)
                    .putInt("op_b_tp", opacityBtnTouchpad)
                    .putInt("op_sett", opacitySettings)
                    .putInt("op_diag", opacityDiag)
                    .putInt("op_kbd_bg", opacityKbdBg)
                    .putInt("op_kbd_keys", opacityKbdKeys)
                    .putInt("op_kbd_sp", opacityKbdSpecial)
                    .putInt("op_tp_bord", opacityTpBorder)
                    .putInt("op_tp_cent", opacityTpCenter)
                    .putInt("kbd_w", kbdWidthPct)
                    .putInt("kbd_h", kbdHeightDp)
                    .putInt("kbd_layout", kbdLayoutIdx)
                    .putFloat("kbd_x", kbdPosX)
                    .putInt("kbd_off_y", kbdOffsetYDp)
                    .putBoolean("kbd_haptics", kbdHaptics)
                    .putBoolean("kbd_game_keys", kbdGameKeys)
                    .putFloat("scroll_speed", scrollSpeed)
                    .putBoolean("scroll_invert", invertScroll)
                    .putInt("op_tp_zone", opacityTpZone)
                    .putInt("col_tp_zone", colTpZone)
                    .putInt("col_gear", colGear)
                    .putInt("col_arrow", colArrow)
                    .putInt("col_menu", colMenu)
                    .putInt("col_kbd", colKbdText)
                    .putInt("col_tp_bord", colTpBorder)
                    .putFloat("gear_x", gearPosX)
                    .putFloat("gear_y", gearPosY)
                    .apply();
        } catch (Exception ignored) {}
    }

    // -----------------------------------------------------------------------
    // ДЕКОДИРОВАНИЕ ВИДЕО (MediaCodec + SurfaceView)
    // -----------------------------------------------------------------------
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

        this.videoHeight = (targetHeight > 0) ? targetHeight : 1080;
        this.videoWidth = (int) Math.round(this.videoHeight * (16.0 / 9.0));
        updateSubtitle();
        inputClient.configure(this.serverUrl, this.authToken);
    }

    private void updateSubtitle() {
        if (subtitleView == null) return;
        String resStr = (targetHeight > 0) ? (targetHeight + "p") : "Native";
        subtitleView.setText(resStr + " · " + targetFps + " FPS · " + (scaleMode == SCALE_MODE_FIT ? "Fit" : "Fill"));
    }

    public void startStream() {
        if (isStreaming.get()) return;
        isStreaming.set(true);
        hidePlaybackError();
        setVisibility(View.VISIBLE);
        acquireStreamWifiLock();

        applyOperatingModeUI();
        if (operatingMode == MODE_VIEW) {
            setControlsVisible(true, false);
            scheduleControlsAutoHide();
        }

        // Поток ввода открывается только в режиме «Управление ПК»; «Демонстрация экрана» — только просмотр
        if (operatingMode == MODE_PC_CONTROL) {
            inputClient.start();
        }
        applyTouchpadConfig();
        updateTouchpadZoneVisibility();

        if (isAudioEnabled) {
            startAudioStream();
        } else {
            updateAudioStatusOnMain("Выключен", PcUi.SUBTEXT);
        }

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

        stopAudioStream();
        stopMicStreaming();

        // Отпускаем всё на телефоне, затем клиент шлёт RELEASE_ALL + END и закрывает поток;
        // даже при обрыве сервер сам отпустит клавиши/кнопки по разрыву соединения или сторожевому таймеру.
        releaseLocalInputState(true);
        inputClient.stop();

        synchronized (surfaceLock) {
            surfaceLock.notifyAll();
        }

        HttpURLConnection conn = activeConn;
        if (conn != null) {
            try { conn.disconnect(); } catch (Exception ignored) {}
            activeConn = null;
        }

        Thread wt = workerThread;
        if (wt != null) {
            wt.interrupt();
            try { wt.join(600); } catch (InterruptedException ignored) {}
            workerThread = null;
        }

        releaseDecoder();
        releaseStreamWifiLock();
        // Окно выходит из полноэкранного режима вместе с плеером (MainActivity) — сбрасываем флаг,
        // иначе в следующем сеансе кнопка показывала бы неверное состояние.
        if (isFullscreen) {
            isFullscreen = false;
            post(new Runnable() {
                @Override
                public void run() {
                    if (fullscreenBtn != null) fullscreenBtn.setIcon(PcIcons.FULLSCREEN);
                    if (floatingFsBtn != null) floatingFsBtn.setIcon(PcIcons.FULLSCREEN);
                    updateQuickActionStates();
                }
            });
        }

        post(new Runnable() {
            @Override
            public void run() {
                setDiagnosticsVisible(false);
                if (isSplitSettingsOpen) closeSplitSettingsWithAnimation();
                hidePlaybackError();
                setVisibility(View.GONE);
            }
        });
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        stopStream();
    }

    @SuppressWarnings("deprecation")
    private void acquireStreamWifiLock() {
        try {
            if (streamWifiLock == null) {
                android.net.wifi.WifiManager wm = (android.net.wifi.WifiManager)
                        getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                if (wm == null) return;
                int mode = Build.VERSION.SDK_INT >= 29
                        ? android.net.wifi.WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                        : android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF;
                streamWifiLock = wm.createWifiLock(mode, "PCControl::PlayerLowLatency");
                streamWifiLock.setReferenceCounted(false);
            }
            if (!streamWifiLock.isHeld()) streamWifiLock.acquire();
        } catch (Exception ignored) {}
    }

    private void releaseStreamWifiLock() {
        try {
            if (streamWifiLock != null && streamWifiLock.isHeld()) streamWifiLock.release();
        } catch (Exception ignored) {}
    }

    private void closeStreamAndExit() {
        stopStream();
        if (playerCallback != null) {
            playerCallback.onCloseRequested();
        }
    }

    public boolean handleBackPressed() {
        if (isErrorVisible) {
            hidePlaybackError();
            closeStreamAndExit();
            return true;
        }
        if (isKeyboardVisible) {
            showCustomKeyboard(false);
            return true;
        }
        if (isQuickDrawerOpen) {
            toggleQuickDrawer();
            return true;
        }
        if (isSplitSettingsOpen) {
            closeSplitSettingsWithAnimation();
            return true;
        }
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

    public void toggleScaleMode() {
        scaleMode = (scaleMode == SCALE_MODE_FIT) ? SCALE_MODE_FILL : SCALE_MODE_FIT;
        if (scaleModeBtn != null) {
            scaleModeBtn.setText(scaleMode == SCALE_MODE_FIT ? "Fit" : "Fill");
        }
        updateSubtitle();
        savePreferences();
        requestLayout();
    }

    public void toggleFullscreen() {
        isFullscreen = !isFullscreen;
        if (fullscreenBtn != null) {
            fullscreenBtn.setIcon(isFullscreen ? PcIcons.FULLSCREEN_EXIT : PcIcons.FULLSCREEN);
        }
        if (floatingFsBtn != null) {
            floatingFsBtn.setIcon(isFullscreen ? PcIcons.FULLSCREEN_EXIT : PcIcons.FULLSCREEN);
            floatingFsBtn.setContentDescription(isFullscreen ? "Выйти из полноэкранного режима" : "Полноэкранный режим");
        }
        updateQuickActionStates();
        // Системные панели и вырез камеры меняются после перехода — пересчитываем раскладку,
        // чтобы шестерёнка, меню и клавиатура остались в доступной области экрана.
        post(new Runnable() {
            @Override public void run() { requestLayout(); }
        });
        if (playerCallback != null) {
            playerCallback.onFullscreenToggled(isFullscreen);
        }
        requestLayout();
    }

    public void setPlayerCallback(PlayerCallback callback) {
        this.playerCallback = callback;
    }

    private void setControlsVisible(boolean visible, boolean animate) {
        if (isControlsVisible == visible || topToolbar == null) return;
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
        if (isDiagVisible || isErrorVisible) return;
        // При включённой мыши касания уходят на ПК, поэтому панель с кнопками 🖱/⌨ не прячем
        if (operatingMode == MODE_VIEW && isViewMouseEnabled) return;
        mainHandler.postDelayed(hideControlsRunnable, 5000);
    }

    private void applyVideoSettings(final int newMon, final int newH, final int newFps, final int newBr) {
        if (targetMonitor == newMon && targetHeight == newH && targetFps == newFps && targetBitrate == newBr) return;
        targetMonitor = newMon;
        targetHeight = newH;
        targetFps = newFps;
        targetBitrate = newBr;
        savePreferences();
        updateSubtitle();

        if (playerCallback != null) {
            playerCallback.onSettingsChanged(newMon, newH, newFps, newBr);
        }

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    URL u = new URL(serverUrl + "/screen/config");
                    HttpURLConnection c = (HttpURLConnection) u.openConnection();
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json");
                    if (!authToken.isEmpty()) c.setRequestProperty("X-Auth-Token", authToken);
                    String body = "{\"monitor\":" + newMon + ",\"height\":" + newH + ",\"fps\":" + newFps + ",\"bitrate\":" + newBr + "}";
                    c.getOutputStream().write(body.getBytes(StandardCharsets.UTF_8));
                    c.getResponseCode();
                    c.disconnect();
                } catch (Exception ignored) {}

                // Мягкий перезапуск видеопотока
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        HttpURLConnection conn = activeConn;
                        if (conn != null) {
                            try { conn.disconnect(); } catch (Exception ignored) {}
                        }
                    }
                });
            }
        }).start();
    }

    // -----------------------------------------------------------------------
    // WORKER ПОТОК ПРИЕМА H.264 СТРИМА
    // -----------------------------------------------------------------------
    private void runStreamWorker() {
        byte[] magic = new byte[4];
        byte[] header13 = new byte[13];
        byte[] frameBuf = new byte[512 * 1024];

        while (isStreaming.get() && !Thread.currentThread().isInterrupted()) {
            synchronized (surfaceLock) {
                while (!surfaceReady && isStreaming.get()) {
                    try { surfaceLock.wait(200); } catch (InterruptedException e) { return; }
                }
            }
            if (!isStreaming.get()) break;

            HttpURLConnection conn = null;
            InputStream in = null;
            try {
                String streamUrl = serverUrl + "/screen/h264_stream?format=framed"
                        + "&monitor=" + targetMonitor
                        + "&height=" + targetHeight
                        + "&fps=" + targetFps
                        + "&bitrate=" + targetBitrate
                        + "&token=" + URLEncoder.encode(authToken, "UTF-8");

                URL u = new URL(streamUrl);
                conn = (HttpURLConnection) u.openConnection();
                conn.setConnectTimeout(4000);
                conn.setReadTimeout(12000);
                conn.setRequestProperty("Accept", "video/x-h264");
                conn.setRequestProperty("Cache-Control", "no-cache");
                conn.setRequestProperty("Connection", "keep-alive");
                if (!authToken.isEmpty()) conn.setRequestProperty("X-Auth-Token", authToken);

                activeConn = conn;
                int respCode = conn.getResponseCode();
                if (respCode != 200) throw new Exception("HTTP " + respCode);

                in = new BufferedInputStream(conn.getInputStream(), 128 * 1024);
                initDecoder();

                lastBitrateSampleTime = SystemClock.elapsedRealtime();
                lastBitrateBytes = 0;

                while (isStreaming.get() && !Thread.currentThread().isInterrupted()) {
                    readFully(in, magic, 0, 4);
                    if (magic[0] != 'P' || magic[1] != 'C' || magic[2] != '0' || magic[3] != '1') {
                        throw new Exception("Bad magic");
                    }
                    readFully(in, header13, 0, 13);
                    int payloadLen = ((header13[0] & 0xFF) << 24)
                            | ((header13[1] & 0xFF) << 16)
                            | ((header13[2] & 0xFF) << 8)
                            | (header13[3] & 0xFF);
                    int flags = header13[4] & 0xFF;
                    long ptsUs = ((long) (header13[5] & 0xFF) << 56)
                            | ((long) (header13[6] & 0xFF) << 48)
                            | ((long) (header13[7] & 0xFF) << 40)
                            | ((long) (header13[8] & 0xFF) << 32)
                            | ((long) (header13[9] & 0xFF) << 24)
                            | ((long) (header13[10] & 0xFF) << 16)
                            | ((long) (header13[11] & 0xFF) << 8)
                            | ((long) (header13[12] & 0xFF));

                    if (payloadLen <= 0 || payloadLen > 10 * 1024 * 1024) throw new Exception("Invalid length");
                    if (frameBuf.length < payloadLen) frameBuf = new byte[payloadLen + 64 * 1024];

                    readFully(in, frameBuf, 0, payloadLen);
                    totalBytesReceived += (payloadLen + 17);
                    receivedFpsTracker.recordEvent();

                    if (!surfaceReady || decoder == null) throw new Exception("Surface lost");
                    feedDecoder(frameBuf, payloadLen, flags, ptsUs);
                }
            } catch (Exception e) {
                if (isStreaming.get()) {
                    try { Thread.sleep(600); } catch (InterruptedException ignored) { break; }
                }
            } finally {
                if (in != null) { try { in.close(); } catch (Exception ignored) {} }
                if (conn != null) { try { conn.disconnect(); } catch (Exception ignored) {} }
                activeConn = null;
            }
        }
        releaseDecoder();
    }

    private void readFully(InputStream in, byte[] b, int off, int len) throws Exception {
        int n = 0;
        while (n < len) {
            int count = in.read(b, off + n, len - n);
            if (count < 0) throw new EOFException("Stream closed");
            n += count;
        }
    }

    private void initDecoder() throws Exception {
        synchronized (decoderLock) {
            releaseDecoder();
            MediaCodec codec = MediaCodec.createDecoderByType("video/avc");
            try {
                codec.configure(buildDecoderFormat(codec, true), surfaceHolder.getSurface(), null, 0);
            } catch (Exception lowLatencyRejected) {
                // Некоторые декодеры не принимают ключи низкой задержки — повтор с обычным форматом
                try { codec.release(); } catch (Exception ignored) {}
                codec = MediaCodec.createDecoderByType("video/avc");
                codec.configure(buildDecoderFormat(codec, false), surfaceHolder.getSurface(), null, 0);
            }
            codec.setVideoScalingMode(MediaCodec.VIDEO_SCALING_MODE_SCALE_TO_FIT);
            codec.start();
            decoder = codec;
            startDecoderOutputThread(codec);
        }
    }

    /** Формат декодера; lowLatency — режим низкой задержки (как в Moonlight): FEATURE_LowLatency, Qualcomm. */
    private MediaFormat buildDecoderFormat(MediaCodec codec, boolean lowLatency) {
        MediaFormat format = MediaFormat.createVideoFormat("video/avc", videoWidth, videoHeight);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            format.setInteger(MediaFormat.KEY_OPERATING_RATE, Short.MAX_VALUE);
            format.setInteger(MediaFormat.KEY_PRIORITY, 0);
        }
        if (lowLatency) {
            if (Build.VERSION.SDK_INT >= 30) {
                try {
                    if (codec.getCodecInfo().getCapabilitiesForType("video/avc")
                            .isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency)) {
                        format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
                    }
                } catch (Exception ignored) {}
            }
            try {
                String name = codec.getName().toLowerCase(java.util.Locale.US);
                if (name.startsWith("omx.qcom") || name.startsWith("c2.qti")) {
                    format.setInteger("vendor.qti-ext-dec-low-latency.enable", 1);
                }
            } catch (Exception ignored) {}
        }
        return format;
    }

    /**
     * Отдельный поток вывода: кадр показывается сразу после декодирования. Раньше выход
     * декодера опрашивался только после прихода следующего кадра из сети (+1 кадр задержки
     * и рывки при неравномерной доставке). Если готово несколько кадров — показывается
     * только самый новый, отставание не накапливается.
     */
    private void startDecoderOutputThread(final MediaCodec codec) {
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
                while (isStreaming.get() && decoder == codec) {
                    int idx;
                    try {
                        idx = codec.dequeueOutputBuffer(info, 8000);
                        if (idx >= 0) {
                            int next;
                            while ((next = codec.dequeueOutputBuffer(info, 0)) >= 0) {
                                codec.releaseOutputBuffer(idx, false); // устаревший кадр
                                droppedFramesCount++;
                                idx = next;
                            }
                            codec.releaseOutputBuffer(idx, true);
                            renderedFpsTracker.recordEvent();
                            minFpsTracker.recordEvent();
                            if (next == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) onDecoderFormatChanged(codec);
                        } else if (idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                            onDecoderFormatChanged(codec);
                        }
                    } catch (Exception e) {
                        break; // декодер остановлен/освобождён
                    }
                }
            }
        }, "pc-video-render");
        t.setPriority(Thread.MAX_PRIORITY - 1);
        t.setDaemon(true);
        decoderOutputThread = t;
        t.start();
    }

    private void onDecoderFormatChanged(MediaCodec codec) {
        MediaFormat f = codec.getOutputFormat();
        if (f.containsKey(MediaFormat.KEY_WIDTH) && f.containsKey(MediaFormat.KEY_HEIGHT)) {
            videoWidth = f.getInteger(MediaFormat.KEY_WIDTH);
            videoHeight = f.getInteger(MediaFormat.KEY_HEIGHT);
            post(new Runnable() {
                @Override public void run() { requestLayout(); }
            });
        }
    }

    private void releaseDecoder() {
        MediaCodec codec;
        Thread out;
        synchronized (decoderLock) {
            codec = decoder;
            decoder = null;
            out = decoderOutputThread;
            decoderOutputThread = null;
        }
        if (out != null && out != Thread.currentThread()) {
            // Сначала дождаться выхода потока вывода (он ждёт не дольше 8 мс), потом stop/release
            boolean wasInterrupted = Thread.interrupted();
            try {
                out.join(300);
            } catch (InterruptedException ignored) {
            }
            if (wasInterrupted) Thread.currentThread().interrupt();
        }
        if (codec != null) {
            try { codec.stop(); } catch (Exception ignored) {}
            try { codec.release(); } catch (Exception ignored) {}
        }
    }

    private void feedDecoder(byte[] data, int length, int flags, long ptsUs) {
        synchronized (decoderLock) {
            if (decoder == null) return;
            try {
                // Ждём свободный буфер дольше (30 мс): потерянный P-кадр портит картинку до следующего I-кадра
                int inIdx = decoder.dequeueInputBuffer(30000);
                if (inIdx >= 0) {
                    ByteBuffer inBuf = (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP)
                            ? decoder.getInputBuffer(inIdx)
                            : decoder.getInputBuffers()[inIdx];
                    if (inBuf != null) {
                        inBuf.clear();
                        inBuf.put(data, 0, length);
                        int bufFlags = 0;
                        if ((flags & 0x02) != 0) bufFlags |= MediaCodec.BUFFER_FLAG_CODEC_CONFIG;
                        if ((flags & 0x01) != 0) bufFlags |= MediaCodec.BUFFER_FLAG_KEY_FRAME;
                        decoder.queueInputBuffer(inIdx, 0, length, ptsUs, bufFlags);
                        decodedFpsTracker.recordEvent();
                    }
                }
            } catch (Exception ignored) {}
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
        }
        // Сворачивание приложения/выключение экрана: декодер должен отпустить поверхность до её
        // уничтожения. Раньше он оставался привязан к мёртвой Surface, ошибки глушились, и после
        // возврата в приложение экран оставался чёрным. Обрываем соединение — рабочий поток
        // дождётся новой поверхности и переподключится с новым декодером.
        releaseDecoder();
        HttpURLConnection conn = activeConn;
        if (conn != null) {
            try { conn.disconnect(); } catch (Exception ignored) {}
        }
    }

    // -----------------------------------------------------------------------
    // ПОСТРОЕНИЕ ТУЛБАРА, ДИАГНОСТИКИ И ОШИБОК
    // -----------------------------------------------------------------------
    private void buildTopToolbar(Context context) {
        topToolbar = new LinearLayout(context);
        topToolbar.setOrientation(LinearLayout.HORIZONTAL);
        topToolbar.setGravity(Gravity.CENTER_VERTICAL);
        // Плавающая «пилюля» в цветах приложения: #121212, рамка rgba(255,255,255,.13)
        topToolbar.setBackground(PcUi.shape(PcUi.FLOAT_BG, dpToPx(26), PcUi.BORDER_STRONG, dpToPx(1)));

        int padH = dpToPx(8);
        int padV = dpToPx(6);
        topToolbar.setPadding(padH, padV, padH, padV);

        FrameLayout.LayoutParams tbParams = new FrameLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        tbParams.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        tbParams.topMargin = dpToPx(16);
        topToolbar.setLayoutParams(tbParams);

        PcUi.IconBtn backBtn = new PcUi.IconBtn(context, PcIcons.ARROW_BACK, 40, 20, false, "Назад");
        backBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeStreamAndExit(); }
        });
        topToolbar.addView(backBtn);

        LinearLayout titleBox = new LinearLayout(context);
        titleBox.setOrientation(LinearLayout.VERTICAL);
        titleBox.setPadding(dpToPx(12), 0, dpToPx(12), 0);
        titleBox.setGravity(Gravity.CENTER_VERTICAL);

        titleView = PcUi.text(context, "Демонстрация экрана", 15f, PcUi.TEXT, Typeface.DEFAULT_BOLD);
        titleBox.addView(titleView);

        subtitleView = PcUi.text(context, "1080p · 60 FPS", 11f, PcUi.SUBTEXT, null);
        subtitleView.setPadding(0, dpToPx(3), 0, 0);
        titleBox.addView(subtitleView);
        // На узком экране сжимается заголовок (с многоточием), а не кнопки справа
        titleView.setSingleLine(true);
        titleView.setEllipsize(TextUtils.TruncateAt.END);
        subtitleView.setSingleLine(true);
        subtitleView.setEllipsize(TextUtils.TruncateAt.END);
        topToolbar.addView(titleBox, new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT, 1f));

        scaleModeBtn = PcUi.text(context, scaleMode == SCALE_MODE_FIT ? "Fit" : "Fill", 13f, PcUi.TEXT, PcUi.medium());
        scaleModeBtn.setGravity(Gravity.CENTER);
        scaleModeBtn.setMinWidth(dpToPx(48));
        scaleModeBtn.setMinHeight(dpToPx(40));
        scaleModeBtn.setPadding(dpToPx(10), 0, dpToPx(10), 0);
        scaleModeBtn.setBackground(PcUi.shape(PcUi.SURFACE2, dpToPx(12), PcUi.BORDER, dpToPx(1)));
        scaleModeBtn.setContentDescription("Масштаб: вписать / заполнить");
        PcUi.pressable(scaleModeBtn);
        scaleModeBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleScaleMode(); }
        });
        topToolbar.addView(scaleModeBtn);

        // Мыши и клавиатуры здесь нет: «Демонстрация экрана» — только просмотр,
        // управление ПК — отдельный режим «Управление ПК».
        addToolbarSpacer(context, topToolbar, 6);

        fullscreenBtn = new PcUi.IconBtn(context, PcIcons.FULLSCREEN, 40, 20, false, "Полноэкранный режим");
        fullscreenBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleFullscreen(); }
        });
        topToolbar.addView(fullscreenBtn);

        addToolbarSpacer(context, topToolbar, 6);

        settingsBtn = new PcUi.IconBtn(context, PcIcons.GEAR, 40, 20, false, "Настройки");
        settingsBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleSplitSettings(); }
        });
        topToolbar.addView(settingsBtn);

        addToolbarSpacer(context, topToolbar, 6);

        closeBtn = new PcUi.IconBtn(context, PcIcons.CLOSE, 40, 18, false, "Закрыть трансляцию");
        closeBtn.setState(PcUi.ST_DANGER);
        closeBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeStreamAndExit(); }
        });
        topToolbar.addView(closeBtn);

        addView(topToolbar);
    }

    private void addToolbarSpacer(Context context, LinearLayout parent, int dp) {
        View sp = new View(context);
        parent.addView(sp, new LinearLayout.LayoutParams(dpToPx(dp), 1));
    }

    private void buildDiagnosticsDialog(Context context) {
        diagOverlay = new FrameLayout(context);
        diagOverlay.setBackgroundColor(0xC2000000);
        diagOverlay.setVisibility(View.GONE);
        diagOverlay.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { setDiagnosticsVisible(false); }
        });

        diagCard = new LinearLayout(context);
        diagCard.setOrientation(LinearLayout.VERTICAL);
        diagCard.setBackground(PcUi.shape(PcUi.SURFACE, dpToPx(22), PcUi.BORDER_STRONG, dpToPx(1)));
        int pad = dpToPx(18);
        diagCard.setPadding(pad, pad, pad, pad);
        diagCard.setClickable(true);

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dpToPx(340), LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        diagCard.setLayoutParams(lp);

        LinearLayout head = new LinearLayout(context);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        android.widget.ImageView tile = new android.widget.ImageView(context);
        tile.setImageDrawable(new PcIconDrawable(PcIcons.CHART, PcUi.RED, dpToPx(16)));
        tile.setScaleType(android.widget.ImageView.ScaleType.CENTER);
        tile.setBackground(PcUi.shape(PcUi.RED_SOFT, dpToPx(8), 0, 0));
        head.addView(tile, new LinearLayout.LayoutParams(dpToPx(28), dpToPx(28)));
        TextView title = PcUi.text(context, "Диагностика потока", 16f, PcUi.TEXT, Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f);
        tlp.leftMargin = dpToPx(10);
        head.addView(title, tlp);
        PcUi.IconBtn closeX = new PcUi.IconBtn(context, PcIcons.CLOSE, 30, 16, true, "Закрыть");
        closeX.setBackground(PcUi.oval(0x14FFFFFF, 0, 0));
        closeX.icon.setColor(0x99FFFFFF);
        closeX.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { setDiagnosticsVisible(false); }
        });
        head.addView(closeX);
        diagCard.addView(head);

        LinearLayout rows = new LinearLayout(context);
        rows.setOrientation(LinearLayout.VERTICAL);
        rows.setPadding(0, dpToPx(10), 0, 0);
        diagCard.addView(rows);
        diagFpsRendVal = addDiagRow(context, rows, "FPS отрисовки");
        diagFpsRecvVal = addDiagRow(context, rows, "FPS приёма");
        diagBitrateVal = addDiagRow(context, rows, "Битрейт");
        diagResVal = addDiagRow(context, rows, "Разрешение");
        diagLatencyVal = addDiagRow(context, rows, "Ввод (мышь/клавиатура)");

        diagOverlay.addView(diagCard);
        addView(diagOverlay, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    private TextView addDiagRow(Context context, LinearLayout parent, String label) {
        LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dpToPx(2), dpToPx(9), dpToPx(2), dpToPx(9));
        TextView l = PcUi.text(context, label, 12.5f, PcUi.SUBTEXT, PcUi.medium());
        TextView v = PcUi.text(context, "—", 12.5f, PcUi.TEXT, Typeface.MONOSPACE);
        row.addView(l, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        row.addView(v);
        parent.addView(row);
        View d = new View(context);
        d.setBackgroundColor(PcUi.BORDER);
        parent.addView(d, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, Math.max(1, dpToPx(1))));
        return v;
    }

    private long diagLastBytes = 0;
    private long diagLastTime = 0;

    private void refreshDiagValues() {
        if (diagFpsRendVal != null) diagFpsRendVal.setText(String.format(java.util.Locale.US, "%.1f", renderedFpsTracker.getFps()));
        if (diagFpsRecvVal != null) diagFpsRecvVal.setText(String.format(java.util.Locale.US, "%.1f", receivedFpsTracker.getFps()));
        if (diagResVal != null) diagResVal.setText(videoWidth + "×" + videoHeight);
        long now = SystemClock.elapsedRealtime();
        long bytes = totalBytesReceived;
        if (diagBitrateVal != null && diagLastTime > 0 && now > diagLastTime) {
            float mbps = (bytes - diagLastBytes) * 8f / ((now - diagLastTime) * 1000f);
            diagBitrateVal.setText(String.format(java.util.Locale.US, "%.1f Мбит/с", Math.max(0f, mbps)));
        }
        diagLastBytes = bytes;
        diagLastTime = now;
        if (diagLatencyVal != null) {
            String st;
            switch (inputClient.getState()) {
                case PcInputClient.STATE_CONNECTED: st = "поток · " + inputClient.framesSent + " событий"; break;
                case PcInputClient.STATE_CONNECTING: st = "подключение…"; break;
                case PcInputClient.STATE_LEGACY: st = "медленный режим (старый сервер)"; break;
                case PcInputClient.STATE_AUTH_ERROR: st = "ошибка пароля"; break;
                case PcInputClient.STATE_ERROR: st = "нет связи"; break;
                default: st = "выключен"; break;
            }
            diagLatencyVal.setText(st);
        }
    }

    public void setDiagnosticsVisible(boolean visible) {
        isDiagVisible = visible;
        if (diagOverlay != null) {
            diagOverlay.animate().cancel();
            if (visible) {
                diagOverlay.setVisibility(View.VISIBLE);
                diagOverlay.setAlpha(0f);
                diagOverlay.animate().alpha(1f).setDuration(180).setListener(null).start();
            } else {
                diagOverlay.setVisibility(View.GONE);
            }
        }
        if (visible) {
            diagLastTime = 0;
            mainHandler.post(diagUpdateRunnable);
        } else {
            mainHandler.removeCallbacks(diagUpdateRunnable);
        }
    }

    private void buildErrorDialog(Context context) {
        errorOverlay = new FrameLayout(context);
        errorOverlay.setBackgroundColor(0xC2000000);
        errorOverlay.setVisibility(View.GONE);
        addView(errorOverlay, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    private void hidePlaybackError() {
        isErrorVisible = false;
        if (errorOverlay != null) errorOverlay.setVisibility(View.GONE);
    }

    // -----------------------------------------------------------------------
    // ИЗМЕРЕНИЕ И РАСПОЛОЖЕНИЕ ЭЛЕМЕНТОВ (onMeasure, onLayout)
    // -----------------------------------------------------------------------
    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int widthSize = MeasureSpec.getSize(widthMeasureSpec);
        int heightSize = MeasureSpec.getSize(heightMeasureSpec);
        if (widthSize <= 0 || heightSize <= 0) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec);
            return;
        }

        // Расчёт пропорций видео 16:9
        float videoAspect = (videoWidth > 0 && videoHeight > 0) ? (videoWidth / (float) videoHeight) : (16.0f / 9.0f);
        int surfW = widthSize;
        int surfH = heightSize;

        if (scaleMode == SCALE_MODE_FIT) {
            float containerAspect = widthSize / (float) heightSize;
            if (containerAspect > videoAspect) {
                surfH = heightSize;
                surfW = Math.round(heightSize * videoAspect);
            } else {
                surfW = widthSize;
                surfH = Math.round(widthSize / videoAspect);
            }
        }

        if (videoContainer != null) {
            videoContainer.measure(MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY));
        }

        if (surfaceView != null) {
            surfaceView.measure(MeasureSpec.makeMeasureSpec(surfW, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(surfH, MeasureSpec.EXACTLY));
        }

        if (topToolbar != null && topToolbar.getVisibility() != View.GONE) {
            topToolbar.measure(MeasureSpec.makeMeasureSpec(widthSize - dpToPx(32), MeasureSpec.AT_MOST),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.AT_MOST));
        }

        if (floatingControlsGroup != null && floatingControlsGroup.getVisibility() != View.GONE) {
            floatingControlsGroup.measure(MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.AT_MOST),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.AT_MOST));
        }

        if (splitSettingsContainer != null && splitSettingsContainer.getVisibility() != View.GONE) {
            int panelW = isSplitSettingsOpen ? (int) (widthSize * 0.48f) : widthSize;
            splitSettingsContainer.measure(MeasureSpec.makeMeasureSpec(panelW, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY));
        }

        if (keyboardPanel != null && keyboardPanel.getVisibility() != View.GONE) {
            int kWidth = (int) (widthSize * (kbdWidthPct / 100f));
            int kHeight = Math.min(heightSize, dpToPx(kbdHeightDp) + dpToPx(20));
            keyboardPanel.measure(MeasureSpec.makeMeasureSpec(kWidth, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(kHeight, MeasureSpec.EXACTLY));
        }
        if (touchpadZoneView != null) {
            touchpadZoneView.measure(MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY));
        }

        if (diagOverlay != null && diagOverlay.getVisibility() != View.GONE) {
            diagOverlay.measure(MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY));
        }
        if (errorOverlay != null && errorOverlay.getVisibility() != View.GONE) {
            errorOverlay.measure(MeasureSpec.makeMeasureSpec(widthSize, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(heightSize, MeasureSpec.EXACTLY));
        }

        setMeasuredDimension(widthSize, heightSize);
    }

    @Override
    protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        int parentW = right - left;
        int parentH = bottom - top;

        if (videoContainer != null) {
            videoContainer.layout(0, 0, parentW, parentH);
        }

        if (surfaceView != null) {
            int sW = surfaceView.getMeasuredWidth();
            int sH = surfaceView.getMeasuredHeight();
            int sLeft = (parentW - sW) / 2;
            int sTop = (parentH - sH) / 2;
            surfaceView.layout(sLeft, sTop, sLeft + sW, sTop + sH);
            videoViewportRect.set(sLeft, sTop, sLeft + sW, sTop + sH);
        }

        if (touchpadVisualEditor != null && touchpadVisualEditor.getVisibility() != View.GONE) {
            touchpadVisualEditor.layout(0, 0, parentW, parentH);
        }

        if (topToolbar != null && topToolbar.getVisibility() != View.GONE) {
            int tbW = topToolbar.getMeasuredWidth();
            int tbH = topToolbar.getMeasuredHeight();
            int tbLeft = Math.max(dpToPx(16), (parentW - tbW) / 2);
            topToolbar.layout(tbLeft, dpToPx(16), tbLeft + tbW, dpToPx(16) + tbH);
        }

        if (floatingControlsGroup != null && floatingControlsGroup.getVisibility() != View.GONE) {
            int gW = floatingControlsGroup.getMeasuredWidth();
            int gH = floatingControlsGroup.getMeasuredHeight();
            Rect safe = getSafeInsets();
            int minX = safe.left + dpToPx(8);
            int maxRight = parentW - safe.right - dpToPx(8);
            int minY = safe.top + dpToPx(8);
            int maxBottom = parentH - safe.bottom - dpToPx(8);
            // Позиция хранится по ПРАВОМУ краю: меню выдвигается влево, шестерёнка остаётся на месте.
            // По умолчанию — правый верхний угол (с учётом выреза камеры и системных панелей).
            float gRight = (gearPosX >= 0) ? gearPosX : (parentW - safe.right - dpToPx(16));
            gRight = Math.max(minX + gW, Math.min(maxRight, gRight));
            float gTop = (gearPosY >= 0) ? gearPosY : (safe.top + dpToPx(16));
            gTop = Math.max(minY, Math.min(maxBottom - gH, gTop));
            floatingControlsGroup.layout((int) (gRight - gW), (int) gTop, (int) gRight, (int) (gTop + gH));
        }

        if (splitSettingsContainer != null && splitSettingsContainer.getVisibility() != View.GONE) {
            int sW = splitSettingsContainer.getMeasuredWidth();
            int sH = splitSettingsContainer.getMeasuredHeight();
            // Панель настроек располагается СЛЕВА
            splitSettingsContainer.layout(0, 0, sW, sH);
        }

        if (keyboardPanel != null && keyboardPanel.getVisibility() != View.GONE) {
            int kW = keyboardPanel.getMeasuredWidth();
            int kH = keyboardPanel.getMeasuredHeight();
            int kLeft = Math.round(kbdPosX * parentW - kW / 2f);
            Rect ks = getSafeInsets();
            int kMin = (kW <= parentW - ks.left - ks.right) ? ks.left : 0;
            int kMax = (kW <= parentW - ks.left - ks.right) ? parentW - ks.right - kW : parentW - kW;
            kLeft = Math.max(kMin, Math.min(kMax, kLeft));
            int kBottom = parentH - dpToPx(kbdOffsetYDp);
            kBottom = Math.max(kH, Math.min(parentH, kBottom));
            keyboardPanel.layout(kLeft, kBottom - kH, kLeft + kW, kBottom);
        }

        if (diagOverlay != null && diagOverlay.getVisibility() != View.GONE) {
            diagOverlay.layout(0, 0, parentW, parentH);
        }
        if (errorOverlay != null && errorOverlay.getVisibility() != View.GONE) {
            errorOverlay.layout(0, 0, parentW, parentH);
        }
    }

    private final Rect safeInsets = new Rect();

    /**
     * Безопасная область в полноэкранном режиме: окно рисуется под вырезом камеры
     * (LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES), поэтому кнопки и клавиатуру отодвигаем от выреза.
     * Вне полноэкранного режима окно и так не заходит под вырез и системные панели.
     */
    private Rect getSafeInsets() {
        safeInsets.set(0, 0, 0, 0);
        if (isFullscreen && Build.VERSION.SDK_INT >= 28) {
            try {
                android.view.WindowInsets wi = getRootWindowInsets();
                android.view.DisplayCutout dc = wi != null ? wi.getDisplayCutout() : null;
                if (dc != null) {
                    safeInsets.set(dc.getSafeInsetLeft(), dc.getSafeInsetTop(), dc.getSafeInsetRight(), dc.getSafeInsetBottom());
                }
            } catch (Exception ignored) {}
        }
        return safeInsets;
    }

    @Override
    public android.view.WindowInsets onApplyWindowInsets(android.view.WindowInsets insets) {
        requestLayout();
        return super.onApplyWindowInsets(insets);
    }

    private int dpToPx(int dp) {
        DisplayMetrics dm = getResources().getDisplayMetrics();
        return Math.round(dp * dm.density);
    }

    // -----------------------------------------------------------------------
    // ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ ТРЕКИНГА FPS
    // -----------------------------------------------------------------------
    private static class FpsTracker {
        private final long[] timestamps;
        private final long windowMs;
        private int head = 0;
        private int count = 0;

        public FpsTracker(int capacity, long windowMs) {
            this.timestamps = new long[capacity];
            this.windowMs = windowMs;
        }

        public synchronized void recordEvent() {
            long now = SystemClock.uptimeMillis();
            timestamps[head] = now;
            head = (head + 1) % timestamps.length;
            if (count < timestamps.length) count++;
        }

        public synchronized float getFps() {
            if (count < 2) return 0f;
            long now = SystemClock.uptimeMillis();
            int validCount = 0;
            for (int i = 0; i < count; i++) {
                int idx = (head - 1 - i + timestamps.length) % timestamps.length;
                if (now - timestamps[idx] <= windowMs) {
                    validCount++;
                } else {
                    break;
                }
            }
            if (validCount < 2) return 0f;
            return (validCount * 1000f) / (float) windowMs;
        }
    }

    private static class MinFpsTracker {
        private final long windowMs;
        private long lastCheck = 0;
        private int frames = 0;
        private float minFps = 60f;

        public MinFpsTracker(long windowMs) {
            this.windowMs = windowMs;
        }

        public synchronized void recordEvent() {
            frames++;
            long now = SystemClock.uptimeMillis();
            if (lastCheck == 0) lastCheck = now;
            if (now - lastCheck >= 1000) {
                float fps = (frames * 1000f) / (float) (now - lastCheck);
                if (fps < minFps && fps > 5f) minFps = fps;
                frames = 0;
                lastCheck = now;
            }
        }

        public synchronized float getMinFps() {
            return minFps;
        }
    }
}
