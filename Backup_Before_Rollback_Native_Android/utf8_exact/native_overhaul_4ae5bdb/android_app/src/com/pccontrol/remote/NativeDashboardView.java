package com.pccontrol.remote;

import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * NativeDashboardView - Нативный главный экран управления PC Control.
 * Полностью автономен от WebView, спроектирован в едином дизайн-коде PC Control:
 * - Глубокий тёмный фон #030303
 * - Карточки #121212 с бордером #1E2530 и скруглением 16dp
 * - Акцентный неоново-голубой цвет #38BDF8
 * - Сенсорные области от 48x48 dp
 * - Управление питанием, медиаплеером, громкостью и быстрым переходом в режимы
 */
public class NativeDashboardView extends ScrollView {

    private final LinearLayout container;
    private final ApiClient apiClient;

    private TextView statusPillText;
    private View statusIndicatorDot;
    private TextView serverAddressText;
    private SeekBar volumeSeekBar;
    private TextView volumePercentText;
    private Button btnMute;

    private DashboardCallback callback;
    private boolean isUpdatingVolumeFromNet = false;

    public interface DashboardCallback {
        void onStartPcControlRequested();
        void onStartScreenRequested();
        void onOpenWebViewRequested();
    }

    public NativeDashboardView(Context context) {
        super(context);
        this.apiClient = ApiClient.getInstance(context);

        setBackgroundColor(Color.parseColor("#030303"));
        setFillViewport(true);
        setVerticalScrollBarEnabled(false);

        container = new LinearLayout(context);
        container.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        container.setPadding(pad, pad, pad, dp(32));

        addView(container, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        buildHeader();
        buildHeroCards();
        buildVolumeAndMediaCard();
        buildPowerCard();
        buildQuickActionsCard();

        refreshStatus();
    }

    public void setCallback(DashboardCallback callback) {
        this.callback = callback;
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return (int) (value * density + 0.5f);
    }

    private GradientDrawable createCardBg(String bgColor, String borderColor, int radiusDp) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor(bgColor));
        if (borderColor != null) {
            gd.setStroke(dp(1), Color.parseColor(borderColor));
        }
        gd.setCornerRadius(dp(radiusDp));
        return gd;
    }

    private Button createStyledButton(String text, String bgColor, String textColor, int heightDp) {
        Button btn = new Button(getContext());
        btn.setText(text);
        btn.setTextColor(Color.parseColor(textColor));
        btn.setTextSize(14);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setAllCaps(false);
        btn.setGravity(Gravity.CENTER);
        btn.setMinHeight(dp(Math.max(48, heightDp)));

        GradientDrawable normalBg = createCardBg(bgColor, "#2A3649", 12);
        btn.setBackground(normalBg);
        return btn;
    }

    // --- 1. ШАПКА И СТАТУС СЕРВЕРА ---
    private void buildHeader() {
        LinearLayout headerCard = new LinearLayout(getContext());
        headerCard.setOrientation(LinearLayout.VERTICAL);
        headerCard.setBackground(createCardBg("#121212", "#1E2530", 16));
        int pad = dp(16);
        headerCard.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(16);
        headerCard.setLayoutParams(lp);

        // Верхний ряд: Название и кнопки управления
        LinearLayout topRow = new LinearLayout(getContext());
        topRow.setOrientation(LinearLayout.HORIZONTAL);
        topRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(getContext());
        title.setText("PC CONTROL");
        title.setTextColor(Color.parseColor("#F8FAFC"));
        title.setTextSize(19);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        topRow.addView(title, titleLp);

        // Кнопка Обновить
        Button btnRefresh = createStyledButton("⟲", "#1A222D", "#38BDF8", 40);
        btnRefresh.setTextSize(16);
        LinearLayout.LayoutParams refLp = new LinearLayout.LayoutParams(dp(44), dp(44));
        refLp.rightMargin = dp(8);
        btnRefresh.setLayoutParams(refLp);
        btnRefresh.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                refreshStatus();
            }
        });
        topRow.addView(btnRefresh);

        // Кнопка Настройки подключения
        Button btnSettings = createStyledButton("⚙", "#1A222D", "#F8FAFC", 40);
        btnSettings.setTextSize(16);
        LinearLayout.LayoutParams setLp = new LinearLayout.LayoutParams(dp(44), dp(44));
        btnSettings.setLayoutParams(setLp);
        btnSettings.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                showServerConfigDialog();
            }
        });
        topRow.addView(btnSettings);

        headerCard.addView(topRow);

        // Нижний ряд: Статус-пилл и текущий адрес
        LinearLayout statusRow = new LinearLayout(getContext());
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        statusRow.setGravity(Gravity.CENTER_VERTICAL);
        statusRow.setPadding(0, dp(12), 0, 0);

        statusIndicatorDot = new View(getContext());
        GradientDrawable dotBg = new GradientDrawable();
        dotBg.setShape(GradientDrawable.OVAL);
        dotBg.setColor(Color.parseColor("#F59E0B")); // Исходно желтый (поиск)
        statusIndicatorDot.setBackground(dotBg);
        LinearLayout.LayoutParams dotLp = new LinearLayout.LayoutParams(dp(10), dp(10));
        dotLp.rightMargin = dp(8);
        statusRow.addView(statusIndicatorDot, dotLp);

        statusPillText = new TextView(getContext());
        statusPillText.setText("Подключение к ПК...");
        statusPillText.setTextColor(Color.parseColor("#94A3B8"));
        statusPillText.setTextSize(13);
        statusRow.addView(statusPillText);

        headerCard.addView(statusRow);

        serverAddressText = new TextView(getContext());
        serverAddressText.setText(apiClient.getServerUrl());
        serverAddressText.setTextColor(Color.parseColor("#64748B"));
        serverAddressText.setTextSize(11);
        serverAddressText.setPadding(dp(18), dp(4), 0, 0);
        headerCard.addView(serverAddressText);

        container.addView(headerCard);
    }

    // --- 2. ГЛАВНЫЕ РЕЖИМЫ (УПРАВЛЕНИЕ ПК И ДЕМОНСТРАЦИЯ) ---
    private void buildHeroCards() {
        // КАРТА 1: УПРАВЛЕНИЕ ПК (Главная фича)
        LinearLayout pcControlHero = new LinearLayout(getContext());
        pcControlHero.setOrientation(LinearLayout.VERTICAL);
        pcControlHero.setBackground(createCardBg("#161D26", "#38BDF8", 16));
        int pad = dp(16);
        pcControlHero.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams pcLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        pcLp.bottomMargin = dp(12);
        pcControlHero.setLayoutParams(pcLp);

        LinearLayout titleRow = new LinearLayout(getContext());
        titleRow.setOrientation(LinearLayout.HORIZONTAL);
        titleRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView icon = new TextView(getContext());
        icon.setText("🎮 ");
        icon.setTextSize(18);
        titleRow.addView(icon);

        TextView heroTitle = new TextView(getContext());
        heroTitle.setText("Управление ПК");
        heroTitle.setTextColor(Color.parseColor("#38BDF8"));
        heroTitle.setTextSize(17);
        heroTitle.setTypeface(Typeface.DEFAULT_BOLD);
        titleRow.addView(heroTitle);

        TextView badge = new TextView(getContext());
        badge.setText("  ИНТЕРАКТИВНЫЙ ПУЛЬТ");
        badge.setTextColor(Color.parseColor("#94A3B8"));
        badge.setTextSize(10);
        titleRow.addView(badge);

        pcControlHero.addView(titleRow);

        TextView heroDesc = new TextView(getContext());
        heroDesc.setText("Прозрачный настраиваемый тачпад, кастомная клавиатура, звук Windows и микрофон.");
        heroDesc.setTextColor(Color.parseColor("#CBD5E1"));
        heroDesc.setTextSize(12);
        heroDesc.setPadding(0, dp(6), 0, dp(12));
        pcControlHero.addView(heroDesc);

        Button btnStartPc = createStyledButton("Запустить Управление ПК ▶", "#38BDF8", "#030303", 52);
        btnStartPc.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (callback != null) callback.onStartPcControlRequested();
            }
        });
        pcControlHero.addView(btnStartPc);

        container.addView(pcControlHero);

        // КАРТА 2: ДЕМОНСТРАЦИЯ ЭКРАНА (Moonlight просмотр)
        LinearLayout screenHero = new LinearLayout(getContext());
        screenHero.setOrientation(LinearLayout.VERTICAL);
        screenHero.setBackground(createCardBg("#121212", "#1E2530", 16));
        screenHero.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams scLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        scLp.bottomMargin = dp(16);
        screenHero.setLayoutParams(scLp);

        LinearLayout scTitleRow = new LinearLayout(getContext());
        scTitleRow.setOrientation(LinearLayout.HORIZONTAL);
        scTitleRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView scIcon = new TextView(getContext());
        scIcon.setText("🖥️ ");
        scIcon.setTextSize(18);
        scTitleRow.addView(scIcon);

        TextView scTitle = new TextView(getContext());
        scTitle.setText("Демонстрация экрана");
        scTitle.setTextColor(Color.parseColor("#F8FAFC"));
        scTitle.setTextSize(17);
        scTitle.setTypeface(Typeface.DEFAULT_BOLD);
        scTitleRow.addView(scTitle);

        TextView scBadge = new TextView(getContext());
        scBadge.setText("  60 FPS MEDIACODEC");
        scBadge.setTextColor(Color.parseColor("#64748B"));
        scBadge.setTextSize(10);
        scTitleRow.addView(scBadge);

        screenHero.addView(scTitleRow);

        TextView scDesc = new TextView(getContext());
        scDesc.setText("Аппаратный просмотр экрана компьютера в реальном времени с передачей звука.");
        scDesc.setTextColor(Color.parseColor("#94A3B8"));
        scDesc.setTextSize(12);
        scDesc.setPadding(0, dp(6), 0, dp(12));
        screenHero.addView(scDesc);

        Button btnStartSc = createStyledButton("Открыть демонстрацию ▶", "#1A222D", "#F8FAFC", 48);
        btnStartSc.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (callback != null) callback.onStartScreenRequested();
            }
        });
        screenHero.addView(btnStartSc);

        container.addView(screenHero);
    }

    // --- 3. ГРОМКОСТЬ И МЕДИА ---
    private void buildVolumeAndMediaCard() {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(createCardBg("#121212", "#1E2530", 16));
        int pad = dp(16);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(16);
        card.setLayoutParams(lp);

        TextView secTitle = new TextView(getContext());
        secTitle.setText("ГРОМКОСТЬ И МЕДИА");
        secTitle.setTextColor(Color.parseColor("#64748B"));
        secTitle.setTextSize(12);
        secTitle.setTypeface(Typeface.DEFAULT_BOLD);
        card.addView(secTitle);

        // Ползунок громкости
        LinearLayout volRow = new LinearLayout(getContext());
        volRow.setOrientation(LinearLayout.HORIZONTAL);
        volRow.setGravity(Gravity.CENTER_VERTICAL);
        volRow.setPadding(0, dp(12), 0, dp(16));

        TextView spkIcon = new TextView(getContext());
        spkIcon.setText("🔊");
        spkIcon.setTextSize(18);
        volRow.addView(spkIcon);

        volumeSeekBar = new SeekBar(getContext());
        volumeSeekBar.setMax(100);
        volumeSeekBar.setProgress(50);
        LinearLayout.LayoutParams sbLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        sbLp.leftMargin = dp(8);
        sbLp.rightMargin = dp(8);
        volumeSeekBar.setLayoutParams(sbLp);
        volumeSeekBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (fromUser) {
                    volumePercentText.setText(progress + "%");
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                if (!isUpdatingVolumeFromNet) {
                    apiClient.setVolume(seekBar.getProgress(), null);
                }
            }
        });
        volRow.addView(volumeSeekBar);

        volumePercentText = new TextView(getContext());
        volumePercentText.setText("50%");
        volumePercentText.setTextColor(Color.parseColor("#38BDF8"));
        volumePercentText.setTextSize(14);
        volumePercentText.setTypeface(Typeface.DEFAULT_BOLD);
        volRow.addView(volumePercentText);

        card.addView(volRow);

        // Кнопки медиауправления
        LinearLayout mediaRow = new LinearLayout(getContext());
        mediaRow.setOrientation(LinearLayout.HORIZONTAL);

        Button btnPrev = createStyledButton("⏮", "#1A222D", "#F8FAFC", 48);
        btnPrev.setTextSize(18);
        LinearLayout.LayoutParams btnLp1 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnLp1.rightMargin = dp(6);
        btnPrev.setLayoutParams(btnLp1);
        btnPrev.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.mediaControl("prev", null);
            }
        });
        mediaRow.addView(btnPrev);

        Button btnPlay = createStyledButton("⏯", "#1A222D", "#38BDF8", 48);
        btnPlay.setTextSize(18);
        LinearLayout.LayoutParams btnLp2 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnLp2.rightMargin = dp(6);
        btnPlay.setLayoutParams(btnLp2);
        btnPlay.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.mediaControl("play_pause", null);
            }
        });
        mediaRow.addView(btnPlay);

        Button btnNext = createStyledButton("⏭", "#1A222D", "#F8FAFC", 48);
        btnNext.setTextSize(18);
        LinearLayout.LayoutParams btnLp3 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnLp3.rightMargin = dp(6);
        btnNext.setLayoutParams(btnLp3);
        btnNext.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.mediaControl("next", null);
            }
        });
        mediaRow.addView(btnNext);

        btnMute = createStyledButton("🔇", "#1A222D", "#F8FAFC", 48);
        btnMute.setTextSize(18);
        LinearLayout.LayoutParams btnLp4 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnMute.setLayoutParams(btnLp4);
        btnMute.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.toggleMute(new ApiClient.ApiCallback() {
                    @Override
                    public void onSuccess(JSONObject response) {
                        refreshVolume();
                    }

                    @Override
                    public void onError(String error, int statusCode) {}
                });
            }
        });
        mediaRow.addView(btnMute);

        card.addView(mediaRow);
        container.addView(card);
    }

    // --- 4. УПРАВЛЕНИЕ ПИТАНИЕМ ---
    private void buildPowerCard() {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(createCardBg("#121212", "#1E2530", 16));
        int pad = dp(16);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(16);
        card.setLayoutParams(lp);

        TextView secTitle = new TextView(getContext());
        secTitle.setText("УПРАВЛЕНИЕ ПИТАНИЕМ");
        secTitle.setTextColor(Color.parseColor("#64748B"));
        secTitle.setTextSize(12);
        secTitle.setTypeface(Typeface.DEFAULT_BOLD);
        secTitle.setPadding(0, 0, 0, dp(12));
        card.addView(secTitle);

        // Ряд 1: Сон и Блокировка
        LinearLayout row1 = new LinearLayout(getContext());
        row1.setOrientation(LinearLayout.HORIZONTAL);
        row1.setPadding(0, 0, 0, dp(8));

        Button btnSleep = createStyledButton("💤 Сон", "#1A222D", "#F8FAFC", 48);
        LinearLayout.LayoutParams r1p1 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        r1p1.rightMargin = dp(6);
        btnSleep.setLayoutParams(r1p1);
        btnSleep.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmAction("Перевести компьютер в спящий режим?", "sleep");
            }
        });
        row1.addView(btnSleep);

        Button btnLock = createStyledButton("🔒 Блокировка", "#1A222D", "#F8FAFC", 48);
        LinearLayout.LayoutParams r1p2 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnLock.setLayoutParams(r1p2);
        btnLock.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.powerAction("lock", new ApiClient.ApiCallback() {
                    @Override
                    public void onSuccess(JSONObject response) {
                        Toast.makeText(getContext(), "ПК заблокирован", Toast.LENGTH_SHORT).show();
                    }

                    @Override
                    public void onError(String error, int statusCode) {
                        Toast.makeText(getContext(), "Ошибка: " + error, Toast.LENGTH_SHORT).show();
                    }
                });
            }
        });
        row1.addView(btnLock);

        card.addView(row1);

        // Ряд 2: Перезагрузка и Выключение
        LinearLayout row2 = new LinearLayout(getContext());
        row2.setOrientation(LinearLayout.HORIZONTAL);

        Button btnReboot = createStyledButton("🔄 Перезагрузка", "#1A222D", "#F59E0B", 48);
        LinearLayout.LayoutParams r2p1 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        r2p1.rightMargin = dp(6);
        btnReboot.setLayoutParams(r2p1);
        btnReboot.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmAction("Перезагрузить компьютер сейчас?", "reboot");
            }
        });
        row2.addView(btnReboot);

        Button btnShutdown = createStyledButton("⏻ Выключение", "#261517", "#EF4444", 48);
        LinearLayout.LayoutParams r2p2 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnShutdown.setLayoutParams(r2p2);
        btnShutdown.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmAction("Выключить компьютер?", "shutdown");
            }
        });
        row2.addView(btnShutdown);

        card.addView(row2);
        container.addView(card);
    }

    // --- 5. БЫСТРЫЕ ДЕЙСТВИЯ ---
    private void buildQuickActionsCard() {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(createCardBg("#121212", "#1E2530", 16));
        int pad = dp(16);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        card.setLayoutParams(lp);

        TextView secTitle = new TextView(getContext());
        secTitle.setText("БЫСТРЫЕ ДЕЙСТВИЯ WINDOWS");
        secTitle.setTextColor(Color.parseColor("#64748B"));
        secTitle.setTextSize(12);
        secTitle.setTypeface(Typeface.DEFAULT_BOLD);
        secTitle.setPadding(0, 0, 0, dp(12));
        card.addView(secTitle);

        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);

        Button btnWinD = createStyledButton("⊞ Свернуть всё", "#1A222D", "#F8FAFC", 48);
        LinearLayout.LayoutParams b1 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        b1.rightMargin = dp(6);
        btnWinD.setLayoutParams(b1);
        btnWinD.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.keyboardHotkey(new String[]{"win", "d"}, null);
            }
        });
        row.addView(btnWinD);

        Button btnTaskMgr = createStyledButton("📋 Диспетчер", "#1A222D", "#F8FAFC", 48);
        LinearLayout.LayoutParams b2 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        b2.rightMargin = dp(6);
        btnTaskMgr.setLayoutParams(b2);
        btnTaskMgr.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                apiClient.keyboardHotkey(new String[]{"ctrl", "shift", "esc"}, null);
            }
        });
        row.addView(btnTaskMgr);

        Button btnWebTools = createStyledButton("🌐 Веб-пульт", "#1A222D", "#38BDF8", 48);
        LinearLayout.LayoutParams b3 = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        btnWebTools.setLayoutParams(b3);
        btnWebTools.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (callback != null) callback.onOpenWebViewRequested();
            }
        });
        row.addView(btnWebTools);

        card.addView(row);
        container.addView(card);
    }

    private void confirmAction(String message, final String action) {
        new AlertDialog.Builder(getContext(), AlertDialog.THEME_DEVICE_DEFAULT_DARK)
                .setTitle("Подтверждение")
                .setMessage(message)
                .setPositiveButton("Да", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        apiClient.powerAction(action, new ApiClient.ApiCallback() {
                            @Override
                            public void onSuccess(JSONObject response) {
                                Toast.makeText(getContext(), "Команда выполнена", Toast.LENGTH_SHORT).show();
                            }

                            @Override
                            public void onError(String error, int statusCode) {
                                Toast.makeText(getContext(), "Ошибка: " + error, Toast.LENGTH_SHORT).show();
                            }
                        });
                    }
                })
                .setNegativeButton("Отмена", null)
                .show();
    }

    public void refreshStatus() {
        if (serverAddressText != null) {
            serverAddressText.setText(apiClient.getServerUrl());
        }
        apiClient.checkStatus(new ApiClient.ApiCallback() {
            @Override
            public void onSuccess(JSONObject response) {
                if (statusIndicatorDot != null) {
                    GradientDrawable dot = new GradientDrawable();
                    dot.setShape(GradientDrawable.OVAL);
                    dot.setColor(Color.parseColor("#10B981")); // Зеленый
                    statusIndicatorDot.setBackground(dot);
                }
                if (statusPillText != null) {
                    String hostname = response.optString("hostname", "ПК");
                    statusPillText.setText("Подключено к " + hostname);
                    statusPillText.setTextColor(Color.parseColor("#10B981"));
                }
                refreshVolume();
            }

            @Override
            public void onError(String error, int statusCode) {
                if (statusIndicatorDot != null) {
                    GradientDrawable dot = new GradientDrawable();
                    dot.setShape(GradientDrawable.OVAL);
                    dot.setColor(Color.parseColor("#EF4444")); // Красный
                    statusIndicatorDot.setBackground(dot);
                }
                if (statusPillText != null) {
                    statusPillText.setText("Сервер недоступен (" + error + ")");
                    statusPillText.setTextColor(Color.parseColor("#EF4444"));
                }
            }
        });
    }

    private void refreshVolume() {
        apiClient.getVolume(new ApiClient.ApiCallback() {
            @Override
            public void onSuccess(JSONObject response) {
                int percent = response.optInt("percent", 50);
                boolean muted = response.optBoolean("muted", false);
                isUpdatingVolumeFromNet = true;
                if (volumeSeekBar != null) volumeSeekBar.setProgress(percent);
                if (volumePercentText != null) volumePercentText.setText(percent + "%");
                if (btnMute != null) {
                    btnMute.setTextColor(muted ? Color.parseColor("#EF4444") : Color.parseColor("#F8FAFC"));
                }
                isUpdatingVolumeFromNet = false;
            }

            @Override
            public void onError(String error, int statusCode) {}
        });
    }

    private void showServerConfigDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(getContext(), AlertDialog.THEME_DEVICE_DEFAULT_DARK);
        builder.setTitle("Настройки подключения к ПК");

        LinearLayout layout = new LinearLayout(getContext());
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        layout.setPadding(pad, pad, pad, pad);

        TextView labelUrl = new TextView(getContext());
        labelUrl.setText("IP-адрес и порт сервера Windows:");
        labelUrl.setTextColor(Color.parseColor("#94A3B8"));
        labelUrl.setTextSize(12);
        layout.addView(labelUrl);

        final EditText editUrl = new EditText(getContext());
        editUrl.setText(apiClient.getServerUrl());
        editUrl.setTextColor(Color.parseColor("#F8FAFC"));
        editUrl.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        layout.addView(editUrl);

        TextView labelToken = new TextView(getContext());
        labelToken.setText("Пароль доступа (Токен):");
        labelToken.setTextColor(Color.parseColor("#94A3B8"));
        labelToken.setTextSize(12);
        labelToken.setPadding(0, dp(12), 0, 0);
        layout.addView(labelToken);

        final EditText editToken = new EditText(getContext());
        editToken.setText(apiClient.getAuthToken());
        editToken.setTextColor(Color.parseColor("#F8FAFC"));
        editToken.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        layout.addView(editToken);

        Button btnAutoDiscover = createStyledButton("🔍 Автопоиск в сети Wi-Fi", "#1E2530", "#38BDF8", 44);
        LinearLayout.LayoutParams adLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        adLp.topMargin = dp(16);
        btnAutoDiscover.setLayoutParams(adLp);
        btnAutoDiscover.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(final View v) {
                v.setEnabled(false);
                Toast.makeText(getContext(), "Сканирование локальной сети...", Toast.LENGTH_SHORT).show();
                apiClient.discoverServer(new ApiClient.DiscoveryCallback() {
                    @Override
                    public void onDiscovered(String foundUrl) {
                        v.setEnabled(true);
                        editUrl.setText(foundUrl);
                        Toast.makeText(getContext(), "Найден сервер: " + foundUrl, Toast.LENGTH_LONG).show();
                    }

                    @Override
                    public void onNotFound() {
                        v.setEnabled(true);
                        Toast.makeText(getContext(), "Сервер в текущей подсети не найден, введите адрес вручную", Toast.LENGTH_LONG).show();
                    }
                });
            }
        });
        layout.addView(btnAutoDiscover);

        builder.setView(layout);
        builder.setPositiveButton("Сохранить", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String newUrl = editUrl.getText().toString().trim();
                String newToken = editToken.getText().toString().trim();
                if (!newUrl.isEmpty()) {
                    apiClient.setServerUrl(newUrl);
                }
                apiClient.setAuthToken(newToken);
                refreshStatus();
            }
        });
        builder.setNegativeButton("Отмена", null);
        builder.show();
    }
}
