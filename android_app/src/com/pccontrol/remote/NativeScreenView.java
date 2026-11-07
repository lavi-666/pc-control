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
    private TextView fullscreenBtn;
    private TextView settingsBtn;
    private TextView closeBtn;

    // Плавающие элементы управления (для MODE_PC_CONTROL)
    private FrameLayout floatingControlsGroup;
    private TextView floatingGearBtn;
    private TextView floatingArrowBtn;
    private LinearLayout quickActionsDrawer;
    private boolean isQuickDrawerOpen = false;

    // 4 быстрые кнопки
    private TextView quickBtnKeyboard;
    private TextView quickBtnMic;
    private TextView quickBtnSound;
    private TextView quickBtnTouchpad;

    private boolean isTouchpadEnabled = true;
    private boolean isKeyboardVisible = false;
    private boolean isMicStreaming = false;

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

    // Оверлей визуального редактирования тачпада прямо на экране
    private TouchpadVisualEditorView touchpadVisualEditor;
    private boolean isTouchpadEditing = false;

    // Собственная встроенная клавиатура PC Control
    private CustomKeyboardView customKeyboardView;
    private int kbdWidthPct = 100;
    private int kbdHeightDp = 220;
    private int kbdLayoutIdx = 0; // 0=EN, 1=RU, 2=UK, 3=SYM

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

    // Стандартные чипы настроек экрана
    private final List<TextView> monitorChips = new ArrayList<>();
    private final Map<Integer, TextView> resChips = new HashMap<>();
    private final Map<Integer, TextView> fpsChips = new HashMap<>();
    private final Map<Integer, TextView> bitrateChips = new HashMap<>();

    // Звук ПК (WASAPI Loopback)
    private boolean isAudioEnabled = true;
    private int audioVolume = 80;
    private boolean isAudioMuted = false;
    private volatile String audioStatus = "Выключен";
    private volatile int audioStatusColor = Color.parseColor("#94A3B8");
    private AudioPlayerThread audioThread = null;
    private final Object audioLock = new Object();

    // Микрофон телефона -> ПК
    private MicSenderThread micSenderThread = null;
    private final Object micLock = new Object();

    // Диспетчер ввода мыши (Coalescing input queue thread)
    private InputDispatcherThread inputDispatcherThread = null;

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
    private MediaCodec decoder;
    private final Object decoderLock = new Object();
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

    // Обработка жестов тачпада
    private float touchStartX = 0f;
    private float touchStartY = 0f;
    private float lastTouchX = 0f;
    private float lastTouchY = 0f;
    private long touchDownTime = 0;
    private long lastTapTime = 0;
    private boolean isDraggingMouse = false;
    private boolean isMouseLongPressed = false;
    private int activePointerCount = 1;

    private final Runnable longPressRunnable = new Runnable() {
        @Override
        public void run() {
            if (operatingMode == MODE_PC_CONTROL && isTouchpadEnabled && !isDraggingMouse) {
                isMouseLongPressed = true;
                if (inputDispatcherThread != null) {
                    inputDispatcherThread.enqueueMouseDown("left");
                }
            }
        }
    };

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

        // Запуск неблокирующего диспетчера команд мыши
        inputDispatcherThread = new InputDispatcherThread();
        inputDispatcherThread.start();

        // 1. Контейнер для масштабирования видео при сплит-экране настроек
        videoContainer = new FrameLayout(context);
        surfaceView = new SurfaceView(context);
        surfaceHolder = surfaceView.getHolder();
        surfaceHolder.addCallback(this);
        videoContainer.addView(surfaceView, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

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

        // Сенсорное управление
        surfaceView.setOnTouchListener(new OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                return handleTouchEvent(event);
            }
        });
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
        } else {
            if (floatingControlsGroup != null) floatingControlsGroup.setVisibility(View.GONE);
            if (quickActionsDrawer != null) quickActionsDrawer.setVisibility(View.GONE);
            if (customKeyboardView != null) customKeyboardView.setVisibility(View.GONE);
            if (topToolbar != null) topToolbar.setVisibility(View.VISIBLE);
            if (titleView != null) titleView.setText("Демонстрация экрана");
        }
        requestLayout();
    }

    // -----------------------------------------------------------------------
    // ПЛАВАЮЩИЕ КНОПКИ И ВЫДВИЖНОЕ МЕНЮ БЫСТРЫХ ФУНКЦИЙ (MODE_PC_CONTROL)
    // -----------------------------------------------------------------------
    private void buildFloatingControls(Context context) {
        floatingControlsGroup = new FrameLayout(context);
        floatingControlsGroup.setVisibility(View.GONE);

        // Кнопка-шестерёнка (⚙)
        floatingGearBtn = createCircularButton(context, "⚙", 48, "#EB121622", Color.WHITE, 18f);
        floatingGearBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleSplitSettings();
            }
        });

        // Поддержка перетаскивания шестерёнки пользователем
        floatingGearBtn.setOnTouchListener(new OnTouchListener() {
            private float startRawX, startRawY, initialX, initialY;
            private boolean isMoving = false;

            @Override
            public boolean onTouch(View v, MotionEvent ev) {
                switch (ev.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        startRawX = ev.getRawX();
                        startRawY = ev.getRawY();
                        initialX = floatingControlsGroup.getX();
                        initialY = floatingControlsGroup.getY();
                        isMoving = false;
                        return false;
                    case MotionEvent.ACTION_MOVE:
                        float dx = ev.getRawX() - startRawX;
                        float dy = ev.getRawY() - startRawY;
                        if (Math.abs(dx) > dpToPx(6) || Math.abs(dy) > dpToPx(6)) {
                            isMoving = true;
                            float newX = Math.max(dpToPx(8), Math.min(getWidth() - dpToPx(56), initialX + dx));
                            float newY = Math.max(dpToPx(8), Math.min(getHeight() - dpToPx(56), initialY + dy));
                            floatingControlsGroup.setX(newX);
                            floatingControlsGroup.setY(newY);
                            gearPosX = newX;
                            gearPosY = newY;
                        }
                        return isMoving;
                    case MotionEvent.ACTION_UP:
                        if (isMoving) {
                            savePreferences();
                            return true;
                        }
                        return false;
                }
                return false;
            }
        });

        // Кнопка-стрелочка (◀ / ▶)
        floatingArrowBtn = createCircularButton(context, "◀", 40, "#EB121622", Color.parseColor("#38BDF8"), 14f);
        floatingArrowBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleQuickDrawer();
            }
        });

        // Панель быстрых действий (выдвижная)
        quickActionsDrawer = new LinearLayout(context);
        quickActionsDrawer.setOrientation(LinearLayout.VERTICAL);
        quickActionsDrawer.setVisibility(View.GONE);

        GradientDrawable drawerBg = new GradientDrawable();
        drawerBg.setColor(Color.parseColor("#EB121622"));
        drawerBg.setCornerRadius(dpToPx(16));
        drawerBg.setStroke(dpToPx(1), Color.parseColor("#334155"));
        quickActionsDrawer.setBackground(drawerBg);
        int pad = dpToPx(8);
        quickActionsDrawer.setPadding(pad, pad, pad, pad);

        // 4 быстрые кнопки
        quickBtnKeyboard = createQuickActionButton(context, "⌨", "Клавиатура", new Runnable() {
            @Override
            public void run() {
                toggleCustomKeyboard();
            }
        });
        quickBtnMic = createQuickActionButton(context, "🎤", "Микрофон", new Runnable() {
            @Override
            public void run() {
                toggleMicStreaming();
            }
        });
        quickBtnSound = createQuickActionButton(context, "🔊", "Звук ПК", new Runnable() {
            @Override
            public void run() {
                setAudioEnabled(!isAudioEnabled);
                updateQuickActionStates();
            }
        });
        quickBtnTouchpad = createQuickActionButton(context, "🖱", "Тачпад", new Runnable() {
            @Override
            public void run() {
                isTouchpadEnabled = !isTouchpadEnabled;
                updateQuickActionStates();
                Toast.makeText(getContext(), isTouchpadEnabled ? "Тачпад включён" : "Тачпад выключен", Toast.LENGTH_SHORT).show();
            }
        });

        quickActionsDrawer.addView(quickBtnKeyboard);
        addQuickSpacer(context, quickActionsDrawer);
        quickActionsDrawer.addView(quickBtnMic);
        addQuickSpacer(context, quickActionsDrawer);
        quickActionsDrawer.addView(quickBtnSound);
        addQuickSpacer(context, quickActionsDrawer);
        quickActionsDrawer.addView(quickBtnTouchpad);

        // Компоновка плавающего контейнера
        LinearLayout headRow = new LinearLayout(context);
        headRow.setOrientation(LinearLayout.HORIZONTAL);
        headRow.setGravity(Gravity.CENTER_VERTICAL);
        headRow.addView(floatingArrowBtn);
        View sp = new View(context);
        headRow.addView(sp, new LinearLayout.LayoutParams(dpToPx(6), 1));
        headRow.addView(floatingGearBtn);

        LinearLayout groupCol = new LinearLayout(context);
        groupCol.setOrientation(LinearLayout.VERTICAL);
        groupCol.setGravity(Gravity.RIGHT);
        groupCol.addView(headRow);

        LinearLayout.LayoutParams drawerLp = new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        drawerLp.topMargin = dpToPx(8);
        groupCol.addView(quickActionsDrawer, drawerLp);

        floatingControlsGroup.addView(groupCol);
        addView(floatingControlsGroup, new FrameLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT));

        updateQuickActionStates();
    }

    private TextView createCircularButton(Context context, String text, int sizeDp, String bgHex, int textColor, float textSp) {
        TextView btn = new TextView(context);
        btn.setText(text);
        btn.setTextColor(textColor);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSp);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setGravity(Gravity.CENTER);

        int px = dpToPx(sizeDp);
        btn.setLayoutParams(new LinearLayout.LayoutParams(px, px));

        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor(bgHex));
        gd.setCornerRadius(px / 2f);
        gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
        btn.setBackground(gd);
        return btn;
    }

    private TextView createQuickActionButton(Context context, final String icon, final String label, final Runnable onClick) {
        TextView btn = new TextView(context);
        btn.setText(icon + " " + label);
        btn.setTextColor(Color.parseColor("#94A3B8"));
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setGravity(Gravity.CENTER_VERTICAL | Gravity.LEFT);
        btn.setMinWidth(dpToPx(130));
        btn.setMinHeight(dpToPx(48));

        int padX = dpToPx(10);
        int padY = dpToPx(6);
        btn.setPadding(padX, padY, padX, padY);

        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor("#1E2530"));
        gd.setCornerRadius(dpToPx(10));
        gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
        btn.setBackground(gd);

        btn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (onClick != null) onClick.run();
            }
        });
        return btn;
    }

    private void addQuickSpacer(Context context, LinearLayout parent) {
        View sp = new View(context);
        parent.addView(sp, new LinearLayout.LayoutParams(1, dpToPx(6)));
    }

    private void setQuickButtonState(TextView btn, boolean active, boolean error) {
        if (btn == null) return;
        GradientDrawable gd = new GradientDrawable();
        gd.setCornerRadius(dpToPx(10));
        if (error) {
            gd.setColor(Color.parseColor("#3B181E"));
            gd.setStroke(dpToPx(1), Color.parseColor("#EF4444"));
            btn.setTextColor(Color.parseColor("#FCA5A5"));
        } else if (active) {
            // Мягкий сине-бирюзовый акцент PC Control
            gd.setColor(Color.parseColor("#0C4A6E"));
            gd.setStroke(dpToPx(1), Color.parseColor("#38BDF8"));
            btn.setTextColor(Color.parseColor("#38BDF8"));
        } else {
            gd.setColor(Color.parseColor("#1E2530"));
            gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
            btn.setTextColor(Color.parseColor("#94A3B8"));
        }
        btn.setBackground(gd);
    }

    private void updateQuickActionStates() {
        setQuickButtonState(quickBtnKeyboard, isKeyboardVisible, false);
        setQuickButtonState(quickBtnMic, isMicStreaming, false);
        setQuickButtonState(quickBtnSound, isAudioEnabled, false);
        setQuickButtonState(quickBtnTouchpad, isTouchpadEnabled, false);
    }

    private void toggleQuickDrawer() {
        isQuickDrawerOpen = !isQuickDrawerOpen;
        if (isQuickDrawerOpen) {
            quickActionsDrawer.setVisibility(View.VISIBLE);
            floatingArrowBtn.setText("▶");
            AlphaAnimation fa = new AlphaAnimation(0f, 1f);
            fa.setDuration(180);
            quickActionsDrawer.startAnimation(fa);
        } else {
            floatingArrowBtn.setText("◀");
            quickActionsDrawer.setVisibility(View.GONE);
        }
    }

    // -----------------------------------------------------------------------
    // АНИМИРОВАННЫЙ SPLIT-SCREEN РЕДАКТОР НАСТРОЕК (Scale, Translate, Preview)
    // -----------------------------------------------------------------------
    private void buildSplitSettings(Context context) {
        splitSettingsContainer = new FrameLayout(context);
        splitSettingsContainer.setVisibility(View.GONE);
        splitSettingsContainer.setBackgroundColor(Color.parseColor("#CC030303"));

        splitSettingsScroll = new ScrollView(context);
        splitSettingsScroll.setVerticalScrollBarEnabled(false);

        splitSettingsCard = new LinearLayout(context);
        splitSettingsCard.setOrientation(LinearLayout.VERTICAL);

        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#EB121622"));
        bg.setCornerRadius(dpToPx(20));
        bg.setStroke(dpToPx(1), Color.parseColor("#334155"));
        splitSettingsCard.setBackground(bg);

        int pad = dpToPx(18);
        splitSettingsCard.setPadding(pad, pad, pad, pad);

        splitSettingsScroll.addView(splitSettingsCard, new ScrollView.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        splitSettingsContainer.addView(splitSettingsScroll, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));

        addView(splitSettingsContainer, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    private void toggleSplitSettings() {
        if (isSplitSettingsOpen) {
            closeSplitSettingsWithAnimation();
        } else {
            openSplitSettingsWithAnimation(0);
        }
    }

    /**
     * Плавная анимация: уменьшение живого видео слева (scale=0.52), выезд панели справа.
     */
    private void openSplitSettingsWithAnimation(int section) {
        isSplitSettingsOpen = true;
        activeSettingsSection = section;
        renderSplitSettingsContent();

        // Скрываем плавающие кнопки на время настроек
        if (floatingControlsGroup != null) floatingControlsGroup.setVisibility(View.GONE);
        if (customKeyboardView != null) customKeyboardView.setVisibility(View.GONE);

        splitSettingsContainer.setVisibility(View.VISIBLE);
        splitSettingsContainer.setAlpha(0f);

        int parentW = getWidth();
        int parentH = getHeight();

        // Анимация контейнера видео: масштабирование до 50% и сдвиг вправо
        videoContainer.animate()
                .scaleX(0.50f)
                .scaleY(0.50f)
                .translationX(parentW * 0.24f)
                .setDuration(280)
                .setInterpolator(new AccelerateDecelerateInterpolator())
                .start();

        // Анимация появления панели настроек слева
        splitSettingsContainer.animate()
                .alpha(1f)
                .setDuration(280)
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
        if (touchpadVisualEditor != null) {
            touchpadVisualEditor.setVisibility(View.GONE);
            isTouchpadEditing = false;
        }

        videoContainer.animate()
                .scaleX(1.0f)
                .scaleY(1.0f)
                .translationX(0f)
                .translationY(0f)
                .setDuration(260)
                .setInterpolator(new DecelerateInterpolator())
                .start();

        splitSettingsContainer.animate()
                .alpha(0f)
                .setDuration(220)
                .setListener(new AnimatorListenerAdapter() {
                    @Override
                    public void onAnimationEnd(Animator animation) {
                        splitSettingsContainer.setVisibility(View.GONE);
                        if (operatingMode == MODE_PC_CONTROL && floatingControlsGroup != null) {
                            floatingControlsGroup.setVisibility(View.VISIBLE);
                        }
                        requestLayout();
                    }
                })
                .start();
    }

    private void renderSplitSettingsContent() {
        splitSettingsCard.removeAllViews();
        Context ctx = getContext();

        // Шапка панели настроек
        LinearLayout head = new LinearLayout(ctx);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(ctx);
        title.setText(getSectionTitle(activeSettingsSection));
        title.setTextColor(Color.parseColor("#38BDF8"));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        head.addView(title, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));

        TextView closeX = createToolbarButton(ctx, "✕", "#242A35", Color.parseColor("#94A3B8"), 14f);
        closeX.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeSplitSettingsWithAnimation();
            }
        });
        head.addView(closeX);
        splitSettingsCard.addView(head);

        addDivider(ctx, splitSettingsCard);

        if (activeSettingsSection == 0) {
            // Главное меню разделов
            buildMainSettingsMenu(ctx);
        } else if (activeSettingsSection == 1) {
            // Раздел: Экран
            buildScreenSettingsSection(ctx);
        } else if (activeSettingsSection == 2) {
            // Раздел: Качество
            buildQualitySettingsSection(ctx);
        } else if (activeSettingsSection == 3) {
            // Раздел: FPS
            buildFpsSettingsSection(ctx);
        } else if (activeSettingsSection == 4) {
            // Раздел: Тачпад
            buildTouchpadSettingsSection(ctx);
        } else if (activeSettingsSection == 5) {
            // Раздел: Клавиатура
            buildKeyboardSettingsSection(ctx);
        } else if (activeSettingsSection == 6) {
            // Раздел: Прозрачность
            buildOpacitySettingsSection(ctx);
        }
    }

    private String getSectionTitle(int s) {
        switch (s) {
            case 1: return "НАСТРОЙКИ ЭКРАНА";
            case 2: return "КАЧЕСТВО ИЗОБРАЖЕНИЯ";
            case 3: return "ЧАСТОТА КАДРОВ (FPS)";
            case 4: return "НАСТРОЙКА ТАЧПАДА";
            case 5: return "ЭКРАННАЯ КЛАВИАТУРА";
            case 6: return "ПРОЗРАЧНОСТЬ ИНТЕРФЕЙСА";
            default: return "УПРАВЛЕНИЕ ПК: НАСТРОЙКИ";
        }
    }

    private void buildMainSettingsMenu(Context ctx) {
        addSectionNavButton(ctx, "🖥 1. Экран (Мониторы)", 1);
        addSectionNavButton(ctx, "🎨 2. Качество изображения", 2);
        addSectionNavButton(ctx, "⚡ 3. Частота кадров (FPS)", 3);
        addSectionNavButton(ctx, "🖱 4. Прозрачный тачпад", 4);
        addSectionNavButton(ctx, "⌨ 5. Экранная клавиатура", 5);
        addSectionNavButton(ctx, "👁 6. Прозрачность элементов", 6);

        addDivider(ctx, splitSettingsCard);

        // Кнопка перехода в диагностику
        TextView diagBtn = createToolbarButton(ctx, "📊 Диагностика и телеметрия потока", "#1E293B", Color.parseColor("#38BDF8"), 13f);
        diagBtn.setLayoutParams(new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        diagBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeSplitSettingsWithAnimation();
                setDiagnosticsVisible(true);
            }
        });
        splitSettingsCard.addView(diagBtn);
    }

    private void addSectionNavButton(Context ctx, String title, final int targetSection) {
        TextView btn = createToolbarButton(ctx, title, "#1E2530", Color.WHITE, 13f);
        btn.setGravity(Gravity.CENTER_VERTICAL | Gravity.LEFT);
        int pad = dpToPx(12);
        btn.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dpToPx(8);
        btn.setLayoutParams(lp);
        btn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                activeSettingsSection = targetSection;
                renderSplitSettingsContent();
            }
        });
        splitSettingsCard.addView(btn);
    }

    private interface TouchpadBoundsListener {
        void onBoundsChanged(float x, float y, float w, float h);
    }
    private TouchpadBoundsListener touchpadBoundsListener;

    private void addSmallSpacer(Context ctx, LinearLayout parent) {
        View sp = new View(ctx);
        parent.addView(sp, new LinearLayout.LayoutParams(dpToPx(6), 1));
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

        addBackToMainButton(ctx);

        addSectionHeader(ctx, splitSettingsCard, "ЖИВАЯ РЕГУЛИРОВКА ПАРАМЕТРОВ");

        // Ширина тачпада
        final TextView wLbl = new TextView(ctx);
        wLbl.setText("Ширина зоны: " + (int) (tpNormW * 100) + "%");
        wLbl.setTextColor(Color.parseColor("#CBD5E1"));
        wLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        splitSettingsCard.addView(wLbl);

        final SeekBar wBar = createSlider(ctx, 15, 95, (int) (tpNormW * 100), new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                tpNormW = val / 100f;
                wLbl.setText("Ширина зоны: " + val + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });
        splitSettingsCard.addView(wBar);

        // Высота тачпада
        final TextView hLbl = new TextView(ctx);
        hLbl.setText("Высота зоны: " + (int) (tpNormH * 100) + "%");
        hLbl.setTextColor(Color.parseColor("#CBD5E1"));
        hLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        splitSettingsCard.addView(hLbl);

        final SeekBar hBar = createSlider(ctx, 15, 95, (int) (tpNormH * 100), new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                tpNormH = val / 100f;
                hLbl.setText("Высота зоны: " + val + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });
        splitSettingsCard.addView(hBar);

        touchpadBoundsListener = new TouchpadBoundsListener() {
            @Override
            public void onBoundsChanged(float x, float y, float w, float h) {
                wLbl.setText("Ширина зоны: " + (int) (w * 100) + "%");
                hLbl.setText("Высота зоны: " + (int) (h * 100) + "%");
                wBar.setProgress((int) (w * 100));
                hBar.setProgress((int) (h * 100));
            }
        };

        // ТОЧНАЯ КОРРЕКЦИЯ СТРЕЛОЧКАМИ
        addSectionHeader(ctx, splitSettingsCard, "ТОЧНАЯ КОРРЕКЦИЯ СТРЕЛОЧКАМИ (±1%)");

        LinearLayout arrowRow1 = new LinearLayout(ctx);
        arrowRow1.setOrientation(LinearLayout.HORIZONTAL);

        TextView leftBtn = createToolbarButton(ctx, "◀ X-", "#1E2530", Color.WHITE, 12f);
        leftBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormX = Math.max(0f, tpNormX - 0.01f);
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView rightBtn = createToolbarButton(ctx, "X+ ▶", "#1E2530", Color.WHITE, 12f);
        rightBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormX = Math.min(1f - tpNormW, tpNormX + 0.01f);
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView upBtn = createToolbarButton(ctx, "▲ Y-", "#1E2530", Color.WHITE, 12f);
        upBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormY = Math.max(0f, tpNormY - 0.01f);
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView downBtn = createToolbarButton(ctx, "Y+ ▼", "#1E2530", Color.WHITE, 12f);
        downBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormY = Math.min(1f - tpNormH, tpNormY + 0.01f);
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        arrowRow1.addView(leftBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow1);
        arrowRow1.addView(rightBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow1);
        arrowRow1.addView(upBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow1);
        arrowRow1.addView(downBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        splitSettingsCard.addView(arrowRow1);

        LinearLayout arrowRow2 = new LinearLayout(ctx);
        arrowRow2.setOrientation(LinearLayout.HORIZONTAL);
        arrowRow2.setPadding(0, dpToPx(6), 0, 0);

        TextView wDecBtn = createToolbarButton(ctx, "Шир -", "#1E2530", Color.WHITE, 12f);
        wDecBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormW = Math.max(0.15f, tpNormW - 0.01f);
                wBar.setProgress((int) (tpNormW * 100));
                wLbl.setText("Ширина зоны: " + (int) (tpNormW * 100) + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView wIncBtn = createToolbarButton(ctx, "Шир +", "#1E2530", Color.WHITE, 12f);
        wIncBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormW = Math.min(1f - tpNormX, tpNormW + 0.01f);
                wBar.setProgress((int) (tpNormW * 100));
                wLbl.setText("Ширина зоны: " + (int) (tpNormW * 100) + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView hDecBtn = createToolbarButton(ctx, "Выс -", "#1E2530", Color.WHITE, 12f);
        hDecBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormH = Math.max(0.15f, tpNormH - 0.01f);
                hBar.setProgress((int) (tpNormH * 100));
                hLbl.setText("Высота зоны: " + (int) (tpNormH * 100) + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        TextView hIncBtn = createToolbarButton(ctx, "Выс +", "#1E2530", Color.WHITE, 12f);
        hIncBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                tpNormH = Math.min(1f - tpNormY, tpNormH + 0.01f);
                hBar.setProgress((int) (tpNormH * 100));
                hLbl.setText("Высота зоны: " + (int) (tpNormH * 100) + "%");
                if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
            }
        });

        arrowRow2.addView(wDecBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow2);
        arrowRow2.addView(wIncBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow2);
        arrowRow2.addView(hDecBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, arrowRow2);
        arrowRow2.addView(hIncBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        splitSettingsCard.addView(arrowRow2);

        // Чувствительность мыши
        final TextView sLbl = new TextView(ctx);
        sLbl.setText("Чувствительность: " + String.format("%.1f", mouseSensitivity) + "x");
        sLbl.setTextColor(Color.parseColor("#CBD5E1"));
        sLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        splitSettingsCard.addView(sLbl);

        SeekBar sBar = createSlider(ctx, 2, 30, (int) (mouseSensitivity * 10), new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                mouseSensitivity = val / 10f;
                sLbl.setText("Чувствительность: " + String.format("%.1f", mouseSensitivity) + "x");
            }
        });
        splitSettingsCard.addView(sBar);

        // Режим мыши: Относительный vs Абсолютный
        addSectionHeader(ctx, splitSettingsCard, "РЕЖИМ УПРАВЛЕНИЯ");
        LinearLayout modeRow = new LinearLayout(ctx);
        modeRow.setOrientation(LinearLayout.HORIZONTAL);

        final TextView relChip = createChipButton(ctx, "Относительный (Тачпад)", null);
        final TextView absChip = createChipButton(ctx, "Абсолютный (Перо)", null);
        setChipActive(relChip, !isMouseAbsolute);
        setChipActive(absChip, isMouseAbsolute);

        relChip.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                isMouseAbsolute = false;
                setChipActive(relChip, true);
                setChipActive(absChip, false);
            }
        });
        absChip.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                isMouseAbsolute = true;
                setChipActive(relChip, false);
                setChipActive(absChip, true);
            }
        });
        modeRow.addView(relChip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        modeRow.addView(absChip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        splitSettingsCard.addView(modeRow);

        addDivider(ctx, splitSettingsCard);

        // Кнопки сохранения: Сброс, Отмена, Применить
        LinearLayout btnRow = new LinearLayout(ctx);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);

        TextView resetBtn = createToolbarButton(ctx, "Сброс", "#242A35", Color.parseColor("#94A3B8"), 12f);
        resetBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                tpNormX = 0.55f;
                tpNormY = 0.10f;
                tpNormW = 0.42f;
                tpNormH = 0.80f;
                mouseSensitivity = 1.0f;
                mouseAccel = true;
                isMouseAbsolute = false;
                savePreferences();
                renderSplitSettingsContent();
            }
        });

        TextView cancelBtn = createToolbarButton(ctx, "✕ Отмена", "#334155", Color.parseColor("#CBD5E1"), 12f);
        cancelBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                tpNormX = initX;
                tpNormY = initY;
                tpNormW = initW;
                tpNormH = initH;
                touchpadBoundsListener = null;
                if (touchpadVisualEditor != null) {
                    touchpadVisualEditor.setVisibility(View.GONE);
                    isTouchpadEditing = false;
                }
                closeSplitSettingsWithAnimation();
                Toast.makeText(getContext(), "Изменения тачпада отменены", Toast.LENGTH_SHORT).show();
            }
        });

        TextView applyBtn = createToolbarButton(ctx, "✓ Применить", "#16A34A", Color.WHITE, 12f);
        applyBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                touchpadBoundsListener = null;
                savePreferences();
                closeSplitSettingsWithAnimation();
                Toast.makeText(getContext(), "Настройки тачпада сохранены", Toast.LENGTH_SHORT).show();
            }
        });

        btnRow.addView(resetBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, btnRow);
        btnRow.addView(cancelBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        addSmallSpacer(ctx, btnRow);
        btnRow.addView(applyBtn, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        splitSettingsCard.addView(btnRow);
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛ: КЛАВИАТУРА (СОБСТВЕННАЯ КЛАВИАТУРА И ПАРАМЕТРЫ)
    // -----------------------------------------------------------------------
    private void buildKeyboardSettingsSection(Context ctx) {
        addBackToMainButton(ctx);

        addSectionHeader(ctx, splitSettingsCard, "НАСТРОЙКИ ЭКРАННОЙ КЛАВИАТУРЫ");

        final TextView hLbl = new TextView(ctx);
        hLbl.setText("Высота клавиатуры: " + kbdHeightDp + " dp");
        hLbl.setTextColor(Color.parseColor("#CBD5E1"));
        hLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        splitSettingsCard.addView(hLbl);

        SeekBar hBar = createSlider(ctx, 160, 320, kbdHeightDp, new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                kbdHeightDp = val;
                hLbl.setText("Высота клавиатуры: " + val + " dp");
                if (customKeyboardView != null) customKeyboardView.updateLayoutSize();
            }
        });
        splitSettingsCard.addView(hBar);

        // Прозрачность фона клавиатуры
        final TextView opLbl = new TextView(ctx);
        opLbl.setText("Прозрачность подложки: " + opacityKbdBg + "%");
        opLbl.setTextColor(Color.parseColor("#CBD5E1"));
        opLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        splitSettingsCard.addView(opLbl);

        SeekBar opBar = createSlider(ctx, 20, 100, opacityKbdBg, new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                opacityKbdBg = val;
                opLbl.setText("Прозрачность подложки: " + val + "%");
                applyOpacities();
            }
        });
        splitSettingsCard.addView(opBar);

        addDivider(ctx, splitSettingsCard);

        TextView testKbdBtn = createToolbarButton(ctx, "⌨ Открыть клавиатуру для проверки", "#1E2530", Color.parseColor("#38BDF8"), 13f);
        testKbdBtn.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                closeSplitSettingsWithAnimation();
                showCustomKeyboard(true);
            }
        });
        splitSettingsCard.addView(testKbdBtn);
    }

    // -----------------------------------------------------------------------
    // РАЗДЕЛ: ПРОЗРАЧНОСТЬ (14 ИНДИВИДУАЛЬНЫХ СЛАЙДЕРОВ С ЖИВЫМ ПРИМЕНЕНИЕМ)
    // -----------------------------------------------------------------------
    private void buildOpacitySettingsSection(Context ctx) {
        addBackToMainButton(ctx);

        addSectionHeader(ctx, splitSettingsCard, "ПРОЗРАЧНОСТЬ ЭЛЕМЕНТОВ (0 - 100%)");

        addOpacitySlider(ctx, "Шестерёнка настроек", opacityGear, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityGear = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Стрелочка быстрого меню", opacityArrow, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityArrow = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Панель быстрых действий", opacityQuickDrawer, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityQuickDrawer = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Кнопка «Клавиатура»", opacityBtnKeyboard, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityBtnKeyboard = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Кнопка «Микрофон»", opacityBtnMic, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityBtnMic = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Кнопка «Звук ПК»", opacityBtnSound, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityBtnSound = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Кнопка «Тачпад»", opacityBtnTouchpad, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityBtnTouchpad = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Основная панель настроек", opacitySettings, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacitySettings = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Панель диагностики", opacityDiag, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityDiag = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Подложка клавиатуры", opacityKbdBg, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityKbdBg = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Клавиши клавиатуры", opacityKbdKeys, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityKbdKeys = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Панель спец-клавиш", opacityKbdSpecial, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityKbdSpecial = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Рамка тачпада в редакторе", opacityTpBorder, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityTpBorder = v; applyOpacities(); }
        });
        addOpacitySlider(ctx, "Индикатор тачпада", opacityTpCenter, new SeekBarCallback() {
            @Override
            public void onVal(int v) { opacityTpCenter = v; applyOpacities(); }
        });

        addDivider(ctx, splitSettingsCard);

        TextView resetOp = createToolbarButton(ctx, "Сбросить прозрачность по умолчанию", "#242A35", Color.parseColor("#E2E8F0"), 13f);
        resetOp.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                resetDefaultOpacities();
                savePreferences();
                renderSplitSettingsContent();
            }
        });
        splitSettingsCard.addView(resetOp);
    }

    private void addOpacitySlider(Context ctx, String label, int currentVal, final SeekBarCallback cb) {
        final TextView lbl = new TextView(ctx);
        lbl.setText(label + ": " + currentVal + "%");
        lbl.setTextColor(Color.parseColor("#CBD5E1"));
        lbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        splitSettingsCard.addView(lbl);

        SeekBar sb = createSlider(ctx, 10, 100, currentVal, new SeekBarCallback() {
            @Override
            public void onVal(int val) {
                cb.onVal(val);
                lbl.setText(label + ": " + val + "%");
            }
        });
        splitSettingsCard.addView(sb);
    }

    private void applyOpacities() {
        if (floatingGearBtn != null) floatingGearBtn.setAlpha(opacityGear / 100f);
        if (floatingArrowBtn != null) floatingArrowBtn.setAlpha(opacityArrow / 100f);
        if (quickActionsDrawer != null) quickActionsDrawer.setAlpha(opacityQuickDrawer / 100f);
        if (quickBtnKeyboard != null) quickBtnKeyboard.setAlpha(opacityBtnKeyboard / 100f);
        if (quickBtnMic != null) quickBtnMic.setAlpha(opacityBtnMic / 100f);
        if (quickBtnSound != null) quickBtnSound.setAlpha(opacityBtnSound / 100f);
        if (quickBtnTouchpad != null) quickBtnTouchpad.setAlpha(opacityBtnTouchpad / 100f);
        if (splitSettingsCard != null) splitSettingsCard.setAlpha(opacitySettings / 100f);
        if (diagCard != null) diagCard.setAlpha(opacityDiag / 100f);
        if (customKeyboardView != null) customKeyboardView.applyOpacity(opacityKbdBg / 100f, opacityKbdKeys / 100f);
        if (touchpadVisualEditor != null) touchpadVisualEditor.invalidate();
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
    // РАЗДЕЛЫ: ЭКРАН, КАЧЕСТВО, FPS
    // -----------------------------------------------------------------------
    private void buildScreenSettingsSection(Context ctx) {
        addBackToMainButton(ctx);
        addSectionHeader(ctx, splitSettingsCard, "ВЫБОР МОНИТОРА");

        LinearLayout monRow = new LinearLayout(ctx);
        monRow.setOrientation(LinearLayout.HORIZONTAL);
        monitorChips.clear();

        final int[] mIds = {1, 2, 0};
        final String[] mNames = {"Экран 1", "Экран 2", "Все"};
        for (int i = 0; i < mIds.length; i++) {
            final int mId = mIds[i];
            TextView chip = createChipButton(ctx, mNames[i], new Runnable() {
                @Override
                public void run() {
                    applyVideoSettings(mId, targetHeight, targetFps, targetBitrate);
                }
            });
            chip.setTag(mId);
            setChipActive(chip, mId == targetMonitor);
            monitorChips.add(chip);
            monRow.addView(chip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        }
        splitSettingsCard.addView(monRow);
    }

    private void buildQualitySettingsSection(Context ctx) {
        addBackToMainButton(ctx);
        addSectionHeader(ctx, splitSettingsCard, "РАЗРЕШЕНИЕ");

        LinearLayout resRow = new LinearLayout(ctx);
        resRow.setOrientation(LinearLayout.HORIZONTAL);
        resChips.clear();

        final int[] rVals = {480, 720, 1080, 0};
        final String[] rNames = {"480p", "720p", "1080p", "Native"};
        for (int i = 0; i < rVals.length; i++) {
            final int h = rVals[i];
            TextView chip = createChipButton(ctx, rNames[i], new Runnable() {
                @Override
                public void run() {
                    applyVideoSettings(targetMonitor, h, targetFps, targetBitrate);
                }
            });
            resChips.put(h, chip);
            setChipActive(chip, h == targetHeight);
            resRow.addView(chip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        }
        splitSettingsCard.addView(resRow);

        addDivider(ctx, splitSettingsCard);
        addSectionHeader(ctx, splitSettingsCard, "БИТРЕЙТ");

        LinearLayout brRow = new LinearLayout(ctx);
        brRow.setOrientation(LinearLayout.HORIZONTAL);
        bitrateChips.clear();

        final int[] bVals = {0, 5, 15, 30, 50};
        final String[] bNames = {"Авто", "5M", "15M", "30M", "50M"};
        for (int i = 0; i < bVals.length; i++) {
            final int b = bVals[i];
            TextView chip = createChipButton(ctx, bNames[i], new Runnable() {
                @Override
                public void run() {
                    applyVideoSettings(targetMonitor, targetHeight, targetFps, b);
                }
            });
            bitrateChips.put(b, chip);
            setChipActive(chip, b == targetBitrate);
            brRow.addView(chip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        }
        splitSettingsCard.addView(brRow);
    }

    private void buildFpsSettingsSection(Context ctx) {
        addBackToMainButton(ctx);
        addSectionHeader(ctx, splitSettingsCard, "ЧАСТОТА КАДРОВ");

        LinearLayout fpsRow = new LinearLayout(ctx);
        fpsRow.setOrientation(LinearLayout.HORIZONTAL);
        fpsChips.clear();

        final int[] fVals = {30, 60, 90};
        final String[] fNames = {"30 FPS", "60 FPS", "90 FPS"};
        for (int i = 0; i < fVals.length; i++) {
            final int f = fVals[i];
            TextView chip = createChipButton(ctx, fNames[i], new Runnable() {
                @Override
                public void run() {
                    applyVideoSettings(targetMonitor, targetHeight, f, targetBitrate);
                }
            });
            fpsChips.put(f, chip);
            setChipActive(chip, f == targetFps);
            fpsRow.addView(chip, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        }
        splitSettingsCard.addView(fpsRow);
    }

    private void addBackToMainButton(Context ctx) {
        TextView back = createToolbarButton(ctx, "← Назад к разделам", "#1E2530", Color.parseColor("#94A3B8"), 12f);
        back.setGravity(Gravity.CENTER_VERTICAL | Gravity.LEFT);
        int pad = dpToPx(8);
        back.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dpToPx(12);
        back.setLayoutParams(lp);
        back.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (touchpadVisualEditor != null) {
                    touchpadVisualEditor.setVisibility(View.GONE);
                    isTouchpadEditing = false;
                }
                activeSettingsSection = 0;
                renderSplitSettingsContent();
            }
        });
        splitSettingsCard.addView(back);
    }

    private interface SeekBarCallback {
        void onVal(int val);
    }

    private SeekBar createSlider(Context ctx, int min, int max, int current, final SeekBarCallback cb) {
        SeekBar sb = new SeekBar(ctx);
        sb.setMax(max - min);
        sb.setProgress(Math.max(0, current - min));
        sb.setPadding(dpToPx(8), dpToPx(8), dpToPx(8), dpToPx(8));
        final int finalMin = min;
        sb.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (fromUser && cb != null) {
                    cb.onVal(finalMin + progress);
                }
            }
            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {}
        });
        return sb;
    }

    // -----------------------------------------------------------------------
    // СОБСТВЕННАЯ ЭКРАННАЯ КЛАВИАТУРА PC CONTROL
    // -----------------------------------------------------------------------
    private void buildCustomKeyboard(Context context) {
        customKeyboardView = new CustomKeyboardView(context);
        customKeyboardView.setVisibility(View.GONE);
        addView(customKeyboardView, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, Gravity.BOTTOM));
    }

    private void toggleCustomKeyboard() {
        showCustomKeyboard(!isKeyboardVisible);
    }

    private void showCustomKeyboard(boolean show) {
        isKeyboardVisible = show;
        if (customKeyboardView != null) {
            if (!show) {
                // При закрытии клавиатуры обязательно отпускаем модификаторы, чтобы они не зависали в Windows
                customKeyboardView.releaseHeldModifiers();
            }
            customKeyboardView.setVisibility(show ? View.VISIBLE : View.GONE);
            if (show) {
                customKeyboardView.setAlpha(0f);
                customKeyboardView.animate().alpha(1f).setDuration(200).start();
            }
        }
        updateQuickActionStates();
    }

    /**
     * Компонент экранной клавиатуры с поддержкой раскладок EN, RU, UK, Symbols и горячих клавиш.
     */
    private class CustomKeyboardView extends LinearLayout {
        private LinearLayout specialBar;
        private LinearLayout keyContainer;
        private boolean isShiftActive = false;
        private boolean isCtrlActive = false;
        private boolean isAltActive = false;
        private boolean isWinActive = false;

        public CustomKeyboardView(Context context) {
            super(context);
            setOrientation(LinearLayout.VERTICAL);
            initKbd(context);
        }

        private void initKbd(Context context) {
            GradientDrawable gd = new GradientDrawable();
            gd.setColor(Color.parseColor("#E6121622"));
            gd.setCornerRadius(dpToPx(16));
            gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
            setBackground(gd);
            int pad = dpToPx(6);
            setPadding(pad, pad, pad, pad);

            // Панель специальных клавиш (Esc, Tab, Del, Home, End, PgUp/Down, Arrows, F-keys) с горизонтальной прокруткой
            HorizontalScrollView specialScroll = new HorizontalScrollView(context);
            specialScroll.setHorizontalScrollBarEnabled(false);
            specialScroll.setFillViewport(true);

            specialBar = new LinearLayout(context);
            specialBar.setOrientation(LinearLayout.HORIZONTAL);
            specialBar.setGravity(Gravity.CENTER_VERTICAL);
            buildSpecialBar(context);

            specialScroll.addView(specialBar, new FrameLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT));
            addView(specialScroll);

            // Контейнер алфавитных рядов
            keyContainer = new LinearLayout(context);
            keyContainer.setOrientation(LinearLayout.VERTICAL);
            addView(keyContainer);

            renderKeyboardRows();
            applyOpacity(opacityKbdBg / 100f, opacityKbdKeys / 100f);
        }

        public void updateLayoutSize() {
            if (keyContainer != null) renderKeyboardRows();
        }

        public void applyOpacity(float bgOp, float keyOp) {
            setAlpha(bgOp);
        }

        public void releaseHeldModifiers() {
            if (isCtrlActive) {
                isCtrlActive = false;
                sendModifierKey("ctrl", false);
            }
            if (isAltActive) {
                isAltActive = false;
                sendModifierKey("alt", false);
            }
            if (isWinActive) {
                isWinActive = false;
                sendModifierKey("win", false);
            }
            if (isShiftActive) {
                isShiftActive = false;
                sendModifierKey("shift", false);
            }
            renderKeyboardRows();
        }

        private void buildSpecialBar(Context ctx) {
            specialBar.removeAllViews();
            addSpecialKey(ctx, "ESC", new Runnable() { @Override public void run() { sendKeyPress("esc"); } });
            addSpecialKey(ctx, "TAB", new Runnable() { @Override public void run() { sendKeyPress("tab"); } });
            addSpecialKey(ctx, "DEL", new Runnable() { @Override public void run() { sendKeyPress("delete"); } });
            addSpecialKey(ctx, "HOME", new Runnable() { @Override public void run() { sendKeyPress("home"); } });
            addSpecialKey(ctx, "END", new Runnable() { @Override public void run() { sendKeyPress("end"); } });
            addSpecialKey(ctx, "PGUP", new Runnable() { @Override public void run() { sendKeyPress("pageup"); } });
            addSpecialKey(ctx, "PGDN", new Runnable() { @Override public void run() { sendKeyPress("pagedown"); } });
            addSpecialKey(ctx, "↑", new Runnable() { @Override public void run() { sendKeyPress("up"); } });
            addSpecialKey(ctx, "↓", new Runnable() { @Override public void run() { sendKeyPress("down"); } });
            addSpecialKey(ctx, "←", new Runnable() { @Override public void run() { sendKeyPress("left"); } });
            addSpecialKey(ctx, "→", new Runnable() { @Override public void run() { sendKeyPress("right"); } });
            addSpecialKey(ctx, "F1", new Runnable() { @Override public void run() { sendKeyPress("f1"); } });
            addSpecialKey(ctx, "F2", new Runnable() { @Override public void run() { sendKeyPress("f2"); } });
            addSpecialKey(ctx, "F5", new Runnable() { @Override public void run() { sendKeyPress("f5"); } });
            addSpecialKey(ctx, "F11", new Runnable() { @Override public void run() { sendKeyPress("f11"); } });
            addSpecialKey(ctx, "F12", new Runnable() { @Override public void run() { sendKeyPress("f12"); } });
            addSpecialKey(ctx, "✕", new Runnable() { @Override public void run() { showCustomKeyboard(false); } });
        }

        private void addSpecialKey(Context ctx, String text, final Runnable act) {
            TextView btn = createKeyView(ctx, text, 1.0f, false, act);
            btn.setTextColor(Color.parseColor("#38BDF8"));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, dpToPx(36));
            lp.setMargins(dpToPx(2), dpToPx(2), dpToPx(2), dpToPx(4));
            int padX = dpToPx(10);
            btn.setPadding(padX, 0, padX, 0);
            btn.setLayoutParams(lp);
            specialBar.addView(btn);
        }

        private void renderKeyboardRows() {
            keyContainer.removeAllViews();
            Context ctx = getContext();

            String[][] rows;
            if (kbdLayoutIdx == 1) {
                // RU раскладка с Shift
                rows = new String[][] {
                    {"Й", "Ц", "У", "К", "Е", "Н", "Г", "Ш", "Щ", "З", "Х", "Ъ"},
                    {"Ф", "Ы", "В", "А", "П", "Р", "О", "Л", "Д", "Ж", "Э"},
                    {"⇧", "Я", "Ч", "С", "М", "И", "Т", "Ь", "Б", "Ю", "⌫"},
                    {"123", "CTRL", "ALT", "WIN", " ", "ENTER", "RU"}
                };
            } else if (kbdLayoutIdx == 2) {
                // UK раскладка с Shift
                rows = new String[][] {
                    {"Й", "Ц", "У", "К", "Е", "Н", "Г", "Ш", "Щ", "З", "Х", "Ї"},
                    {"Ф", "І", "В", "А", "П", "Р", "О", "Л", "Д", "Ж", "Є"},
                    {"⇧", "Я", "Ч", "С", "М", "И", "Т", "Ь", "Б", "Ю", "⌫"},
                    {"123", "CTRL", "ALT", "WIN", " ", "ENTER", "UK"}
                };
            } else if (kbdLayoutIdx == 3) {
                // Цифры и спецсимволы
                rows = new String[][] {
                    {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"},
                    {"@", "#", "$", "%", "&", "*", "-", "+", "(", ")"},
                    {"⇧", "!", "\"", "'", ":", ";", "/", "\\", "?", "⌫"},
                    {"ABC", "CTRL", "ALT", "WIN", " ", "ENTER", "SYM"}
                };
            } else {
                // EN раскладка с Shift
                rows = new String[][] {
                    {"Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"},
                    {"A", "S", "D", "F", "G", "H", "J", "K", "L"},
                    {"⇧", "Z", "X", "C", "V", "B", "N", "M", "⌫"},
                    {"123", "CTRL", "ALT", "WIN", " ", "ENTER", "EN"}
                };
            }

            for (String[] rowKeys : rows) {
                LinearLayout rowLayout = new LinearLayout(ctx);
                rowLayout.setOrientation(LinearLayout.HORIZONTAL);
                rowLayout.setGravity(Gravity.CENTER);

                for (final String key : rowKeys) {
                    float weight = 1.0f;
                    if (" ".equals(key)) weight = 3.5f;
                    else if ("ENTER".equals(key)) weight = 1.8f;
                    else if ("⌫".equals(key)) weight = 1.4f;
                    else if ("⇧".equals(key)) weight = 1.4f;

                    boolean isMod = "CTRL".equals(key) || "ALT".equals(key) || "WIN".equals(key) || "⇧".equals(key);
                    boolean isModActive = ("CTRL".equals(key) && isCtrlActive)
                            || ("ALT".equals(key) && isAltActive)
                            || ("WIN".equals(key) && isWinActive)
                            || ("⇧".equals(key) && isShiftActive);

                    String displayKey = key;
                    if (key.length() == 1 && Character.isLetter(key.charAt(0))) {
                        displayKey = isShiftActive ? key.toUpperCase() : key.toLowerCase();
                    }

                    TextView kView = createKeyView(ctx, displayKey, weight, isModActive, new Runnable() {
                        @Override
                        public void run() {
                            handleKeyTap(key);
                        }
                    });
                    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dpToPx(38), weight);
                    lp.setMargins(dpToPx(2), dpToPx(2), dpToPx(2), dpToPx(2));
                    kView.setLayoutParams(lp);
                    rowLayout.addView(kView);
                }
                keyContainer.addView(rowLayout);
            }
        }

        private TextView createKeyView(Context ctx, String text, float weight, boolean active, final Runnable act) {
            TextView btn = new TextView(ctx);
            btn.setText(" ".equals(text) ? "ПРОБЕЛ" : text);
            btn.setTextColor(active ? Color.parseColor("#38BDF8") : Color.WHITE);
            btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, text.length() > 2 ? 11f : 14f);
            btn.setTypeface(Typeface.DEFAULT_BOLD);
            btn.setGravity(Gravity.CENTER);

            GradientDrawable gd = new GradientDrawable();
            gd.setColor(active ? Color.parseColor("#0C4A6E") : Color.parseColor("#1E2530"));
            gd.setCornerRadius(dpToPx(8));
            gd.setStroke(dpToPx(1), active ? Color.parseColor("#38BDF8") : Color.parseColor("#334155"));
            btn.setBackground(gd);

            btn.setOnClickListener(new OnClickListener() {
                @Override
                public void onClick(View v) {
                    if (act != null) act.run();
                }
            });
            return btn;
        }

        private void handleKeyTap(String key) {
            if ("⌫".equals(key)) {
                sendKeyPress("backspace");
            } else if ("ENTER".equals(key)) {
                sendKeyPress("enter");
            } else if (" ".equals(key)) {
                sendKeyPress("space");
            } else if ("123".equals(key)) {
                kbdLayoutIdx = 3;
                renderKeyboardRows();
            } else if ("ABC".equals(key)) {
                kbdLayoutIdx = 0;
                renderKeyboardRows();
            } else if ("EN".equals(key)) {
                kbdLayoutIdx = 1; // переход на RU
                renderKeyboardRows();
            } else if ("RU".equals(key)) {
                kbdLayoutIdx = 2; // переход на UK
                renderKeyboardRows();
            } else if ("UK".equals(key)) {
                kbdLayoutIdx = 0; // переход на EN
                renderKeyboardRows();
            } else if ("SYM".equals(key)) {
                kbdLayoutIdx = 0;
                renderKeyboardRows();
            } else if ("⇧".equals(key)) {
                isShiftActive = !isShiftActive;
                sendModifierKey("shift", isShiftActive);
                renderKeyboardRows();
            } else if ("CTRL".equals(key)) {
                isCtrlActive = !isCtrlActive;
                sendModifierKey("ctrl", isCtrlActive);
                renderKeyboardRows();
            } else if ("ALT".equals(key)) {
                isAltActive = !isAltActive;
                sendModifierKey("alt", isAltActive);
                renderKeyboardRows();
            } else if ("WIN".equals(key)) {
                isWinActive = !isWinActive;
                sendModifierKey("win", isWinActive);
                renderKeyboardRows();
            } else {
                // Обычный символ (Unicode)
                String charToSend = isShiftActive ? key.toUpperCase() : key.toLowerCase();
                sendUnicodeText(charToSend);
                if (isShiftActive) {
                    isShiftActive = false;
                    sendModifierKey("shift", false);
                    renderKeyboardRows();
                }
            }
        }
    }

    private void sendKeyPress(final String keyName) {
        if (inputDispatcherThread != null) {
            inputDispatcherThread.enqueueKeyPress(keyName);
        }
    }

    private void sendModifierKey(final String keyName, final boolean isDown) {
        if (inputDispatcherThread != null) {
            inputDispatcherThread.enqueueKeyModifier(keyName, isDown);
        }
    }

    private void sendUnicodeText(final String text) {
        if (inputDispatcherThread != null) {
            inputDispatcherThread.enqueueUnicodeText(text);
        }
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
            fillPaint.setColor(Color.parseColor("#2638BDF8"));
            fillPaint.setStyle(android.graphics.Paint.Style.FILL);
            canvas.drawRoundRect(zoneRect, dpToPx(16), dpToPx(16), fillPaint);

            // Рамка зоны тачпада
            android.graphics.Paint borderPaint = new android.graphics.Paint();
            borderPaint.setColor(Color.parseColor("#38BDF8"));
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
    // МУЛЬТИТАЧ СЕНСОРНЫЙ КОНТРОЛЛЕР МЫШИ (ПРОЗРАЧНЫЙ ТАЧПАД)
    // -----------------------------------------------------------------------
    private boolean handleTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        activePointerCount = event.getPointerCount();
        float x = event.getX();
        float y = event.getY();

        if (operatingMode == MODE_VIEW) {
            // В режиме просмотра тапы скрывают/показывают тулбар
            if (action == MotionEvent.ACTION_UP) {
                setControlsVisible(!isControlsVisible, true);
            }
            return true;
        }

        // В режиме Управление ПК: если открыта панель настроек слева, клик по живому видео справа закрывает настройки
        int pW = getWidth();
        int pH = getHeight();
        if (isSplitSettingsOpen && !isTouchpadEditing) {
            if (action == MotionEvent.ACTION_UP && x > pW * 0.48f) {
                closeSplitSettingsWithAnimation();
                return true;
            }
            return false;
        }

        if (pW <= 0 || pH <= 0 || !isTouchpadEnabled || isTouchpadEditing) {
            return false;
        }

        float tpLeft = tpNormX * pW;
        float tpTop = tpNormY * pH;
        float tpRight = (tpNormX + tpNormW) * pW;
        float tpBottom = (tpNormY + tpNormH) * pH;

        // Если касание вне зоны тачпада — пропускаем для остальных элементов
        if (action == MotionEvent.ACTION_DOWN) {
            if (x < tpLeft || x > tpRight || y < tpTop || y > tpBottom) {
                return false;
            }
        }

        switch (action) {
            case MotionEvent.ACTION_DOWN:
                touchStartX = x;
                touchStartY = y;
                lastTouchX = x;
                lastTouchY = y;
                touchDownTime = SystemClock.uptimeMillis();
                isDraggingMouse = false;
                isMouseLongPressed = false;
                mainHandler.postDelayed(longPressRunnable, 350);
                break;

            case MotionEvent.ACTION_MOVE:
                float dx = x - lastTouchX;
                float dy = y - lastTouchY;
                lastTouchX = x;
                lastTouchY = y;

                if (Math.abs(x - touchStartX) > dpToPx(6) || Math.abs(y - touchStartY) > dpToPx(6)) {
                    isDraggingMouse = true;
                    mainHandler.removeCallbacks(longPressRunnable);
                }

                if (activePointerCount == 1) {
                    if (isMouseAbsolute) {
                        float normX = Math.max(0f, Math.min(1f, (x - tpLeft) / (tpRight - tpLeft)));
                        float normY = Math.max(0f, Math.min(1f, (y - tpTop) / (tpBottom - tpTop)));
                        if (inputDispatcherThread != null) {
                            inputDispatcherThread.enqueueMouseMoveNorm(normX, normY, targetMonitor);
                        }
                    } else {
                        if (inputDispatcherThread != null) {
                            inputDispatcherThread.enqueueMouseMoveRel(dx, dy, mouseSensitivity, mouseAccel);
                        }
                    }
                } else if (activePointerCount >= 2) {
                    mainHandler.removeCallbacks(longPressRunnable);
                    int scrollDelta = (int) (-dy / dpToPx(6));
                    if (scrollDelta != 0 && inputDispatcherThread != null) {
                        inputDispatcherThread.enqueueMouseScroll(scrollDelta);
                    }
                }
                break;

            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                mainHandler.removeCallbacks(longPressRunnable);
                long duration = SystemClock.uptimeMillis() - touchDownTime;

                if (isMouseLongPressed) {
                    isMouseLongPressed = false;
                    if (inputDispatcherThread != null) {
                        inputDispatcherThread.enqueueMouseUp("left");
                    }
                } else if (action != MotionEvent.ACTION_CANCEL && !isDraggingMouse && duration < 280) {
                    long now = SystemClock.uptimeMillis();
                    if (now - lastTapTime < 280) {
                        // Двойной клик
                        if (inputDispatcherThread != null) {
                            inputDispatcherThread.enqueueMouseClick("left", true);
                        }
                        lastTapTime = 0;
                    } else {
                        // Одиночный левый клик
                        if (inputDispatcherThread != null) {
                            inputDispatcherThread.enqueueMouseClick("left", false);
                        }
                        lastTapTime = now;
                    }
                }
                break;

            case MotionEvent.ACTION_POINTER_UP:
                mainHandler.removeCallbacks(longPressRunnable);
                if (activePointerCount == 2 && !isDraggingMouse) {
                    // Касание двумя пальцами — Правый клик
                    if (inputDispatcherThread != null) {
                        inputDispatcherThread.enqueueMouseClick("right", false);
                    }
                }
                break;
        }
        return true;
    }

    // -----------------------------------------------------------------------
    // НЕБЛОКИРУЮЩИЙ ДИСПЕТЧЕР КОМАНД ВВОДА (InputDispatcherThread)
    // -----------------------------------------------------------------------
    private static class InputCmd {
        String json;
        float relDx, relDy;
        boolean isCoalescedMove = false;
    }

    private class InputDispatcherThread extends Thread {
        private final LinkedBlockingQueue<InputCmd> queue = new LinkedBlockingQueue<>(250);
        private final AtomicBoolean running = new AtomicBoolean(true);
        private HttpURLConnection keepAliveConn = null;

        public InputDispatcherThread() {
            super("pc-control-input-dispatcher");
        }

        public void enqueueMouseMoveRel(float dx, float dy, float sens, boolean accel) {
            InputCmd cmd = new InputCmd();
            cmd.relDx = dx;
            cmd.relDy = dy;
            cmd.isCoalescedMove = true;
            cmd.json = "{\"action\":\"move_rel\",\"dx\":" + dx + ",\"dy\":" + dy + ",\"sensitivity\":" + sens + ",\"accel\":" + accel + "}";
            queue.offer(cmd);
        }

        public void enqueueMouseMoveNorm(float nx, float ny, int mon) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"move_norm\",\"x\":" + nx + ",\"y\":" + ny + ",\"monitor\":" + mon + "}";
            queue.offer(cmd);
        }

        public void enqueueMouseClick(String btn, boolean dbl) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"" + (dbl ? "double_click" : "click") + "\",\"button\":\"" + btn + "\"}";
            queue.offer(cmd);
        }

        public void enqueueMouseDown(String btn) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"down\",\"button\":\"" + btn + "\"}";
            queue.offer(cmd);
        }

        public void enqueueMouseUp(String btn) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"up\",\"button\":\"" + btn + "\"}";
            queue.offer(cmd);
        }

        public void enqueueMouseScroll(int dy) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"scroll\",\"dy\":" + dy + "}";
            queue.offer(cmd);
        }

        public void enqueueKeyPress(String key) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"key_press\",\"key\":\"" + key + "\"}";
            queue.offer(cmd);
        }

        public void enqueueKeyModifier(String key, boolean down) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"" + (down ? "key_down" : "key_up") + "\",\"key\":\"" + key + "\"}";
            queue.offer(cmd);
        }

        public void enqueueUnicodeText(String text) {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"text\",\"text\":\"" + text.replace("\"", "\\\"") + "\"}";
            queue.offer(cmd);
        }

        public void enqueueReleaseAll() {
            InputCmd cmd = new InputCmd();
            cmd.json = "{\"action\":\"release_all\"}";
            queue.offer(cmd);
        }

        @Override
        public void run() {
            while (running.get()) {
                try {
                    InputCmd cmd = queue.poll(500, TimeUnit.MILLISECONDS);
                    if (cmd == null) continue;

                    // Коалесцирование быстрых перемещений мыши: объединяем накопившиеся дельты
                    if (cmd.isCoalescedMove) {
                        float sumDx = cmd.relDx;
                        float sumDy = cmd.relDy;
                        while (!queue.isEmpty()) {
                            InputCmd next = queue.peek();
                            if (next != null && next.isCoalescedMove) {
                                queue.poll();
                                sumDx += next.relDx;
                                sumDy += next.relDy;
                            } else {
                                break;
                            }
                        }
                        cmd.json = "{\"action\":\"move_rel\",\"dx\":" + sumDx + ",\"dy\":" + sumDy + ",\"sensitivity\":" + mouseSensitivity + ",\"accel\":" + mouseAccel + "}";
                    }

                    sendJson(cmd.json);
                } catch (InterruptedException e) {
                    break;
                } catch (Exception ignored) {}
            }
        }

        private void sendJson(String json) {
            if (serverUrl == null || serverUrl.isEmpty()) return;
            try {
                String targetPath = json.contains("\"text\"") || json.contains("\"key_") || json.contains("\"hotkey\"")
                        ? "/api/keyboard"
                        : "/api/mouse";

                URL u = new URL(serverUrl + targetPath);
                HttpURLConnection c = (HttpURLConnection) u.openConnection();
                c.setRequestMethod("POST");
                c.setConnectTimeout(400);
                c.setReadTimeout(400);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("Connection", "keep-alive");
                if (!authToken.isEmpty()) {
                    c.setRequestProperty("X-Auth-Token", authToken);
                }

                byte[] body = json.getBytes(StandardCharsets.UTF_8);
                c.setFixedLengthStreamingMode(body.length);
                try (OutputStream os = c.getOutputStream()) {
                    os.write(body);
                    os.flush();
                }
                c.getResponseCode();
                c.disconnect();
            } catch (Exception ignored) {}
        }

        public void shutdown() {
            running.set(false);
            interrupt();
        }
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

    private void startMicStreaming() {
        MainActivity act = MainActivity.getInstance();
        if (act != null && !act.checkOrRequestRecordAudioPermission()) {
            Toast.makeText(getContext(), "Требуется разрешение на запись звука", Toast.LENGTH_SHORT).show();
            return;
        }

        synchronized (micLock) {
            if (isMicStreaming) return;
            isMicStreaming = true;
            updateQuickActionStates();

            micSenderThread = new MicSenderThread();
            micSenderThread.start();
        }
        Toast.makeText(getContext(), "Подключение микрофона к ПК...", Toast.LENGTH_SHORT).show();
    }

    private void stopMicStreaming() {
        synchronized (micLock) {
            isMicStreaming = false;
            if (micSenderThread != null) {
                micSenderThread.shutdown();
                micSenderThread = null;
            }
            updateQuickActionStates();
        }
    }

    private class MicSenderThread extends Thread {
        private final AtomicBoolean active = new AtomicBoolean(true);
        private AudioRecord recorder = null;

        public MicSenderThread() {
            super("pc-control-mic-sender");
        }

        @Override
        public void run() {
            int sampleRate = 16000;
            int channelConfig = AudioFormat.CHANNEL_IN_MONO;
            int audioFormat = AudioFormat.ENCODING_PCM_16BIT;
            int bufferSize = Math.max(AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat) * 2, 2048);

            try {
                recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, sampleRate, channelConfig, audioFormat, bufferSize);
                if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                    post(new Runnable() {
                        @Override public void run() { stopMicStreaming(); }
                    });
                    return;
                }
                recorder.startRecording();

                URL url = new URL(serverUrl + "/api/mic/stream?rate=" + sampleRate + "&channels=1");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setChunkedStreamingMode(1024);
                conn.setRequestProperty("Content-Type", "application/octet-stream");
                if (!authToken.isEmpty()) {
                    conn.setRequestProperty("X-Auth-Token", authToken);
                }

                try (OutputStream os = conn.getOutputStream()) {
                    byte[] buf = new byte[1024];
                    while (active.get() && isStreaming.get()) {
                        int read = recorder.read(buf, 0, buf.length);
                        if (read > 0) {
                            os.write(buf, 0, read);
                            os.flush();
                        }
                    }
                }
                int code = conn.getResponseCode();
                if (code == 200) {
                    post(new Runnable() {
                        @Override public void run() {
                            Toast.makeText(getContext(), "Микрофон успешно передан на ПК", Toast.LENGTH_SHORT).show();
                        }
                    });
                }
                conn.disconnect();
            } catch (Exception e) {
                final String errStr = (e.getMessage() != null && e.getMessage().contains("400"))
                        ? "На ПК требуется VB-CABLE для микрофона"
                        : "Сбой передачи микрофона на ПК";
                post(new Runnable() {
                    @Override public void run() {
                        stopMicStreaming();
                        Toast.makeText(getContext(), errStr, Toast.LENGTH_LONG).show();
                    }
                });
            } finally {
                if (recorder != null) {
                    try {
                        recorder.stop();
                        recorder.release();
                    } catch (Exception ignored) {}
                    recorder = null;
                }
            }
        }

        public void shutdown() {
            active.set(false);
            interrupt();
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
            int sampleRate = 48000;
            int channelConfig = AudioFormat.CHANNEL_OUT_STEREO;
            int audioFormat = AudioFormat.ENCODING_PCM_16BIT;
            int minBufSize = AudioTrack.getMinBufferSize(sampleRate, channelConfig, audioFormat);
            int bufSize = Math.max(minBufSize * 2, 8192);

            try {
                audioTrack = new AudioTrack(
                        AudioManager.STREAM_MUSIC,
                        sampleRate,
                        channelConfig,
                        audioFormat,
                        bufSize,
                        AudioTrack.MODE_STREAM
                );
                float vol = isAudioMuted ? 0f : (audioVolume / 100.0f);
                audioTrack.setVolume(vol);
                audioTrack.play();

                updateAudioStatusOnMain("Подключение...", Color.parseColor("#38BDF8"));

                String aUrl = serverUrl + "/audio?token=" + URLEncoder.encode(authToken, "UTF-8") + "&t=" + System.currentTimeMillis();
                URL u = new URL(aUrl);
                HttpURLConnection c = (HttpURLConnection) u.openConnection();
                c.setConnectTimeout(4000);
                c.setReadTimeout(10000);
                c.setRequestProperty("Accept", "audio/wav");

                if (c.getResponseCode() != 200) {
                    updateAudioStatusOnMain("Ошибка (" + c.getResponseCode() + ")", Color.parseColor("#EF4444"));
                    return;
                }

                updateAudioStatusOnMain("Подключен (48 kHz)", Color.parseColor("#22C55E"));

                try (InputStream raw = c.getInputStream();
                     BufferedInputStream bis = new BufferedInputStream(raw, 16384)) {

                    // Пропуск 44-байтного заголовка WAV при наличии
                    bis.mark(44);
                    byte[] hdr = new byte[44];
                    int rHdr = bis.read(hdr, 0, 44);
                    if (rHdr == 44 && hdr[0] == 'R' && hdr[1] == 'I' && hdr[2] == 'F' && hdr[3] == 'F') {
                        // Заголовок пропущен
                    } else {
                        bis.reset();
                    }

                    byte[] chunk = new byte[1920];
                    long totalBytesWritten = 0;

                    while (running.get() && isStreaming.get()) {
                        int r = bis.read(chunk, 0, chunk.length);
                        if (r <= 0) break;

                        // Компенсация дрифта (порог 100 мс = 9600 сэмплов)
                        long playHead = audioTrack.getPlaybackHeadPosition();
                        long writtenFrames = totalBytesWritten / 4;
                        long latencyFrames = writtenFrames - playHead;
                        if (latencyFrames > 48000 * 0.10) {
                            audioTrack.flush();
                            totalBytesWritten = playHead * 4;
                        }

                        int written = audioTrack.write(chunk, 0, r);
                        if (written > 0) totalBytesWritten += written;
                    }
                }
                c.disconnect();
            } catch (Exception e) {
                updateAudioStatusOnMain("Отключен", Color.parseColor("#94A3B8"));
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

        public void shutdown() {
            running.set(false);
            interrupt();
        }
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
            updateAudioStatusOnMain("Выключен", Color.parseColor("#94A3B8"));
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

            kbdWidthPct = sp.getInt("kbd_w", 100);
            kbdHeightDp = sp.getInt("kbd_h", 220);
            kbdLayoutIdx = sp.getInt("kbd_layout", 0);

            gearPosX = sp.getFloat("gear_x", -1f);
            gearPosY = sp.getFloat("gear_y", -1f);
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

        applyOperatingModeUI();
        if (operatingMode == MODE_VIEW) {
            setControlsVisible(true, false);
            scheduleControlsAutoHide();
        }

        synchronized (this) {
            if (inputDispatcherThread == null || !inputDispatcherThread.isAlive()) {
                inputDispatcherThread = new InputDispatcherThread();
                inputDispatcherThread.start();
            }
        }

        if (isAudioEnabled) {
            startAudioStream();
        } else {
            updateAudioStatusOnMain("Выключен", Color.parseColor("#94A3B8"));
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

        if (inputDispatcherThread != null) {
            inputDispatcherThread.enqueueReleaseAll();
            final InputDispatcherThread idt = inputDispatcherThread;
            inputDispatcherThread = null;
            mainHandler.postDelayed(new Runnable() {
                @Override public void run() {
                    idt.shutdown();
                }
            }, 250);
        }

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
            fullscreenBtn.setText(isFullscreen ? "⊡" : "⛶");
        }
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

                    feedDecoder(frameBuf, payloadLen, flags, ptsUs);
                    drainDecoder(false);
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
            decoder = MediaCodec.createDecoderByType("video/avc");
            MediaFormat format = MediaFormat.createVideoFormat("video/avc", videoWidth, videoHeight);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                format.setInteger(MediaFormat.KEY_OPERATING_RATE, Short.MAX_VALUE);
                format.setInteger(MediaFormat.KEY_PRIORITY, 0);
            }
            decoder.configure(format, surfaceHolder.getSurface(), null, 0);
            decoder.setVideoScalingMode(MediaCodec.VIDEO_SCALING_MODE_SCALE_TO_FIT);
            decoder.start();
        }
    }

    private void releaseDecoder() {
        synchronized (decoderLock) {
            if (decoder != null) {
                try {
                    decoder.stop();
                    decoder.release();
                } catch (Exception ignored) {}
                decoder = null;
            }
        }
    }

    private void feedDecoder(byte[] data, int length, int flags, long ptsUs) {
        synchronized (decoderLock) {
            if (decoder == null) return;
            try {
                int inIdx = decoder.dequeueInputBuffer(4000);
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

    private void drainDecoder(boolean endOfStream) {
        synchronized (decoderLock) {
            if (decoder == null) return;
            try {
                MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
                while (true) {
                    int outIdx = decoder.dequeueOutputBuffer(info, 1500);
                    if (outIdx >= 0) {
                        decoder.releaseOutputBuffer(outIdx, true);
                        renderedFpsTracker.recordEvent();
                        minFpsTracker.recordEvent();
                    } else if (outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        MediaFormat f = decoder.getOutputFormat();
                        if (f.containsKey(MediaFormat.KEY_WIDTH) && f.containsKey(MediaFormat.KEY_HEIGHT)) {
                            videoWidth = f.getInteger(MediaFormat.KEY_WIDTH);
                            videoHeight = f.getInteger(MediaFormat.KEY_HEIGHT);
                            post(new Runnable() {
                                @Override public void run() { requestLayout(); }
                            });
                        }
                    } else {
                        break;
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
    }

    // -----------------------------------------------------------------------
    // ПОСТРОЕНИЕ ТУЛБАРА, ДИАГНОСТИКИ И ОШИБОК
    // -----------------------------------------------------------------------
    private void buildTopToolbar(Context context) {
        topToolbar = new LinearLayout(context);
        topToolbar.setOrientation(LinearLayout.HORIZONTAL);
        topToolbar.setGravity(Gravity.CENTER_VERTICAL);

        GradientDrawable tbBg = new GradientDrawable();
        tbBg.setColor(Color.parseColor("#E612161F"));
        tbBg.setCornerRadius(dpToPx(24));
        tbBg.setStroke(dpToPx(1), Color.parseColor("#33FFFFFF"));
        topToolbar.setBackground(tbBg);

        int padH = dpToPx(16);
        int padV = dpToPx(8);
        topToolbar.setPadding(padH, padV, padH, padV);

        FrameLayout.LayoutParams tbParams = new FrameLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        tbParams.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        tbParams.topMargin = dpToPx(16);
        topToolbar.setLayoutParams(tbParams);

        TextView backBtn = createToolbarButton(context, "←", "#242A35", Color.WHITE, 17f);
        backBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeStreamAndExit(); }
        });
        topToolbar.addView(backBtn);

        LinearLayout titleBox = new LinearLayout(context);
        titleBox.setOrientation(LinearLayout.VERTICAL);
        titleBox.setPadding(dpToPx(12), 0, dpToPx(14), 0);
        titleBox.setGravity(Gravity.CENTER_VERTICAL);

        titleView = new TextView(context);
        titleView.setText("Демонстрация экрана");
        titleView.setTextColor(Color.WHITE);
        titleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f);
        titleView.setTypeface(Typeface.DEFAULT_BOLD);
        titleBox.addView(titleView);

        subtitleView = new TextView(context);
        subtitleView.setText("1080p · 60 FPS");
        subtitleView.setTextColor(Color.parseColor("#94A3B8"));
        subtitleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        titleBox.addView(subtitleView);
        topToolbar.addView(titleBox);

        scaleModeBtn = createToolbarButton(context, "Fit", "#242A35", Color.parseColor("#E2E8F0"), 13f);
        scaleModeBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleScaleMode(); }
        });
        topToolbar.addView(scaleModeBtn);

        addToolbarSpacer(context, topToolbar, 8);

        fullscreenBtn = createToolbarButton(context, "⛶", "#242A35", Color.WHITE, 17f);
        fullscreenBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleFullscreen(); }
        });
        topToolbar.addView(fullscreenBtn);

        addToolbarSpacer(context, topToolbar, 8);

        settingsBtn = createToolbarButton(context, "⚙", "#242A35", Color.WHITE, 17f);
        settingsBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { toggleSplitSettings(); }
        });
        topToolbar.addView(settingsBtn);

        addToolbarSpacer(context, topToolbar, 8);

        closeBtn = createToolbarButton(context, "✕", "#3A2024", Color.parseColor("#FF5252"), 17f);
        closeBtn.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeStreamAndExit(); }
        });
        topToolbar.addView(closeBtn);

        addView(topToolbar);
    }

    private TextView createToolbarButton(Context context, String text, String bgColorHex, int textColor, float textSizeSp) {
        TextView btn = new TextView(context);
        btn.setText(text);
        btn.setTextColor(textColor);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSizeSp);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setGravity(Gravity.CENTER);
        btn.setMinWidth(dpToPx(48));
        btn.setMinHeight(dpToPx(48));

        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor(bgColorHex));
        bg.setCornerRadius(dpToPx(14));
        btn.setBackground(bg);
        int pad = dpToPx(8);
        btn.setPadding(pad, pad, pad, pad);
        return btn;
    }

    private void addToolbarSpacer(Context context, LinearLayout parent, int dp) {
        View sp = new View(context);
        parent.addView(sp, new LinearLayout.LayoutParams(dpToPx(dp), 1));
    }

    private TextView createChipButton(Context context, String text, final Runnable onClick) {
        TextView chip = new TextView(context);
        chip.setText(text);
        chip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f);
        chip.setTypeface(Typeface.DEFAULT_BOLD);
        chip.setGravity(Gravity.CENTER);
        chip.setTextColor(Color.parseColor("#CBD5E1"));
        chip.setMinWidth(dpToPx(48));
        chip.setMinHeight(dpToPx(48));
        int pad = dpToPx(8);
        chip.setPadding(pad, pad, pad, pad);

        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor("#1E2530"));
        gd.setCornerRadius(dpToPx(12));
        gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
        chip.setBackground(gd);

        chip.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { if (onClick != null) onClick.run(); }
        });
        return chip;
    }

    private void setChipActive(TextView chip, boolean active) {
        if (chip == null) return;
        GradientDrawable gd = new GradientDrawable();
        gd.setCornerRadius(dpToPx(12));
        if (active) {
            gd.setColor(Color.parseColor("#0C4A6E"));
            gd.setStroke(dpToPx(1), Color.parseColor("#38BDF8"));
            chip.setTextColor(Color.parseColor("#38BDF8"));
        } else {
            gd.setColor(Color.parseColor("#1E2530"));
            gd.setStroke(dpToPx(1), Color.parseColor("#334155"));
            chip.setTextColor(Color.parseColor("#CBD5E1"));
        }
        chip.setBackground(gd);
    }

    private void addSectionHeader(Context context, LinearLayout parent, String text) {
        TextView label = new TextView(context);
        label.setText(text);
        label.setTextColor(Color.parseColor("#94A3B8"));
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f);
        label.setTypeface(Typeface.DEFAULT_BOLD);
        label.setPadding(0, dpToPx(4), 0, dpToPx(4));
        parent.addView(label);
    }

    private void addDivider(Context context, LinearLayout parent) {
        View d = new View(context);
        d.setBackgroundColor(Color.parseColor("#22334155"));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dpToPx(1));
        lp.setMargins(0, dpToPx(10), 0, dpToPx(10));
        d.setLayoutParams(lp);
        parent.addView(d);
    }

    private void buildDiagnosticsDialog(Context context) {
        diagOverlay = new FrameLayout(context);
        diagOverlay.setBackgroundColor(Color.parseColor("#80000000"));
        diagOverlay.setVisibility(View.GONE);

        diagCard = new LinearLayout(context);
        diagCard.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#EE121622"));
        bg.setCornerRadius(dpToPx(16));
        bg.setStroke(dpToPx(1), Color.parseColor("#334155"));
        diagCard.setBackground(bg);
        int pad = dpToPx(16);
        diagCard.setPadding(pad, pad, pad, pad);

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dpToPx(340), LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        diagCard.setLayoutParams(lp);

        TextView head = new TextView(context);
        head.setText("📊 ТЕЛЕМЕТРИЯ ПОТОКА");
        head.setTextColor(Color.parseColor("#38BDF8"));
        head.setTypeface(Typeface.DEFAULT_BOLD);
        diagCard.addView(head);

        diagFpsRendVal = addDiagRow(context, diagCard, "FPS Отрисовки:");
        diagFpsRecvVal = addDiagRow(context, diagCard, "FPS Приёма:");
        diagBitrateVal = addDiagRow(context, diagCard, "Битрейт:");
        diagResVal = addDiagRow(context, diagCard, "Разрешение:");

        TextView closeDiag = createToolbarButton(context, "Закрыть", "#242A35", Color.WHITE, 12f);
        closeDiag.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { setDiagnosticsVisible(false); }
        });
        diagCard.addView(closeDiag);

        diagOverlay.addView(diagCard);
        addView(diagOverlay, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    private TextView addDiagRow(Context context, LinearLayout parent, String label) {
        LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        TextView l = new TextView(context);
        l.setText(label);
        l.setTextColor(Color.parseColor("#94A3B8"));
        TextView v = new TextView(context);
        v.setTextColor(Color.WHITE);
        v.setTypeface(Typeface.MONOSPACE);
        row.addView(l, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1.0f));
        row.addView(v);
        parent.addView(row);
        return v;
    }

    private void refreshDiagValues() {
        if (diagFpsRendVal != null) diagFpsRendVal.setText(String.format("%.1f", renderedFpsTracker.getFps()));
        if (diagFpsRecvVal != null) diagFpsRecvVal.setText(String.format("%.1f", receivedFpsTracker.getFps()));
        if (diagResVal != null) diagResVal.setText(videoWidth + "x" + videoHeight);
    }

    public void setDiagnosticsVisible(boolean visible) {
        isDiagVisible = visible;
        if (diagOverlay != null) diagOverlay.setVisibility(visible ? View.VISIBLE : View.GONE);
        if (visible) {
            mainHandler.post(diagUpdateRunnable);
        } else {
            mainHandler.removeCallbacks(diagUpdateRunnable);
        }
    }

    private void buildErrorDialog(Context context) {
        errorOverlay = new FrameLayout(context);
        errorOverlay.setBackgroundColor(Color.parseColor("#B3000000"));
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

        if (customKeyboardView != null && customKeyboardView.getVisibility() != View.GONE) {
            int kWidth = (int) (widthSize * (kbdWidthPct / 100f));
            customKeyboardView.measure(MeasureSpec.makeMeasureSpec(kWidth, MeasureSpec.EXACTLY),
                    MeasureSpec.makeMeasureSpec(dpToPx(kbdHeightDp), MeasureSpec.EXACTLY));
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
            // Гарантируем, что плавающие кнопки никогда не уйдут за экран при повороте телефона
            float defX = (gearPosX >= 0)
                    ? Math.min(parentW - gW - dpToPx(8), Math.max(dpToPx(8), gearPosX))
                    : (parentW - gW - dpToPx(16));
            float defY = (gearPosY >= 0)
                    ? Math.min(parentH - gH - dpToPx(8), Math.max(dpToPx(8), gearPosY))
                    : dpToPx(16);
            floatingControlsGroup.layout((int) defX, (int) defY, (int) (defX + gW), (int) (defY + gH));
        }

        if (splitSettingsContainer != null && splitSettingsContainer.getVisibility() != View.GONE) {
            int sW = splitSettingsContainer.getMeasuredWidth();
            int sH = splitSettingsContainer.getMeasuredHeight();
            // Панель настроек располагается СЛЕВА
            splitSettingsContainer.layout(0, 0, sW, sH);
        }

        if (customKeyboardView != null && customKeyboardView.getVisibility() != View.GONE) {
            int kW = customKeyboardView.getMeasuredWidth();
            int kH = customKeyboardView.getMeasuredHeight();
            int kLeft = (parentW - kW) / 2;
            customKeyboardView.layout(kLeft, parentH - kH - dpToPx(8), kLeft + kW, parentH - dpToPx(8));
        }

        if (diagOverlay != null && diagOverlay.getVisibility() != View.GONE) {
            diagOverlay.layout(0, 0, parentW, parentH);
        }
        if (errorOverlay != null && errorOverlay.getVisibility() != View.GONE) {
            errorOverlay.layout(0, 0, parentW, parentH);
        }
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
