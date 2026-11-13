package com.pccontrol.remote;

import android.app.Activity;
import android.content.ClipData;
import android.content.BroadcastReceiver;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.IntentFilter;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.provider.Settings;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.MediaStore;
import android.text.Html;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * PC Control — fully native Android client (no WebView). One scrolling dashboard identical to the
 * web UI (header, offline banner, media player, audio & streaming, input & system, power) plus
 * modals (settings, launch routines, login, confirmations); the screen stream / PC control is the
 * native NativeScreenView. This class owns the connection state machine (web app.js ConnState),
 * the HTTP plumbing (worker threads, 401 → login), adaptive polling and the Android integration.
 */
public class MainActivity extends Activity {
    private static MainActivity instance;

    // connection state (web ConnState)
    static final int ST_CONNECTING = 0, ST_CONNECTED = 1, ST_AUTH = 2, ST_DISCONNECTED = 3;

    final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newFixedThreadPool(6);
    PcConn conn;
    PcI18n i18n;

    FrameLayout root;
    private ScrollView pageScroll;
    private LinearLayout page;
    private TextView statusText, statusMsg;
    private View statusDot;
    private LinearLayout offlineBanner;
    NativeScreenView nativeScreenView;

    PcMediaCard media;
    PcAudioCard audio;
    PcInputCard input;
    PcPowerCard power;
    PcPresets presets;
    PcSettings settings;
    PcLogin login;
    private final List<PcModal> modals = new ArrayList<>();

    int connState = ST_CONNECTING;
    private boolean statusInFlight, resumed, destroyed, pendingPair;
    private long lastMedia, lastStatus, lastLang, lastPresets, lastProc, lastVolume, nextRetryAt;
    private long retryDelay = 5000;

    // audio from the PC (buttons "Звук ПК" / "Микрофон")
    int pcAudioState = PcAudioStream.STOPPED, micAudioState = PcAudioStream.STOPPED;
    private PcAudioStream pcStream, micStream;
    private boolean resumePcAudio, resumeMic;

    // native screen
    boolean nativeMode;
    int nativeModeKind = NativeScreenView.MODE_VIEW;

    private byte[] pendingScreenshot;
    private String pendingScreenshotName, pendingScreenshotMime;
    private ConnectivityManager.NetworkCallback netCallback, anyNetCallback;
    // USB cable / route choice (PcRoute): current route kind, tethering discovery, event receiver
    volatile int routeKind = -1;
    private PcUsbLink usbLink;
    private BroadcastReceiver usbReceiver;
    private volatile Set<String> autoUrls = new LinkedHashSet<>();
    private long routeKeyMissAt;
    private String routeKeyMissUrl = "";
    private Runnable wolWait;
    private View updateDot;
    private boolean updateBadge;

    public static MainActivity getInstance() {
        return instance;
    }

    // ================================================================== lifecycle
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        instance = this;
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        Window win = getWindow();
        win.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        win.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        win.setStatusBarColor(PcViews.BG);
        win.setNavigationBarColor(PcViews.BG);
        // Фон окна темы DeviceDefault — серый (#1E1F24); он проступал по краям демонстрации.
        win.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(PcViews.BG));
        win.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);

        final SharedPreferences prefs = getSharedPreferences("pc_control", MODE_PRIVATE);
        conn = new PcConn(new PcConn.Store() {
            @Override public String get(String key) { return prefs.getString(key, null); }
            @Override public void put(String key, String value) { prefs.edit().putString(key, value).apply(); }
            @Override public void remove(String key) { prefs.edit().remove(key).apply(); }
        }, loadBuildDefaults());
        i18n = new PcI18n(PcI18n.resolve(conn.lang(), Locale.getDefault()));
        PcHttp.acceptLanguage = i18n.lang(); // QA T-1: server messages in the UI language

        pcStream = new PcAudioStream(false, (st, d) -> ui.post(() -> onAudioState(false, st, d)));
        micStream = new PcAudioStream(true, (st, d) -> ui.post(() -> onAudioState(true, st, d)));

        root = new FrameLayout(this);
        root.setBackground(new PcViews.BodyBackground());
        presets = new PcPresets(this);
        settings = new PcSettings(this);
        login = new PcLogin(this);
        buildPage();

        nativeScreenView = new NativeScreenView(this);
        nativeScreenView.setVisibility(View.GONE);
        nativeScreenView.setPlayerCallback(new NativeScreenView.PlayerCallback() {
            @Override
            public void onCloseRequested() {
                setNativeFullscreen(false);
                onNativeClosed();
            }

            @Override
            public void onFullscreenToggled(boolean isFullscreen) {
                setNativeFullscreen(isFullscreen);
            }

            @Override
            public void onSettingsChanged(int monitor, int height, int fps, int bitrate) {
                ui.post(() -> {
                    if (audio != null) audio.onNativeParams(monitor, height, fps, bitrate);
                });
            }

            @Override
            public void onStreamVolumeChanged(int percent, boolean muted) {
                if (audio != null) audio.onNativeStreamVolume(percent, muted);
            }
        });
        root.addView(nativeScreenView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        usbLink = new PcUsbLink();
        usbLink.onNewBeacon = () -> ui(this::routeBurst);
        usbLink.start();
        registerNetworkCallback();
        registerUsbReceiver();
        handleIntent(getIntent());
        if (!pendingPair && (conn.apiBase().isEmpty() || !conn.hasToken())) login.open("");
        setConnState(ST_CONNECTING);
        checkStatus(true);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (handleIntent(intent) || pendingPair) {
            setConnState(ST_CONNECTING);
            checkStatus(true);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (resumePcAudio && !pcStream.isRunning()) togglePcAudio(false);
        if (resumeMic && !micStream.isRunning()) togglePcAudio(true);
        resumePcAudio = resumeMic = false;
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        lastMedia = lastStatus = 0;
        ui.removeCallbacks(pollTick);
        ui.post(pollTick);
        ui.removeCallbacks(mediaTicker);
        ui.post(mediaTicker);
        if (audio != null) audio.syncButtons();
        settings.onResume(); // возврат с экрана «Установка неизвестных приложений»
        if (connState == ST_CONNECTED && !nativeMode) {
            if (media != null) media.loadQueue(false, false);
            presets.load();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        resumed = false;
        ui.removeCallbacks(pollTick);
        ui.removeCallbacks(mediaTicker);
        if (media != null) media.dismissPopups();
        if (input != null) input.dismissPopups();
    }

    @Override
    protected void onStop() {
        super.onStop();
        // Without background mode the PC sound stops with the app (as the WebView did);
        // with it, the foreground service keeps the process and the stream alive.
        if (!BackgroundAudioService.isRunning && !isChangingConfigurations()) {
            if (pcStream.isRunning()) {
                resumePcAudio = true;
                pcStream.stop();
            }
            if (micStream.isRunning()) {
                resumeMic = true;
                micStream.stop();
            }
        }
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        settings.cancelDownload();
        ui.removeCallbacksAndMessages(null);
        if (nativeScreenView != null) {
            nativeScreenView.stopStream();
            setNativeFullscreen(false);
        }
        pcStream.stop();
        micStream.stop();
        // QA A-12: the streams live in this activity — the background service must not outlive them
        if (BackgroundAudioService.isRunning && !isChangingConfigurations()) {
            try {
                stopService(new Intent(this, BackgroundAudioService.class));
            } catch (Exception ignored) {
            }
        }
        if (power != null) power.dispose();
        unregisterNetworkCallback();
        if (usbReceiver != null) {
            try {
                unregisterReceiver(usbReceiver);
            } catch (Exception ignored) {
            }
        }
        if (usbLink != null) usbLink.stop();
        io.shutdownNow();
        if (instance == this) instance = null;
        super.onDestroy();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        // rotation is handled in place (no activity restart): just drop anchored popups
        if (media != null) media.dismissPopups();
        if (input != null) input.dismissPopups();
    }

    @Override
    public void onBackPressed() {
        if (nativeScreenView != null && nativeScreenView.getVisibility() == View.VISIBLE) {
            if (nativeScreenView.handleBackPressed()) return;
            stopNativeScreen();
            return;
        }
        PcModal top = topModal();
        if (top != null) {
            top.requestBack();
            return;
        }
        if (media != null && media.closeQueueIfOpen()) return;
        if (input != null && input.closeProcessesIfOpen()) return;
        if (audio != null && audio.closePanelsForBack()) return;
        super.onBackPressed();
    }

    // ================================================================== page
    /** .wrap: centred column, max-width 420, gap 12; body padding 18 / 14 / 56. */
    private static final class CenterColumn extends FrameLayout {
        private final int maxW, side;

        CenterColumn(Context c) {
            super(c);
            maxW = PcViews.dp(c, 420);
            side = PcViews.dp(c, 14);
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            int w = MeasureSpec.getSize(wSpec);
            int cw = Math.min(maxW, w - 2 * side);
            View ch = getChildAt(0);
            ch.measure(MeasureSpec.makeMeasureSpec(cw, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED));
            setMeasuredDimension(w, ch.getMeasuredHeight() + getPaddingTop() + getPaddingBottom());
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            View ch = getChildAt(0);
            int x = (r - l - ch.getMeasuredWidth()) / 2;
            ch.layout(x, getPaddingTop(), x + ch.getMeasuredWidth(), getPaddingTop() + ch.getMeasuredHeight());
        }
    }

    private void buildPage() {
        pageScroll = new ScrollView(this);
        pageScroll.setFillViewport(true);
        pageScroll.setVerticalScrollBarEnabled(false);
        pageScroll.setOverScrollMode(View.OVER_SCROLL_IF_CONTENT_SCROLLS);
        CenterColumn cc = new CenterColumn(this);
        cc.setPadding(0, dp(18), 0, dp(56));
        page = PcViews.col(this);
        cc.addView(page);
        pageScroll.addView(cc, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        page.addView(buildHeader(), PcViews.matchWrap());
        page.addView(buildOfflineBanner(), gap(PcViews.matchWrap()));
        media = new PcMediaCard(this);
        page.addView(media.root, gap(PcViews.matchWrap()));
        audio = new PcAudioCard(this);
        page.addView(audio.root, gap(PcViews.matchWrap()));
        input = new PcInputCard(this);
        page.addView(input.root, gap(PcViews.matchWrap()));
        power = new PcPowerCard(this);
        page.addView(power.root, gap(PcViews.matchWrap()));
        statusMsg = PcViews.text(this, "", 12f, PcViews.SUBTEXT, 400);
        statusMsg.setGravity(Gravity.CENTER);
        statusMsg.setMinHeight(dp(18));
        statusMsg.setPadding(dp(8), dp(4), dp(8), dp(4));
        page.addView(statusMsg, gap(PcViews.matchWrap()));
        root.addView(pageScroll, 0, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        presets.renderMainButtons();
        renderConnState();
    }

    private LinearLayout.LayoutParams gap(LinearLayout.LayoutParams p) {
        p.topMargin = dp(12);
        return p;
    }

    private View buildHeader() {
        LinearLayout h = PcViews.row(this);
        h.setPadding(dp(4), dp(4), dp(4), dp(6));
        LinearLayout brand = PcViews.row(this);
        brand.setPadding(dp(8), dp(4), dp(8), dp(4));
        FrameLayout icon = new FrameLayout(this);
        icon.setBackground(PcViews.rect(this, 0xFF000000, 8, 0x66FF0000, 1));
        icon.setClipToOutline(true);
        icon.setElevation(dp(5));
        if (Build.VERSION.SDK_INT >= 28) {
            icon.setOutlineSpotShadowColor(0xFFFF0000);
            icon.setOutlineAmbientShadowColor(0xFFFF0000);
        }
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.pc_logo);
        logo.setScaleType(ImageView.ScaleType.CENTER_CROP);
        icon.addView(logo, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        brand.addView(icon, PcViews.lp(dp(32), dp(32)));
        LinearLayout bt = PcViews.col(this);
        TextView title = PcViews.text(this, t("brand_title"), 17f, PcViews.TEXT, 700);
        title.setLetterSpacing(-0.02f);
        bt.addView(title);
        TextView sub = PcViews.text(this, t("brand_sub"), 10f, PcViews.MUTED, 500);
        // «Настройки •» — красная точка, когда на ПК есть новая версия приложения
        LinearLayout subRow = PcViews.row(this);
        subRow.setPadding(0, dp(1), 0, 0);
        subRow.addView(sub);
        updateDot = new View(this);
        updateDot.setBackground(PcViews.oval(PcViews.RED));
        LinearLayout.LayoutParams udp = PcViews.lp(dp(6), dp(6));
        udp.leftMargin = dp(5);
        subRow.addView(updateDot, udp);
        updateDot.setVisibility(updateBadge ? View.VISIBLE : View.GONE);
        bt.addView(subRow);
        LinearLayout.LayoutParams btp = PcViews.wrap();
        btp.leftMargin = dp(10);
        brand.addView(bt, btp);
        brand.setClickable(true);
        brand.setBackground(PcViews.rect(this, 0, 12, 0, 0));
        brand.setContentDescription(t("brand_tip"));
        PcViews.pressable(brand);
        brand.setOnClickListener(v -> settings.open(updateBadge ? 2 : 0));
        LinearLayout.LayoutParams bp = PcViews.wrap();
        bp.leftMargin = -dp(8);
        h.addView(brand, bp);
        h.addView(PcViews.space(this), PcViews.weight(1));

        LinearLayout pill = PcViews.row(this);
        pill.setBackground(PcViews.pill(this, PcViews.SURFACE2, PcViews.BORDER));
        pill.setPadding(dp(11), dp(5), dp(11), dp(5));
        statusDot = new View(this);
        pill.addView(statusDot, PcViews.lp(dp(7), dp(7)));
        statusText = PcViews.single(PcViews.text(this, t("status_checking"), 12f, PcViews.SUBTEXT, 500));
        statusText.setMaxWidth(dp(190));
        LinearLayout.LayoutParams sp = PcViews.wrap();
        sp.leftMargin = dp(7);
        pill.addView(statusText, sp);
        pill.setClickable(true);
        pill.setContentDescription(t("tip_conn_check"));
        PcViews.pressable(pill);
        pill.setOnClickListener(v -> manualReconnect());
        h.addView(pill);
        // QA U-1: settings were reachable only through the logo — a visible gear next to the status
        FrameLayout gear = new FrameLayout(this);
        gear.setBackground(PcViews.pill(this, PcViews.SURFACE2, PcViews.BORDER));
        gear.addView(PcViews.icon(this, PcAppIcons.GEAR, PcViews.SUBTEXT, 18),
                new FrameLayout.LayoutParams(dp(18), dp(18), Gravity.CENTER));
        gear.setClickable(true);
        gear.setContentDescription(t("brand_tip"));
        PcViews.pressable(gear);
        gear.setOnClickListener(v -> settings.open(updateBadge ? 2 : 0));
        LinearLayout.LayoutParams gp = PcViews.lp(dp(36), dp(36));
        gp.leftMargin = dp(8);
        h.addView(gear, gp);
        return h;
    }

    private View buildOfflineBanner() {
        offlineBanner = PcViews.row(this);
        offlineBanner.setBackground(PcViews.rect(this, 0x1FEF4444, 14, 0x59EF4444, 1));
        offlineBanner.setPadding(dp(12), dp(10), dp(12), dp(10));
        LinearLayout info = PcViews.col(this);
        info.addView(PcViews.text(this, t("offline_title"), 12.5f, 0xFFFCA5A5, 600));
        TextView s = PcViews.text(this, t("offline_sub"), 11f, 0x99FFFFFF, 400);
        s.setPadding(0, dp(3), 0, 0);
        info.addView(s);
        offlineBanner.addView(info, PcViews.weight(1));
        PcViews.Btn retry = new PcViews.Btn(this, null, t("offline_retry"));
        retry.setBackground(PcViews.rect(this, 0x26FFFFFF, 10, 0x40FFFFFF, 1));
        retry.pad(12, 8).size(12f);
        retry.label.setTypeface(PcViews.face(600));
        retry.setOnClickListener(v -> manualReconnect());
        LinearLayout.LayoutParams rp = PcViews.wrap();
        rp.leftMargin = dp(10);
        offlineBanner.addView(retry, rp);
        PcViews.Btn wol = new PcViews.Btn(this, null, t("offline_btn"));
        wol.setBackground(PcViews.rect(this, 0xFFEF4444, 10, 0, 0));
        wol.pad(12, 8).size(12f);
        wol.label.setTypeface(PcViews.face(600));
        wol.setOnClickListener(v -> wakeOnLan());
        LinearLayout.LayoutParams wp = PcViews.wrap();
        wp.leftMargin = dp(8);
        offlineBanner.addView(wol, wp);
        offlineBanner.setVisibility(View.GONE);
        return offlineBanner;
    }

    /** Language switch: rebuild every screen with the new dictionary (data reloads from the PC). */
    void setAppLanguage(String code) {
        conn.setLang(code);
        i18n.setLang(code);
        PcHttp.acceptLanguage = i18n.lang();
        if (media != null) media.dismissPopups();
        if (input != null) input.dismissPopups();
        if (power != null) power.dispose();
        for (PcModal m : new ArrayList<>(modals)) {
            ViewGroup p = (ViewGroup) m.getParent();
            if (p != null) p.removeView(m);
        }
        modals.clear();
        root.removeView(pageScroll);
        buildPage();
        audio.syncButtons();
        if (connState == ST_CONNECTED) refreshAll();
        settings.open(0);
    }

    // ================================================================== helpers for screens
    int dp(float v) {
        return PcViews.dp(this, v);
    }

    String t(String key, Object... vars) {
        return i18n.t(key, vars);
    }

    void status(CharSequence msg) {
        if (statusMsg == null || msg == null) return;
        String s = msg.toString();
        if (s.contains("<")) statusMsg.setText(Html.fromHtml(s, Html.FROM_HTML_MODE_LEGACY));
        else statusMsg.setText(s);
        statusMsg.setAlpha(0.4f);
        statusMsg.animate().alpha(1f).setDuration(180).start();
    }

    void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    void bg(Runnable r) {
        try {
            io.execute(r);
        } catch (Exception ignored) {
            // executor shut down (activity destroyed)
        }
    }

    void ui(Runnable r) {
        ui.post(() -> {
            if (!destroyed) r.run();
        });
    }

    interface ApiCallback {
        void on(PcHttp.Resp r);
    }

    /**
     * web apiFetch(): request on a worker thread, callback on the UI thread. 401 → login window;
     * a successful answer marks the connection as online. Network errors only reach the caller.
     */
    void api(final String method, final String path, Object body, final int timeoutMs, final ApiCallback cb) {
        final String base = conn.apiBase();
        final String token = conn.token();
        final String json = body == null ? null : PcJson.stringify(body); // serialise on the UI thread
        bg(() -> {
            final PcHttp.Resp r = PcHttp.request(base, method, path, token, json, Math.min(timeoutMs, PcHttp.CONNECT_TIMEOUT), timeoutMs, null);
            ui(() -> {
                if (r.unauthorized() && !path.startsWith("/api/auth/login")) {
                    onUnauthorized();
                } else if (r.ok() && connState != ST_CONNECTED && connState != ST_AUTH) {
                    setConnState(ST_CONNECTED);
                }
                if (cb != null) cb.on(r);
            });
        });
    }

    interface Choice {
        void on(int index);
    }

    /** web showCustomConfirm(): gradient box, title, text, buttons; backdrop = cancel (-1). */
    void confirm(String title, String message, String[] labels, int[] styles, final Choice cb) {
        final PcModal m = new PcModal(this, PcModal.KIND_CONFIRM, 360);
        final boolean[] done = {false};
        m.onBackRequest = () -> {
            if (!done[0]) {
                done[0] = true;
                m.dismiss();
                if (cb != null) cb.on(-1);
            }
        };
        TextView tt = PcViews.text(this, title, 16f, PcViews.TEXT, 700);
        LinearLayout.LayoutParams tp = PcViews.matchWrap();
        tp.bottomMargin = dp(8);
        m.content.addView(tt, tp);
        TextView desc = PcViews.text(this, message, 13f, PcViews.SUBTEXT, 400);
        desc.setLineSpacing(0, 1.45f);
        LinearLayout.LayoutParams dp = PcViews.matchWrap();
        dp.bottomMargin = dp(18);
        m.content.addView(desc, dp);
        LinearLayout actions = PcViews.col(this);
        LinearLayout row = PcViews.row(this);
        actions.addView(row, PcViews.matchWrap());
        boolean stackLast = labels.length == 3;
        for (int i = 0; i < labels.length; i++) {
            final int idx = i;
            PcViews.Btn b = new PcViews.Btn(this, null, labels[i]);
            b.setStyle(styles != null && i < styles.length ? styles[i] : PcViews.B_SEC);
            b.pad(12, 10).size(13f);
            b.label.setTypeface(PcViews.face(600));
            b.label.setSingleLine(false);
            b.label.setMaxLines(2);
            b.setOnClickListener(v -> {
                if (done[0]) return;
                done[0] = true;
                m.dismiss();
                if (cb != null) cb.on(idx);
            });
            if (stackLast && i == 2) {
                b.pad(12, 9).size(12.5f);
                b.label.setTextColor(PcViews.MUTED);
                LinearLayout.LayoutParams p = PcViews.matchWrap();
                p.topMargin = dp(8);
                actions.addView(b, p);
            } else {
                LinearLayout.LayoutParams p = PcViews.weight(1);
                if (row.getChildCount() > 0) p.leftMargin = dp(8);
                row.addView(b, p);
            }
        }
        m.content.addView(actions, PcViews.matchWrap());
        m.show(root);
        registerModal(m);
    }

    void alert(String message, final Runnable then) {
        confirm("PC Control", message, new String[]{t("btn_ok")}, new int[]{PcViews.B_RED}, i -> {
            if (then != null) then.run();
        });
    }

    void registerModal(final PcModal m) {
        modals.add(m);
        final Runnable prev = m.onDismissed;
        m.onDismissed = () -> {
            modals.remove(m);
            if (prev != null) prev.run();
        };
        hideKeyboard(pageScroll);
    }

    private PcModal topModal() {
        for (int i = modals.size() - 1; i >= 0; i--) {
            PcModal m = modals.get(i);
            if (m.isShowing()) return m;
        }
        return null;
    }

    void copyText(String s) {
        ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("PC Control", s));
    }

    void hideKeyboard(View v) {
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        View f = getCurrentFocus();
        if (imm != null) imm.hideSoftInputFromWindow((f != null ? f : (v != null ? v : root)).getWindowToken(), 0);
        if (f != null) f.clearFocus();
    }

    void showKeyboard(View v) {
        v.requestFocus();
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.showSoftInput(v, InputMethodManager.SHOW_IMPLICIT);
    }

    /** scrollIntoView({block:'nearest'}) for opened panels. */
    void scrollIntoView(final View v) {
        ui.postDelayed(() -> {
            if (pageScroll == null || v.getParent() == null) return;
            int top = 0;
            View cur = v;
            while (cur != null && cur != pageScroll) {
                top += cur.getTop();
                if (!(cur.getParent() instanceof View)) break;
                cur = (View) cur.getParent();
            }
            int bottom = top + v.getHeight();
            int vis0 = pageScroll.getScrollY(), vis1 = vis0 + pageScroll.getHeight();
            if (bottom > vis1) pageScroll.smoothScrollTo(0, Math.min(top, bottom - pageScroll.getHeight() + dp(16)));
            else if (top < vis0) pageScroll.smoothScrollTo(0, top - dp(8));
        }, 300);
    }

    String versionName() {
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
            return pi.versionName;
        } catch (Exception e) {
            return "";
        }
    }

    long versionCode() {
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    /** Точка «есть обновление» у входа в настройки (заголовок). */
    void setUpdateBadge(boolean on) {
        updateBadge = on;
        if (updateDot != null) updateDot.setVisibility(on ? View.VISIBLE : View.GONE);
    }

    /** Итог установки обновления (PcApkInstaller.Receiver, может прийти не из UI-потока). */
    void onApkInstallStatus(final int status, final String message) {
        ui(() -> settings.onInstallStatus(status, message));
    }

    /** assets/pc_defaults.json written by scripts/build_apk.py (LAN / VPN / relay / MAC / token). */
    private Map<String, String> loadBuildDefaults() {
        Map<String, String> m = new LinkedHashMap<>();
        try (InputStream is = getAssets().open("pc_defaults.json")) {
            PcJson.O o = PcJson.parseObj(new String(PcHttp.readAll(is, 65536), "UTF-8"));
            for (String k : new String[]{"token", "lan", "vpn", "relay", "mac"}) m.put(k, o.str(k));
        } catch (Exception ignored) {
            // generic APK without embedded defaults
        }
        return m;
    }

    // ================================================================== connection
    private void setConnState(int st) {
        int prev = connState;
        connState = st;
        renderConnState();
        if (st == ST_CONNECTED) {
            retryDelay = 5000;
            if (prev != ST_CONNECTED) {
                if (prev != ST_CONNECTING) status(t("status_online"));
                lastMedia = lastStatus = lastLang = SystemClock.elapsedRealtime();
                refreshAll();
                settings.checkUpdateOnConnect();
            }
        } else if (st == ST_DISCONNECTED && prev != ST_DISCONNECTED) {
            nextRetryAt = SystemClock.elapsedRealtime() + retryDelay;
        }
    }

    private void renderConnState() {
        if (statusDot == null) return;
        switch (connState) {
            case ST_CONNECTED: {
                statusDot.setBackground(PcViews.oval(PcViews.OK));
                statusDot.setElevation(dp(2));
                if (Build.VERSION.SDK_INT >= 28) {
                    statusDot.setOutlineSpotShadowColor(PcViews.OK);
                    statusDot.setOutlineAmbientShadowColor(PcViews.OK);
                }
                offlineBanner.setVisibility(View.GONE);
                break;
            }
            case ST_AUTH:
                statusDot.setBackground(PcViews.oval(PcViews.MUTED));
                statusDot.setElevation(0);
                statusText.setText(t("status_auth_required"));
                offlineBanner.setVisibility(View.GONE);
                break;
            case ST_DISCONNECTED:
                statusDot.setBackground(PcViews.oval(PcViews.DANGER));
                statusDot.setElevation(0);
                statusText.setText(t("status_offline"));
                offlineBanner.setVisibility(View.VISIBLE);
                break;
            default:
                statusDot.setBackground(PcViews.oval(PcViews.MUTED));
                statusDot.setElevation(0);
                statusText.setText(t("status_checking"));
                break;
        }
    }

    private void manualReconnect() {
        if (connState == ST_CONNECTING && statusInFlight) return;
        setConnState(ST_CONNECTING);
        status(t("status_checking"));
        checkStatus(true);
    }

    /** Settings changed the route / addresses: probe again. */
    void reconnect(boolean probe) {
        setConnState(ST_CONNECTING);
        checkStatus(probe);
    }

    /**
     * web checkStatus(): /status on the active address, otherwise probe LAN / Tailscale / custom in
     * parallel (first answer wins and becomes the active server). When the PC comes online the
     * saved password is verified once (/api/auth/verify) — a rejected one opens the login window.
     */
    void checkStatus(final boolean allowProbe) {
        if (statusInFlight) return;
        statusInFlight = true;
        final String current = conn.apiBase();
        final String tok = conn.token();
        final String key = conn.routeKey(), inst = conn.instance();
        final boolean verify = connState != ST_CONNECTED;
        final boolean auto = PcConn.MODE_AUTO.equals(conn.mode());
        // an older server without /api/route/key is asked again only after 5 minutes (per address)
        final String missUrl = SystemClock.elapsedRealtime() - routeKeyMissAt < 300000 ? routeKeyMissUrl : "";
        bg(() -> {
            // Candidates (USB cable / tethering / LAN / Tailscale) are probed WITHOUT the password;
            // the password is used only on the route PcRoute accepts (see PcRoute / core/route_auth.py).
            long now = System.currentTimeMillis();
            List<String> tether = new ArrayList<>(), beacons = new ArrayList<>();
            if (auto && allowProbe) {
                int port = PcRoute.portOf(!conn.lanHost().isEmpty() ? conn.lanHost() : current);
                tether = usbLink.tetherUrls(port, now);
                beacons = usbLink.otherBeaconUrls(now, tether);
            }
            Set<String> autos = new LinkedHashSet<>(tether);
            autos.addAll(beacons);
            autoUrls = autos;
            List<PcRoute.Target> targets = PcRoute.candidates(conn, tether, beacons, conn.untrustedHosts());
            if (!allowProbe) targets.clear();
            if (!current.isEmpty()) {
                // the active address (chosen at login / last winner) is always a candidate too
                boolean trusted = !conn.isUntrusted(current) && !PcRoute.isLoopback(current) && !autos.contains(current);
                targets = PcRoute.withTarget(targets, new PcRoute.Target(current, PcRoute.kindOf(current), trusted));
            }
            PcHttp.RouteResult rr = PcHttp.probeRoutes(targets, key, inst, !tok.isEmpty(), 3500);
            final PcRoute.Probe w = rr.winner;
            final PcRoute.Probe mismatch = w == null ? PcRoute.trustedMismatch(rr.all) : null;
            boolean authBad = false;
            String newKey = null, newInst = null;
            if (w != null && verify) {
                PcHttp.Resp v = PcHttp.request(w.target.url, "GET", "/api/auth/verify", tok, null, 4000, 4000, null);
                authBad = v.unauthorized();
            }
            boolean keyMiss = false;
            if (w != null && !authBad && key.isEmpty() && !tok.isEmpty() && !w.target.url.equals(missUrl)) {
                PcHttp.Resp k = PcHttp.request(w.target.url, "GET", "/api/route/key", tok, null, 4000, 4000, null);
                if (k.ok() && !k.json().str("route_key").isEmpty()) {
                    newKey = k.json().str("route_key");
                    newInst = k.json().str("instance");
                } else {
                    keyMiss = true; // older server without route keys
                }
            }
            final boolean fAuthBad = authBad, fKeyMiss = keyMiss;
            final String fKey = newKey, fInst = newInst;
            ui(() -> {
                statusInFlight = false;
                if (fKeyMiss) {
                    routeKeyMissAt = SystemClock.elapsedRealtime();
                    routeKeyMissUrl = w.target.url;
                }
                if (w == null) {
                    if (mismatch != null && !conn.token().isEmpty()) {
                        onRouteMismatch(mismatch.target.url);
                        return;
                    }
                    if (connState != ST_AUTH) setConnState(ST_DISCONNECTED);
                    return;
                }
                String url = w.target.url;
                if (fKey != null) {
                    conn.setRouteKey(fKey, fInst);
                    // with the key, USB / tethering routes can be verified now — re-probe at once instead
                    // of waiting for the next periodic check (~17 s seen on the phone)
                    ui.postDelayed(routeKick, 300);
                }
                if (w.verified) conn.markTrusted(url);
                String old = conn.apiBase();
                conn.setActiveServer(url);
                int prevKind = routeKind;
                routeKind = w.target.kind;
                if (login.isOpen()) login.suggestServer(old, conn.apiBase());
                if (fAuthBad) {
                    onUnauthorized();
                    return;
                }
                setConnState(ST_CONNECTED);
                statusText.setText(w.status.str("hostname", "PC Control") + " · " + t(PcRoute.labelKey(routeKind)));
                String now2 = conn.apiBase();
                if (!old.isEmpty() && !old.equals(now2)) onRouteChanged(now2, prevKind != routeKind);
            });
        });
    }

    /**
     * The route changed mid-session (cable plugged / pulled, Wi-Fi lost): the same PC answers at a new
     * address. API calls pick it up by themselves (conn.apiBase()); open streams are moved over.
     */
    private void onRouteChanged(String url, boolean announce) {
        String tok = conn.token();
        if (pcStream.isRunning()) pcStream.start(url, tok);
        if (micStream.isRunning()) micStream.start(url, tok);
        if (nativeMode && nativeScreenView != null) nativeScreenView.switchServer(url);
        if (announce) status(t("msg_route_switched", "route", t(PcRoute.labelKey(routeKind))));
    }

    /** A user-entered address answers, but as another server (or the PC password changed). */
    private void onRouteMismatch(String url) {
        if (connState != ST_AUTH) {
            connState = ST_AUTH;
            renderConnState();
        }
        conn.setActiveServer(url);
        if (!login.isOpen()) login.open(t("msg_route_mismatch", "host", PcConn.hostOnly(url)));
    }

    // ------------------------------------------------------------------ USB cable events
    private final Runnable routeKick = () -> {
        nextRetryAt = 0;
        if (!statusInFlight && !destroyed) checkStatus(true);
    };

    /** Cable / tethering / network changed: re-check the routes a few times while adb reverse settles. */
    void routeBurst() {
        ui.removeCallbacks(routeKick);
        for (long d : new long[]{700, 2500, 5000, 9000, 15000}) ui.postDelayed(routeKick, d);
    }

    private void registerUsbReceiver() {
        usbReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                ui(() -> routeBurst());
            }
        };
        IntentFilter f = new IntentFilter();
        f.addAction("android.hardware.usb.action.USB_STATE");
        f.addAction("android.net.conn.TETHER_STATE_CHANGED");
        f.addAction(Intent.ACTION_POWER_CONNECTED);
        f.addAction(Intent.ACTION_POWER_DISCONNECTED);
        try {
            if (Build.VERSION.SDK_INT >= 26) registerReceiver(usbReceiver, f, Context.RECEIVER_EXPORTED);
            else registerReceiver(usbReceiver, f);
        } catch (Exception ignored) {
            usbReceiver = null;
        }
    }

    /** "Connect by cable" help (settings): both ways + shortcuts to the system screens. */
    void showUsbHelp() {
        confirm(t("usb_help_title"), t("usb_help_text"),
                new String[]{t("usb_help_open_tether"), t("usb_help_open_dev"), t("btn_ok")},
                new int[]{PcViews.B_RED, PcViews.B_SEC, PcViews.B_SEC}, choice -> {
                    if (choice == 0) openTetherSettings();
                    else if (choice == 1) openSystemScreen(new Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS));
                });
    }

    private void openTetherSettings() {
        Intent tether = new Intent();
        tether.setClassName("com.android.settings", "com.android.settings.TetherSettings");
        if (openSystemScreen(tether)) return;
        Intent tether2 = new Intent();
        tether2.setClassName("com.android.settings", "com.android.settings.Settings$TetherSettingsActivity");
        if (openSystemScreen(tether2)) return;
        openSystemScreen(new Intent(Settings.ACTION_WIRELESS_SETTINGS));
    }

    private boolean openSystemScreen(Intent i) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private void onUnauthorized() {
        if (connState != ST_AUTH) {
            connState = ST_AUTH;
            renderConnState();
        }
        conn.dropToken();
        if (!login.isOpen()) login.open(t("msg_auth_err"));
    }

    /** Login succeeded against `base` (PcLogin). */
    void onLoggedIn(String base, String password, boolean remember) {
        String mode = conn.mode();
        String host = PcConn.hostOnly(base);
        // a USB route (127.0.0.1 via adb, tethering address) is not the PC's home address
        boolean usbRoute = PcRoute.isLoopback(base) || autoUrls.contains(PcConn.stripSlash(base));
        if (PcConn.MODE_CUSTOM.equals(mode)) conn.putOrRemove(PcConn.K_CUSTOM, base);
        else if (PcConn.MODE_VPN.equals(mode) || (PcConn.MODE_AUTO.equals(mode) && host.startsWith("100."))) conn.putOrRemove(PcConn.K_VPN, base);
        else if (!usbRoute) conn.putOrRemove(PcConn.K_LAN, base);
        conn.markTrusted(base);
        conn.setActiveServer(base);
        conn.setToken(password, remember);
        connState = ST_CONNECTING;
        renderConnState();
        // the user has just signed in to this address: take its route key now, so automatic routes
        // (USB cable / tethering, verified by it) work from the first connection on
        fetchRouteKeyThen(base, password, () -> {
            statusInFlight = false;
            checkStatus(true);
        });
    }

    /** GET /api/route/key from an address the password was already given to, then `then` (UI thread). */
    private void fetchRouteKeyThen(final String base, final String token, final Runnable then) {
        bg(() -> {
            final PcHttp.Resp k = PcHttp.request(base, "GET", "/api/route/key", token, null, 4000, 4000, null);
            ui(() -> {
                if (k.ok() && !k.json().str("route_key").isEmpty() && token.equals(conn.token())) {
                    conn.setRouteKey(k.json().str("route_key"), k.json().str("instance"));
                }
                then.run();
            });
        });
    }

    /** QA U-41: the saved password is forgotten — ask first. */
    void confirmLogout() {
        confirm(t("btn_logout"), t("confirm_logout"), new String[]{t("btn_cancel"), t("btn_logout")},
                new int[]{PcViews.B_SEC, PcViews.B_DANGER}, i -> {
                    if (i == 1) logout();
                });
    }

    void logout() {
        conn.setToken("", false);
        settings.close();
        connState = ST_AUTH;
        renderConnState();
        login.open(t("msg_logged_out"));
    }

    /** web initDashboardData(). */
    void refreshAll() {
        audio.loadVolume();
        audio.loadStreamVolume();
        power.checkTimerStatus();
        media.pollMedia();
        media.loadQueue(false, false);
        input.loadLanguages();
        audio.loadMonitors();
        audio.syncButtons();
        presets.load();
    }

    private boolean handleIntent(Intent intent) {
        if (intent == null || intent.getData() == null) return false;
        Uri u = intent.getData();
        if (!"pccontrol".equalsIgnoreCase(u.getScheme())) return false;
        Map<String, String> q = PcConn.parseQuery(u.getEncodedQuery());
        final String ticket = conn.applyConnectParams(q);
        intent.setData(null);
        if (!ticket.isEmpty()) {
            pendingPair = true;
            final String base = conn.apiBase();
            bg(() -> {
                final PcHttp.Resp r = PcHttp.request(base, "POST", "/api/pair/exchange", null, PcJson.map("ticket", ticket), 4000, 8000, null);
                ui(() -> {
                    pendingPair = false;
                    if (r.ok() && !r.json().str("token").isEmpty()) {
                        conn.setToken(r.json().str("token"), true);
                        conn.markTrusted(base);
                        toast(t("msg_pair_ok"));
                        login.close();
                        fetchRouteKeyThen(base, conn.token(), () -> reconnect(true));
                    } else {
                        login.open(t("msg_pair_fail"));
                    }
                });
            });
        } else if (conn.hasToken()) {
            login.close();
        }
        return true;
    }

    private void registerNetworkCallback() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            if (cm == null) return;
            netCallback = new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    ui(() -> {
                        if (connState != ST_CONNECTED && connState != ST_AUTH) {
                            nextRetryAt = 0;
                            checkStatus(true);
                        }
                        routeBurst();
                    });
                }

                @Override
                public void onLost(Network network) {
                    ui(() -> {
                        ConnectivityManager c2 = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
                        // over the USB cable (adb / tethering) the PC stays reachable without any network
                        if (c2 != null && c2.getActiveNetwork() == null && connState == ST_CONNECTED && !PcRoute.isUsb(routeKind)) {
                            setConnState(ST_DISCONNECTED);
                            status(t("status_network_lost"));
                        }
                        routeBurst();
                    });
                }
            };
            cm.registerDefaultNetworkCallback(netCallback);
            // any network (Wi-Fi, VPN/Tailscale, ...) appearing or disappearing → re-check the routes
            anyNetCallback = new ConnectivityManager.NetworkCallback() {
                @Override public void onAvailable(Network network) { ui(() -> routeBurst()); }
                @Override public void onLost(Network network) { ui(() -> routeBurst()); }
            };
            NetworkRequest req = new NetworkRequest.Builder()
                    .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                    .build();
            cm.registerNetworkCallback(req, anyNetCallback);
        } catch (Exception ignored) {
        }
    }

    private void unregisterNetworkCallback() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            if (cm != null && netCallback != null) cm.unregisterNetworkCallback(netCallback);
            if (cm != null && anyNetCallback != null) cm.unregisterNetworkCallback(anyNetCallback);
        } catch (Exception ignored) {
        }
    }

    // ================================================================== polling (web adaptivePollTick)
    private final Runnable pollTick = new Runnable() {
        @Override
        public void run() {
            if (destroyed || !resumed) return;
            long now = SystemClock.elapsedRealtime();
            if (!nativeMode) {
                if (connState == ST_CONNECTED) {
                    if (now - lastMedia >= media.pollInterval()) {
                        lastMedia = now;
                        media.pollMedia();
                    }
                    if (now - lastStatus >= 12000) {
                        lastStatus = now;
                        checkStatus(true);
                    }
                    if (now - lastLang >= 15000) {
                        lastLang = now;
                        input.loadLanguages();
                    }
                    if (now - lastVolume >= 5000) {
                        // QA P-6: the slider showed a stale value after the volume changed on the PC
                        lastVolume = now;
                        audio.loadVolume();
                    }
                    if ((presets.isOpen() || presets.anyRunning()) && now - lastPresets >= 3000) {
                        lastPresets = now;
                        presets.pollStatus();
                    }
                    if (input.procOpen && now - lastProc >= 4000) {
                        lastProc = now;
                        input.loadProcesses(true);
                    }
                } else if (connState == ST_DISCONNECTED && !statusInFlight && now >= nextRetryAt) {
                    // automatic retry with back-off (5 s → 30 s)
                    retryDelay = Math.min(30000, retryDelay * 2);
                    nextRetryAt = now + retryDelay;
                    checkStatus(true);
                }
            } else if (!statusInFlight && connState != ST_AUTH
                    && now - lastStatus >= (connState == ST_CONNECTED ? 6000 : 3000)) {
                // during the screen stream too: cable pulled → Wi-Fi, cable plugged → USB
                lastStatus = now;
                checkStatus(true);
            }
            ui.postDelayed(this, 1000);
        }
    };

    private final Runnable mediaTicker = new Runnable() {
        @Override
        public void run() {
            if (destroyed || !resumed) return;
            if (media != null && !nativeMode) media.tick();
            ui.postDelayed(this, 400);
        }
    };

    // ================================================================== PC audio / mic
    void togglePcAudio(boolean mic) {
        PcAudioStream s = mic ? micStream : pcStream;
        if (s.isRunning()) {
            s.stop();
            if (mic) micAudioState = PcAudioStream.STOPPED;
            else pcAudioState = PcAudioStream.STOPPED;
            status(t(mic ? "msg_mic_stopped" : "msg_audio_stopped"));
        } else {
            if (mic) micAudioState = PcAudioStream.CONNECTING;
            else pcAudioState = PcAudioStream.CONNECTING;
            status(t(mic ? "msg_connecting_mic" : "msg_connecting_audio").replace(" (WebRTC)", ""));
            s.start(conn.apiBase(), conn.token());
        }
        audio.syncButtons();
    }

    private void onAudioState(boolean mic, int st, String detail) {
        if (destroyed) return;
        if (mic) micAudioState = st;
        else pcAudioState = st;
        switch (st) {
            case PcAudioStream.PLAYING:
                status(t(mic ? "msg_mic_connected" : "msg_audio_connected") + (detail.isEmpty() ? "" : " (" + detail + ")"));
                break;
            case PcAudioStream.RECONNECTING:
                status(t("msg_audio_reconnecting"));
                break;
            case PcAudioStream.AUTH:
                (mic ? micStream : pcStream).stop();
                onUnauthorized();
                break;
            case PcAudioStream.FAILED:
                (mic ? micStream : pcStream).stop();
                // "@key" = localized message from PcAudioStream
                status(detail.isEmpty() ? t("msg_server_err") : (detail.startsWith("@") ? t(detail.substring(1)) : detail));
                break;
            default:
                break;
        }
        if (st == PcAudioStream.AUTH || st == PcAudioStream.FAILED) {
            if (mic) micAudioState = PcAudioStream.STOPPED;
            else pcAudioState = PcAudioStream.STOPPED;
        }
        audio.syncButtons();
    }

    // ================================================================== background mode
    void setBackgroundMode(final boolean enable) {
        try {
            if (enable) {
                if (Build.VERSION.SDK_INT >= 33
                        && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
                }
                Intent intent = new Intent(this, BackgroundAudioService.class);
                intent.setAction(BackgroundAudioService.ACTION_START);
                if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent);
                else startService(intent);
            } else {
                Intent intent = new Intent(this, BackgroundAudioService.class);
                intent.setAction(BackgroundAudioService.ACTION_STOP);
                startService(intent);
            }
            status(t(enable ? "msg_bg_mode_on" : "msg_bg_mode_off"));
        } catch (Exception e) {
            status("Background service: " + e.getMessage());
        }
        ui.postDelayed(() -> {
            if (audio != null) audio.syncButtons();
        }, 150);
    }

    /** Called by BackgroundAudioService when it starts / stops. */
    public static void notifyBackgroundStateChanged(final boolean active) {
        final MainActivity a = instance;
        if (a == null) return;
        a.ui(() -> {
            if (a.audio != null) a.audio.syncButtons();
            a.status(a.t(active ? "msg_bg_mode_on" : "msg_bg_mode_off"));
        });
    }

    // ================================================================== native screen / PC control
    void startNativeScreen(final int mode) {
        if (nativeMode) {
            if (nativeModeKind == mode) return;
            nativeScreenView.stopStream();
        }
        final String base = conn.apiBase();
        if (base.isEmpty() || connState == ST_AUTH) {
            login.open("");
            return;
        }
        hideKeyboard(pageScroll);
        if (media != null) media.dismissPopups();
        if (input != null) input.dismissPopups();
        nativeMode = true;
        nativeModeKind = mode;
        setSystemBarColors(0xFF000000);
        status(mode == NativeScreenView.MODE_PC_CONTROL ? t("btn_pc_control") + " (MediaCodec + Touchpad)"
                : t("btn_screen_share") + " (Moonlight MediaCodec)");
        audio.syncButtons();
        audio.saveScreenCfg(() -> {
            if (!nativeMode || nativeModeKind != mode) return;
            try {
                nativeScreenView.setOperatingMode(mode);
                nativeScreenView.configure(conn.apiBase(), conn.token(), audio.cfgMonitor, audio.cfgHeight, audio.cfgFps,
                        audio.cfgBitrate, "auto", "auto");
                nativeScreenView.startStream();
            } catch (Exception e) {
                nativeMode = false;
                status(t(mode == NativeScreenView.MODE_PC_CONTROL ? "msg_pc_control_error" : "msg_native_screen_error") + e.getMessage());
                audio.syncButtons();
            }
        });
    }

    void stopNativeScreen() {
        if (nativeScreenView != null) nativeScreenView.stopStream();
        setNativeFullscreen(false);
        onNativeClosed();
    }

    /** Цвет статус- и навигационной панели (в демонстрации — чёрный, как поля вокруг видео). */
    private void setSystemBarColors(int color) {
        Window win = getWindow();
        win.setStatusBarColor(color);
        win.setNavigationBarColor(color);
    }

    private void onNativeClosed() {
        ui(() -> {
            nativeMode = false;
            if (!nativeFullscreenOn) setSystemBarColors(PcViews.BG);
            if (audio != null) audio.syncButtons();
            lastMedia = lastStatus = 0;
        });
    }

    void setNativeStreamVolume(int percent, boolean muted) {
        if (nativeScreenView != null) nativeScreenView.setStreamVolume(percent, muted);
    }

    public boolean checkOrRequestRecordAudioPermission() {
        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, 102);
            return false;
        }
        return true;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        boolean granted = grantResults != null && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (requestCode == 102 && nativeScreenView != null) {
            nativeScreenView.onRecordAudioPermissionResult(granted);
        } else if (requestCode == 103) {
            if (granted && pendingScreenshot != null) saveScreenshot(pendingScreenshot, pendingScreenshotName, pendingScreenshotMime);
            else if (!granted) sideToast(t("msg_storage_denied"), true);
            pendingScreenshot = null;
        }
    }

    /** Полноэкранная демонстрация включена (нужно для повторного скрытия панелей при возврате фокуса). */
    private boolean nativeFullscreenOn = false;

    /**
     * Полноэкранная демонстрация. Причина серой полосы слева (v2.4.2): на API 30+ скрывались только
     * панели, а окно продолжало «вписываться» в системные отступы (decorFitsSystemWindows = true),
     * поэтому root не заходил под вырез камеры / место навигационной панели, и там был виден фон
     * окна темы DeviceDefault (#1E1F24). Теперь окно рисуется на всю физическую площадь, фон окна,
     * decor и root — чёрные, видео центрируется по всему экрану (поля симметричные).
     */
    public void setNativeFullscreen(final boolean fullscreen) {
        runOnUiThread(() -> {
            Window win = getWindow();
            if (fullscreen && !nativeFullscreenOn) {
                portraitBeforeFullscreen = getResources().getConfiguration().orientation != Configuration.ORIENTATION_LANDSCAPE;
            }
            boolean wasFullscreen = nativeFullscreenOn;
            nativeFullscreenOn = fullscreen;
            if (fullscreen) {
                win.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0xFF000000));
                root.setBackgroundColor(0xFF000000);
                win.setStatusBarColor(0xFF000000);
                win.setNavigationBarColor(0xFF000000);
                applyImmersive(win);
                if (Build.VERSION.SDK_INT >= 28) {
                    WindowManager.LayoutParams lp = win.getAttributes();
                    // ALWAYS (API 30+) — заходим под вырез на любой стороне; SHORT_EDGES — на API 28–29.
                    lp.layoutInDisplayCutoutMode = Build.VERSION.SDK_INT >= 30
                            ? WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                            : WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
                    win.setAttributes(lp);
                }
                try {
                    setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
                } catch (Exception ignored) {
                }
            } else {
                if (Build.VERSION.SDK_INT >= 30) {
                    win.setDecorFitsSystemWindows(true);
                    android.view.WindowInsetsController c = win.getInsetsController();
                    if (c != null) c.show(android.view.WindowInsets.Type.statusBars() | android.view.WindowInsets.Type.navigationBars());
                } else {
                    win.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
                }
                // Фон окна = фон приложения (а не серый фон темы), чтобы и в обычной демонстрации
                // при повороте/изменении размеров не мелькали серые края.
                win.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(PcViews.BG));
                root.setBackground(new PcViews.BodyBackground());
                setSystemBarColors(nativeMode ? 0xFF000000 : PcViews.BG);
                if (Build.VERSION.SDK_INT >= 28) {
                    WindowManager.LayoutParams lp = win.getAttributes();
                    lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT;
                    win.setAttributes(lp);
                }
                if (wasFullscreen) restoreOrientation();
                else setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
            }
        });
    }

    private boolean portraitBeforeFullscreen = true;

    /**
     * QA P-11: with auto-rotate OFF, UNSPECIFIED kept the forced landscape after leaving fullscreen.
     * Then: back to portrait (if the app was in portrait before), and afterwards follow the user's
     * rotation setting (USER) — with auto-rotate ON the sensor decides as before.
     */
    private void restoreOrientation() {
        try {
            boolean autoRotate = Settings.System.getInt(getContentResolver(), Settings.System.ACCELEROMETER_ROTATION, 0) == 1;
            if (!autoRotate && portraitBeforeFullscreen) {
                setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
                ui.postDelayed(() -> {
                    if (!nativeFullscreenOn) setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_USER);
                }, 800);
            } else {
                setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_USER);
            }
        } catch (Exception ignored) {
        }
    }

    /** Скрывает статус- и навигационную панели (immersive sticky), окно — на весь экран. */
    private void applyImmersive(Window win) {
        if (Build.VERSION.SDK_INT >= 30) {
            win.setDecorFitsSystemWindows(false);
            android.view.WindowInsetsController c = win.getInsetsController();
            if (c != null) {
                c.hide(android.view.WindowInsets.Type.statusBars() | android.view.WindowInsets.Type.navigationBars());
                c.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            win.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // После шторки/диалога система может вернуть панели — снова прячем их.
        if (hasFocus && nativeFullscreenOn && !destroyed) applyImmersive(getWindow());
    }

    // ================================================================== screenshot
    /** Уведомление справа сверху (поверх всего, в т.ч. демонстрации экрана) + строка статуса. */
    private TextView linkBadge;

    /** QA P2-4: badge over the video while the link to the PC is down (no frames / input stream dead). */
    void setStreamLinkLost(boolean lost) {
        if (destroyed) return;
        if (lost && linkBadge == null) {
            linkBadge = PcViews.text(this, t("stream_link_lost"), 13f, 0xFFFFFFFF, 600);
            linkBadge.setBackground(PcViews.rect(this, 0xE6B91C1C, 18, 0x66FFFFFF, 1));
            linkBadge.setPadding(dp(14), dp(8), dp(14), dp(8));
            linkBadge.setElevation(dp(12));
            linkBadge.setTranslationZ(dp(20));
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
            lp.topMargin = dp(28);
            root.addView(linkBadge, lp);
        }
        if (linkBadge != null) {
            linkBadge.setText(t("stream_link_lost"));
            linkBadge.setVisibility(lost ? View.VISIBLE : View.GONE);
            if (lost) linkBadge.bringToFront();
        }
    }

    void sideToast(String text, boolean error) {
        status(text);
        if (!destroyed) PcViews.SideToast.show(root, text, error);
    }

    void takeScreenshot() {
        status(t("msg_screenshot_start"));
        api("GET", "/screenshot", null, 25000, r -> {
            if (!r.ok()) {
                if (r.unauthorized()) return;
                String m = r.error == null ? r.message() : "";
                sideToast(m.isEmpty() ? t("msg_screenshot_err") : m, true);
                return;
            }
            if (r.body == null || r.body.length == 0) {
                sideToast(t("msg_screenshot_err"), true);
                return;
            }
            String mime = r.contentType.contains("jpeg") ? "image/jpeg" : "image/png";
            String name = "screenshot_" + System.currentTimeMillis() + (mime.equals("image/jpeg") ? ".jpg" : ".png");
            if (Build.VERSION.SDK_INT < 29 && checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                pendingScreenshot = r.body;
                pendingScreenshotName = name;
                pendingScreenshotMime = mime;
                requestPermissions(new String[]{android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, 103);
                return;
            }
            saveScreenshot(r.body, name, mime);
        });
    }

    /** Альбом снимков в галерее: Pictures/PC Control. */
    private static final String GALLERY_ALBUM = "PC Control";

    /**
     * Сохраняет снимок в ГАЛЕРЕЮ: API 29+ — MediaStore.Images (Pictures/PC Control, без
     * разрешений); API 24–28 — файл в общей папке Pictures/PC Control (WRITE_EXTERNAL_STORAGE
     * запрошено в takeScreenshot) + MediaScanner, чтобы снимок сразу появился в галерее.
     */
    private void saveScreenshot(final byte[] data, final String name, final String mime) {
        bg(() -> {
            boolean ok = false;
            Uri uri = null;
            ContentResolver cr = getContentResolver();
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                    v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                    v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + GALLERY_ALBUM);
                    v.put(MediaStore.MediaColumns.DATE_ADDED, System.currentTimeMillis() / 1000);
                    v.put(MediaStore.Images.ImageColumns.DATE_TAKEN, System.currentTimeMillis());
                    v.put(MediaStore.MediaColumns.IS_PENDING, 1);
                    uri = cr.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                    if (uri != null) {
                        try (OutputStream os = cr.openOutputStream(uri)) {
                            if (os == null) throw new java.io.IOException("no output stream");
                            os.write(data);
                        }
                        ContentValues done = new ContentValues();
                        done.put(MediaStore.MediaColumns.IS_PENDING, 0);
                        cr.update(uri, done, null, null);
                        ok = true;
                    }
                } else {
                    File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), GALLERY_ALBUM);
                    if (!dir.exists() && !dir.mkdirs()) throw new java.io.IOException("mkdirs failed");
                    File f = new File(dir, name);
                    try (FileOutputStream fos = new FileOutputStream(f)) {
                        fos.write(data);
                    }
                    android.media.MediaScannerConnection.scanFile(getApplicationContext(),
                            new String[]{f.getAbsolutePath()}, new String[]{mime}, null);
                    ok = true;
                }
            } catch (Exception e) {
                // недописанную запись не оставляем в галерее
                if (uri != null) {
                    try {
                        cr.delete(uri, null, null);
                    } catch (Exception ignored) {
                    }
                }
            }
            final boolean fOk = ok;
            ui(() -> sideToast(t(fOk ? "msg_screenshot_gallery" : "msg_screenshot_gallery_err"), !fOk));
        });
    }

    // ================================================================== Wake-on-LAN
    /** web triggerWakeOnLan(): UDP magic packet from the phone + WOL relay + the PC backend, in parallel. */
    void wakeOnLan() {
        status(t("msg_wol_sending"));
        vibrate();
        final String mac = conn.mac();
        final List<String> targets = PcConn.wolTargets(conn.lanHost());
        final String relay = conn.relay();
        String mode = conn.mode();
        final String backend = PcConn.MODE_VPN.equals(mode) ? conn.vpnHost() : PcConn.MODE_LAN.equals(mode) ? conn.lanHost()
                : (PcConn.MODE_CUSTOM.equals(mode) && !conn.customHost().isEmpty()) ? conn.customHost()
                : (!conn.activeServer().isEmpty() ? conn.activeServer() : conn.vpnHost());
        final String token = conn.token();
        bg(() -> {
            final AtomicBoolean sent = new AtomicBoolean(false);
            byte[] pkt = PcConn.magicPacket(mac);
            if (pkt != null && sendMagicPacket(pkt, targets)) sent.set(true);
            final CountDownLatch done = new CountDownLatch(2);
            Thread tr = new Thread(() -> {
                try {
                    if (!relay.isEmpty()) {
                        PcHttp.Resp r = PcHttp.request(relay, "POST", "/wake", null, null, 3500, 3500, null);
                        if (r.ok()) sent.set(true);
                    }
                } finally {
                    done.countDown();
                }
            });
            Thread tb = new Thread(() -> {
                try {
                    if (!backend.isEmpty()) {
                        List<Object> tl = new ArrayList<>(targets);
                        PcHttp.Resp r = PcHttp.request(backend, "POST", "/api/wol", token, PcJson.map("mac", mac, "targets", tl), 1200, 1200, null);
                        if (r.ok()) sent.set(true);
                    }
                } finally {
                    done.countDown();
                }
            });
            tr.start();
            tb.start();
            try {
                done.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
            }
            ui(() -> onWolSent(sent.get()));
        });
    }

    private void onWolSent(boolean ok) {
        if (!ok) {
            status(t("msg_wol_timeout"));
            alert(PcConn.magicPacket(conn.mac()) == null ? t("server_mac_lbl") + "\n" + t("server_mac_placeholder") : t("msg_wol_timeout"), null);
            return;
        }
        status(t("msg_wol_sent"));
        if (power != null) {
            power.wolBtn.setAlpha(0.7f);
            ui.postDelayed(() -> {
                if (power != null) power.wolBtn.setAlpha(1f);
            }, 4000);
        }
        if (wolWait != null) ui.removeCallbacks(wolWait);
        final int[] attempts = {0};
        wolWait = new Runnable() {
            @Override
            public void run() {
                attempts[0]++;
                if (connState == ST_CONNECTED) {
                    status(t("msg_wol_online"));
                    return;
                }
                if (attempts[0] > 18) {
                    status(t("msg_wol_timeout"));
                    return;
                }
                checkStatus(true);
                ui.postDelayed(this, 2500);
            }
        };
        ui.postDelayed(wolWait, 2500);
    }

    private void vibrate() {
        try {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v != null && v.hasVibrator()) v.vibrate(VibrationEffect.createWaveform(new long[]{0, 60, 40, 60}, -1));
        } catch (Exception ignored) {
        }
    }

    /** UDP 9 and 7 to every broadcast (incl. the Wi-Fi interface broadcast), 3 rounds, multicast lock held. */
    private boolean sendMagicPacket(byte[] packet, List<String> extra) {
        Set<String> targets = new LinkedHashSet<>(extra);
        targets.add("255.255.255.255");
        targets.add("192.168.0.255");
        targets.add("192.168.1.255");
        try {
            Enumeration<NetworkInterface> ifs = NetworkInterface.getNetworkInterfaces();
            while (ifs != null && ifs.hasMoreElements()) {
                NetworkInterface ni = ifs.nextElement();
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress b = ia.getBroadcast();
                    if (b != null && b.getHostAddress() != null) targets.add(b.getHostAddress());
                }
            }
        } catch (Exception ignored) {
        }
        int sent = 0;
        WifiManager.MulticastLock lock = null;
        DatagramSocket socket = null;
        try {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                lock = wm.createMulticastLock("wol_lock");
                lock.setReferenceCounted(false);
                lock.acquire();
            }
        } catch (Exception ignored) {
        }
        try {
            socket = new DatagramSocket();
            socket.setBroadcast(true);
            for (int round = 0; round < 3; round++) {
                for (String host : targets) {
                    if (!PcConn.isIpv4(host)) continue;
                    try {
                        InetAddress addr = PcConn.ipv4(host);
                        for (int port : new int[]{9, 7}) {
                            socket.send(new DatagramPacket(packet, packet.length, addr, port));
                            sent++;
                        }
                    } catch (Exception ignored) {
                    }
                }
                try {
                    Thread.sleep(100);
                } catch (InterruptedException e) {
                    break;
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (socket != null) socket.close();
            if (lock != null && lock.isHeld()) try { lock.release(); } catch (Exception ignored) {}
        }
        return sent > 0;
    }
}
