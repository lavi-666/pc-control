package com.pccontrol.remote;

import android.content.Context;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Card "Аудио и трансляция" (index.html card 2 + stream.js + app.js volume code):
 * PC sound / PC microphone, background mode, PC control, screen share panel with pre-launch
 * parameters and stream volume, system volume, per-app volume mixer.
 */
final class PcAudioCard {
    private final MainActivity a;
    private final Context c;
    final LinearLayout root;

    PcViews.Btn pcAudioBtn, micBtn, bgBtn, pcControlBtn, screenPanelBtn, screenStartBtn, mixerBtn;
    private LinearLayout screenPanel, prelaunch, prelaunchBody, mixerBox;
    private TextView prelaunchTitle;
    private ImageView prelaunchIcon, prelaunchChev;
    private PcViews.Seg monSeg, resSeg, fpsSeg, brSeg;
    private PcViews.VolRow streamVol, sysVol;
    private boolean screenPanelOpen, prelaunchOpen, mixerOpen;
    private boolean sysVolDragging, sysMuted, streamVolDragging, streamMuted;
    private int streamVolume = 50;
    private boolean streamSendQueued;

    // screen configuration (stream.js screenCfg) — persisted on the PC (/screen/config)
    int cfgMonitor = 1, cfgHeight = 1080, cfgFps = 60, cfgBitrate = 0;
    String cfgQuality = "high", cfgCodec = "auto";
    private List<int[]> monitorIds = new ArrayList<>();
    private List<String> monitorLabels = new ArrayList<>();

    PcAudioCard(MainActivity act) {
        a = act;
        c = act;
        root = PcViews.card(c);
        root.addView(PcViews.cardTitle(c, a.t("card_audio_streaming")));

        PcViews.Grid g = new PcViews.Grid(c, 2, 0, 8);
        pcAudioBtn = new PcViews.Btn(c, PcAppIcons.HEADPHONES, a.t("btn_pc_audio"));
        pcAudioBtn.setOnClickListener(v -> a.togglePcAudio(false));
        micBtn = new PcViews.Btn(c, PcAppIcons.MIC, a.t("btn_mic"));
        micBtn.setOnClickListener(v -> a.togglePcAudio(true));
        g.addView(pcAudioBtn);
        g.addView(micBtn);
        root.addView(g, PcViews.matchWrap());

        bgBtn = new PcViews.Btn(c, PcAppIcons.BG_MODE, a.t("btn_bg_mode_off")).withDot();
        bgBtn.setOnClickListener(v -> a.setBackgroundMode(!BackgroundAudioService.isRunning));
        root.addView(bgBtn, PcViews.top(PcViews.matchWrap(), c, 8));

        pcControlBtn = new PcViews.Btn(c, PcAppIcons.PC, a.t("btn_pc_control"));
        pcControlBtn.setOnClickListener(v -> a.startNativeScreen(NativeScreenView.MODE_PC_CONTROL));
        root.addView(pcControlBtn, PcViews.top(PcViews.matchWrap(), c, 8));

        screenPanelBtn = new PcViews.Btn(c, PcAppIcons.MONITOR, a.t("btn_screen_share"));
        screenPanelBtn.setOnClickListener(v -> toggleScreenPanel());
        root.addView(screenPanelBtn, PcViews.top(PcViews.matchWrap(), c, 8));

        buildScreenPanel();

        sysVol = new PcViews.VolRow(c, false, PcAppIcons.VOL_ON);
        sysVol.muteBtn.setContentDescription(a.t("sys_vol_tip"));
        sysVol.slider.configure(0, 100, 1, PcViews.TEXT, false);
        sysVol.slider.setValue(50);
        sysVol.slider.setListener(new PcViews.SliderListener() {
            @Override public void onInput(float v) {
                sysVolDragging = true;
                sysVol.value.setText(Math.round(v) + "%");
            }

            @Override public void onCommit(float v) {
                sysVolDragging = false;
                commitSysVolume(Math.round(v));
            }
        });
        sysVol.muteBtn.setOnClickListener(v -> toggleSysMute());
        // QA U-7: two volume sliders on the screen — say which one this is
        TextView sysCap = PcViews.text(c, a.t("sys_vol_tip"), 11f, PcViews.MUTED, 500);
        sysCap.setPadding(PcViews.dp(c, 4), 0, 0, PcViews.dp(c, 3));
        root.addView(sysCap, PcViews.top(PcViews.matchWrap(), c, 10));
        root.addView(sysVol, PcViews.matchWrap());

        mixerBtn = new PcViews.Btn(c, null, a.t("btn_app_mixer"));
        mixerBtn.pad(12, 9).size(12.5f);
        mixerBtn.label.setTextColor(PcViews.SUBTEXT);
        mixerBtn.setOnClickListener(v -> toggleMixer());
        root.addView(mixerBtn, PcViews.top(PcViews.matchWrap(), c, 8));
        mixerBox = PcViews.col(c);
        mixerBox.setVisibility(View.GONE);
        root.addView(mixerBox, PcViews.top(PcViews.matchWrap(), c, 10));

        syncButtons();
    }

    private int dp(float v) {
        return PcViews.dp(c, v);
    }

    // ------------------------------------------------------------------ state → buttons
    void syncButtons() {
        int pcState = a.pcAudioState, micState = a.micAudioState;
        pcAudioBtn.setStyle(pcState == PcAudioStream.PLAYING ? PcViews.B_PILL : PcViews.B_DEFAULT);
        pcAudioBtn.setText(pcState == PcAudioStream.PLAYING ? a.t("btn_pc_audio_on")
                : (pcState == PcAudioStream.CONNECTING || pcState == PcAudioStream.RECONNECTING) ? a.t("status_checking") : a.t("btn_pc_audio"));
        micBtn.setStyle(micState == PcAudioStream.PLAYING ? PcViews.B_PILL : PcViews.B_DEFAULT);
        micBtn.setText(micState == PcAudioStream.PLAYING ? a.t("btn_mic_on")
                : (micState == PcAudioStream.CONNECTING || micState == PcAudioStream.RECONNECTING) ? a.t("status_checking") : a.t("btn_mic"));
        boolean bg = BackgroundAudioService.isRunning;
        bgBtn.setStyle(bg ? PcViews.B_BG_ACTIVE : PcViews.B_BG);
        bgBtn.setText(a.t(bg ? "btn_bg_mode_on" : "btn_bg_mode_off"));
        boolean nat = a.nativeMode;
        pcControlBtn.setStyle(nat && a.nativeModeKind == NativeScreenView.MODE_PC_CONTROL ? PcViews.B_PC_ACTIVE : PcViews.B_PC);
        boolean viewing = nat && a.nativeModeKind == NativeScreenView.MODE_VIEW;
        screenPanelBtn.setStyle(screenPanelOpen ? PcViews.B_PILL : PcViews.B_DEFAULT);
        screenStartBtn.setStyle(viewing ? PcViews.B_PILL : PcViews.B_RED);
        screenStartBtn.setText(a.t(viewing ? "btn_stop_screen" : "btn_start_screen"));
        mixerBtn.setStyle(mixerOpen ? PcViews.B_ACTIVE : PcViews.B_DEFAULT);
        mixerBtn.label.setTextColor(mixerOpen ? PcViews.TEXT : PcViews.SUBTEXT);
    }

    // ------------------------------------------------------------------ screen panel
    private void buildScreenPanel() {
        screenPanel = PcViews.col(c);
        screenPanel.addView(PcViews.hr(c));
        screenStartBtn = new PcViews.Btn(c, PcAppIcons.PLAY, a.t("btn_start_screen"));
        screenStartBtn.setOnClickListener(v -> {
            if (a.nativeMode && a.nativeModeKind == NativeScreenView.MODE_VIEW) a.stopNativeScreen();
            else a.startNativeScreen(NativeScreenView.MODE_VIEW);
        });
        LinearLayout.LayoutParams sp = PcViews.matchWrap();
        sp.topMargin = dp(12);
        sp.bottomMargin = dp(12);
        screenPanel.addView(screenStartBtn, sp);

        // .prelaunch
        prelaunch = PcViews.col(c);
        LinearLayout toggle = PcViews.row(c);
        toggle.setPadding(dp(12), dp(10), dp(12), dp(10));
        prelaunchIcon = PcViews.icon(c, PcAppIcons.TUNE, PcViews.SUBTEXT, 16);
        toggle.addView(prelaunchIcon);
        prelaunchTitle = PcViews.single(PcViews.text(c, a.t("screen_prelaunch_title"), 12.5f, PcViews.SUBTEXT, 600));
        LinearLayout.LayoutParams tp = PcViews.weight(1);
        tp.leftMargin = dp(8);
        tp.rightMargin = dp(8);
        toggle.addView(prelaunchTitle, tp);
        prelaunchChev = PcViews.icon(c, PcAppIcons.EXPAND, PcViews.SUBTEXT, 20);
        toggle.addView(prelaunchChev);
        toggle.setClickable(true);
        toggle.setOnClickListener(v -> togglePrelaunch());
        prelaunch.addView(toggle, PcViews.matchWrap());

        prelaunchBody = PcViews.col(c);
        prelaunchBody.setPadding(dp(12), 0, dp(12), dp(10));
        monSeg = new PcViews.Seg(c);
        monSeg.setListener(v -> setScreenOpt("monitor", v));
        prelaunchBody.addView(segRow(a.t("screen_lbl_monitor"), monSeg));
        resSeg = new PcViews.Seg(c);
        resSeg.setItems(new String[]{"480p", "720p", "1080p", a.t("screen_res_source")}, new int[]{480, 720, 1080, 0});
        resSeg.setListener(v -> setScreenOpt("height", v));
        prelaunchBody.addView(segRow(a.t("screen_lbl_resolution"), resSeg));
        fpsSeg = new PcViews.Seg(c);
        fpsSeg.setItems(new String[]{"30", "60", "90"}, new int[]{30, 60, 90});
        fpsSeg.setListener(v -> setScreenOpt("fps", v));
        prelaunchBody.addView(segRow(a.t("screen_lbl_fps"), fpsSeg));
        brSeg = new PcViews.Seg(c);
        brSeg.setItems(new String[]{a.t("screen_qual_auto"), "5M", "15M", "30M", "50M"}, new int[]{0, 5, 15, 30, 50});
        brSeg.setListener(v -> setScreenOpt("bitrate", v));
        prelaunchBody.addView(segRow(a.t("screen_lbl_bitrate"), brSeg));

        streamVol = new PcViews.VolRow(c, false, PcAppIcons.VOL_ON);
        streamVol.muteBtn.setContentDescription(a.t("screen_stream_vol_tip"));
        streamVol.slider.configure(0, PcAudioGain.MAX_PERCENT, 1, PcViews.TEXT, false);
        streamVol.slider.setListener(new PcViews.SliderListener() {
            @Override public void onInput(float v) {
                streamVolDragging = true;
                int p = Math.round(v);
                if (p > 0 && streamMuted) streamMuted = false;
                syncStreamVolume(p, streamMuted);
                if (!streamSendQueued) {
                    streamSendQueued = true;
                    a.ui.postDelayed(() -> {
                        streamSendQueued = false;
                        sendStreamVolume();
                    }, 35);
                }
            }

            @Override public void onCommit(float v) {
                streamVolDragging = false;
                int p = Math.round(v);
                if (p > 0 && streamMuted) streamMuted = false;
                syncStreamVolume(p, streamMuted);
                sendStreamVolume();
            }
        });
        streamVol.muteBtn.setOnClickListener(v -> {
            syncStreamVolume(streamVolume, !streamMuted);
            sendStreamVolume();
        });
        prelaunchBody.addView(streamVol, PcViews.top(PcViews.matchWrap(), c, 10));
        prelaunchBody.setVisibility(View.GONE);
        prelaunch.addView(prelaunchBody, PcViews.matchWrap());
        stylePrelaunch();
        LinearLayout.LayoutParams pp = PcViews.matchWrap();
        pp.bottomMargin = dp(0);
        screenPanel.addView(prelaunch, pp);

        screenPanel.setVisibility(View.GONE);
        root.addView(screenPanel, PcViews.top(PcViews.matchWrap(), c, 12));
        syncStreamVolume(50, false);
        renderScreenCfg();
    }

    private LinearLayout segRow(String label, PcViews.Seg seg) {
        LinearLayout r = PcViews.row(c);
        TextView l = PcViews.text(c, label, 12f, PcViews.SUBTEXT, 500);
        r.addView(l);
        r.addView(PcViews.space(c), PcViews.weight(1));
        LinearLayout.LayoutParams sp = PcViews.wrap();
        sp.leftMargin = dp(10);
        r.addView(seg, sp);
        LinearLayout.LayoutParams rp = PcViews.matchWrap();
        rp.bottomMargin = dp(8);
        r.setLayoutParams(rp);
        return r;
    }

    private void stylePrelaunch() {
        prelaunch.setBackground(prelaunchOpen ? PcViews.rect(c, 0x0BFFFFFF, 12, PcViews.BORDER_STRONG, 1)
                : PcViews.rect(c, 0x08FFFFFF, 12, PcViews.BORDER, 1));
        int col = prelaunchOpen ? PcViews.TEXT : PcViews.SUBTEXT;
        prelaunchTitle.setTextColor(col);
        PcViews.tintIcon(prelaunchIcon, col);
        PcViews.tintIcon(prelaunchChev, col);
    }

    private void togglePrelaunch() {
        prelaunchOpen = !prelaunchOpen;
        stylePrelaunch();
        prelaunchChev.animate().rotation(prelaunchOpen ? 180 : 0).setDuration(280)
                .setInterpolator(new android.view.animation.PathInterpolator(0.2f, 0.7f, 0.2f, 1f)).start();
        PcViews.animateHeight(prelaunchBody, prelaunchOpen, 280);
    }

    boolean closePanelsForBack() {
        if (mixerOpen) {
            toggleMixer();
            return true;
        }
        return false;
    }

    private void toggleScreenPanel() {
        screenPanelOpen = !screenPanelOpen;
        PcViews.animateHeight(screenPanel, screenPanelOpen, 260);
        syncButtons();
        if (screenPanelOpen) {
            loadMonitors();
            loadStreamVolume();
            a.scrollIntoView(screenPanel);
        }
    }

    void renderScreenCfg() {
        String[] labels = new String[monitorIds.isEmpty() ? 3 : monitorIds.size()];
        int[] vals = new int[labels.length];
        if (monitorIds.isEmpty()) {
            vals = new int[]{1, 2, 0};
            labels = new String[]{a.t("screen_mon_1"), a.t("screen_mon_2"), a.t("screen_mon_all")};
        } else {
            for (int i = 0; i < monitorIds.size(); i++) {
                int id = monitorIds.get(i)[0];
                vals[i] = id;
                labels[i] = monitorLabel(id, monitorLabels.get(i));
            }
        }
        monSeg.setItems(labels, vals);
        monSeg.select(cfgMonitor);
        resSeg.select(cfgHeight);
        fpsSeg.select(cfgFps);
        brSeg.select(cfgBitrate);
    }

    private String monitorLabel(int id, String fallback) {
        if (id == 1) return a.t("screen_mon_1");
        if (id == 2) return a.t("screen_mon_2");
        if (id == 0) return a.t("screen_mon_all");
        return a.t("screen_lbl_monitor") + " " + id;
    }

    void loadMonitors() {
        a.api("GET", "/screen/monitors", null, 6000, r -> {
            if (!r.ok()) return;
            PcJson.O d = r.json();
            List<PcJson.O> mons = d.objs("monitors");
            if (!mons.isEmpty()) {
                monitorIds = new ArrayList<>();
                monitorLabels = new ArrayList<>();
                for (PcJson.O m : mons) {
                    monitorIds.add(new int[]{m.integer("id", 1)});
                    monitorLabels.add(m.str("label"));
                }
            }
            PcJson.O cfg = d.obj("config");
            if (!cfg.map.isEmpty()) applyCfg(cfg);
            renderScreenCfg();
        });
    }

    private void applyCfg(PcJson.O cfg) {
        cfgMonitor = cfg.integer("monitor", cfgMonitor);
        cfgHeight = cfg.integer("height", cfgHeight);
        cfgFps = cfg.integer("fps", cfgFps);
        cfgBitrate = cfg.integer("bitrate", cfgBitrate);
        cfgQuality = cfg.str("quality", cfgQuality);
        cfgCodec = cfg.str("codec", cfgCodec);
    }

    Map<String, Object> cfgMap() {
        return PcJson.map("monitor", cfgMonitor, "height", cfgHeight, "fps", cfgFps, "quality", cfgQuality,
                "bitrate", cfgBitrate, "codec", cfgCodec);
    }

    private void setScreenOpt(String key, int v) {
        if ("monitor".equals(key)) cfgMonitor = v;
        else if ("height".equals(key)) cfgHeight = v;
        else if ("fps".equals(key)) cfgFps = v;
        else if ("bitrate".equals(key)) cfgBitrate = v;
        renderScreenCfg();
        saveScreenCfg(null);
    }

    void saveScreenCfg(Runnable then) {
        a.api("POST", "/screen/config", cfgMap(), 6000, r -> {
            if (then != null) then.run();
        });
    }

    /** NativeScreenView changed resolution / fps / bitrate from its own settings. */
    void onNativeParams(int monitor, int height, int fps, int bitrate) {
        cfgMonitor = monitor;
        cfgHeight = height;
        cfgFps = fps;
        cfgBitrate = bitrate;
        renderScreenCfg();
    }

    // ------------------------------------------------------------------ stream volume
    private void syncStreamVolume(int pct, boolean muted) {
        streamVolume = Math.max(0, Math.min(PcAudioGain.MAX_PERCENT, pct));
        streamMuted = muted;
        streamVol.slider.setValue(streamVolume);
        streamVol.value.setText(streamVolume + "%");
        streamVol.muteBtn.setIcon(streamMuted || streamVolume == 0 ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_ON, PcViews.SUBTEXT);
    }

    private PcThrottle nativeVolThrottle;

    /**
     * Громкость изменена в меню настроек демонстрации: обновить ползунок главного экрана и
     * сохранить на ПК (/screen/volume) — с троттлингом, последнее значение уходит всегда.
     */
    void onNativeStreamVolume(int pct, boolean muted) {
        if (streamVolDragging) return;
        syncStreamVolume(pct, muted);
        if (nativeVolThrottle == null) {
            nativeVolThrottle = new PcThrottle(150, android.os.SystemClock::uptimeMillis, (rn, ms) -> a.ui.postDelayed(rn, ms));
        }
        nativeVolThrottle.submit(() -> a.api("POST", "/screen/volume",
                PcJson.map("percent", streamVolume, "muted", streamMuted), 6000, null));
    }

    private void sendStreamVolume() {
        a.setNativeStreamVolume(streamVolume, streamMuted);
        a.api("POST", "/screen/volume", PcJson.map("percent", streamVolume, "muted", streamMuted), 6000, null);
    }

    void loadStreamVolume() {
        if (streamVolDragging) return;
        a.api("GET", "/screen/volume", null, 6000, r -> {
            if (!r.ok() || streamVolDragging) return;
            PcJson.O d = r.json();
            syncStreamVolume(d.integer("percent", 50), d.bool("muted", false));
        });
    }

    // ------------------------------------------------------------------ system volume
    private void syncSysVolume(int pct, Boolean muted) {
        int p = Math.max(0, Math.min(100, pct));
        sysVol.slider.setValue(p);
        sysVol.value.setText(p + "%");
        if (muted != null) sysMuted = muted;
        sysVol.muteBtn.setIcon(sysMuted ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_ON, PcViews.SUBTEXT);
    }

    void loadVolume() {
        if (sysVolDragging) return;
        a.api("GET", "/volume", null, 6000, r -> {
            if (!r.ok() || sysVolDragging) return;
            PcJson.O d = r.json();
            syncSysVolume(d.integer("percent", 50), d.bool("muted", false));
        });
    }

    private void commitSysVolume(int pct) {
        syncSysVolume(pct, null);
        a.api("POST", "/volume", PcJson.map("percent", pct), 6000, r -> {
            if (r.ok() && !r.message().isEmpty()) a.status(r.message());
        });
    }

    private void toggleSysMute() {
        syncSysVolume(Math.round(sysVol.slider.getValue()), !sysMuted);
        a.api("POST", "/mute", PcJson.map("mute", sysMuted), 6000, r -> {
            if (!r.message().isEmpty()) a.status(r.message());
        });
    }

    // ------------------------------------------------------------------ app mixer
    private void toggleMixer() {
        if (mixerOpen) {
            mixerOpen = false;
            PcViews.animateHeight(mixerBox, false, 200);
            syncButtons();
            return;
        }
        mixerOpen = true;
        syncButtons();
        loadAppVolumes();
    }

    private void loadAppVolumes() {
        // пока тянут ползунок сессии — не пересобираем список (ползунок «прыгнул» бы назад)
        if (mixerDragging > 0) return;
        a.api("GET", "/app_volumes", null, 8000, r -> {
            if (!r.ok() || mixerDragging > 0) return;
            List<PcMixer.Session> list = PcMixer.parse(r.jsonArray());
            mixerBox.removeAllViews();
            mixerBox.addView(PcViews.hr(c));
            LinearLayout inner = PcViews.col(c);
            inner.setPadding(0, dp(10), 0, 0);
            if (list.isEmpty()) {
                TextView e = PcViews.text(c, a.t("app_mixer_empty"), 12.5f, PcViews.MUTED, 400);
                e.setPadding(0, dp(8), 0, dp(8));
                inner.addView(e);
            }
            for (int i = 0; i < list.size(); i++) {
                LinearLayout.LayoutParams lp = PcViews.matchWrap();
                if (i > 0) lp.topMargin = dp(10);
                inner.addView(appRow(list.get(i)), lp);
            }
            PcViews.MaxScroll sc = new PcViews.MaxScroll(c, 300);
            sc.addView(inner);
            mixerBox.addView(sc, PcViews.matchWrap());
            if (mixerOpen && mixerBox.getVisibility() != View.VISIBLE) {
                PcViews.animateHeight(mixerBox, true, 220);
                a.scrollIntoView(mixerBox);
            }
        });
    }

    private int mixerDragging;

    /**
     * Сессия микшера: имя (+ «PID n» у одноимённых) и строка громкости как у системной
     * (кнопка звука · ползунок · проценты). Громкость меняется вживую с троттлингом.
     */
    private View appRow(final PcMixer.Session s) {
        LinearLayout row = PcViews.col(c);
        LinearLayout top = PcViews.row(c);
        top.setPadding(dp(4), 0, dp(4), dp(6));
        top.addView(PcViews.single(PcViews.text(c, s.name, 12.5f, PcViews.TEXT, 500)), PcViews.weight(1));
        if (!s.detail.isEmpty()) {
            TextView d = PcViews.single(PcViews.monoText(c, s.detail, 10.5f, PcViews.MUTED));
            LinearLayout.LayoutParams dlp = PcViews.wrap();
            dlp.leftMargin = dp(8);
            top.addView(d, dlp);
        }
        row.addView(top, PcViews.matchWrap());

        final PcViews.VolRow vr = new PcViews.VolRow(c, false, PcAppIcons.VOL_ON);
        vr.muteBtn.setContentDescription(s.name);
        vr.slider.configure(0, 100, 1, PcViews.TEXT, false);
        vr.slider.setValue(s.percent);
        vr.value.setText(s.percent + "%");
        final boolean[] muted = {s.muted};
        styleAppMute(vr, muted[0]);
        final PcThrottle th = new PcThrottle(120, android.os.SystemClock::uptimeMillis, (rn, ms) -> a.ui.postDelayed(rn, ms));
        vr.slider.setListener(new PcViews.SliderListener() {
            private boolean dragging;

            @Override public void onInput(float v) {
                if (!dragging) {
                    dragging = true;
                    mixerDragging++;
                }
                vr.value.setText(PcMixer.clampPercent(v) + "%");
                th.submit(() -> a.api("POST", "/app_volume", PcMixer.volumeBody(s.pid, v), 6000, null));
            }

            @Override public void onCommit(float v) {
                if (dragging) {
                    dragging = false;
                    mixerDragging = Math.max(0, mixerDragging - 1);
                }
                vr.value.setText(PcMixer.clampPercent(v) + "%");
                th.commit(() -> a.api("POST", "/app_volume", PcMixer.volumeBody(s.pid, v), 6000, r -> {
                    if (!r.message().isEmpty()) a.status(r.message());
                }));
            }
        });
        vr.muteBtn.setOnClickListener(v -> {
            final boolean want = !muted[0];
            muted[0] = want;
            styleAppMute(vr, want);
            a.api("POST", "/app_volume/mute", PcMixer.muteBody(s.pid, want), 6000, r -> {
                if (!r.message().isEmpty()) a.status(r.message());
                if (!r.ok()) {
                    // сессия закрылась или ошибка — откат и свежий список
                    muted[0] = !want;
                    styleAppMute(vr, !want);
                    loadAppVolumes();
                }
            });
        });
        row.addView(vr, PcViews.matchWrap());
        return row;
    }

    private void styleAppMute(PcViews.VolRow vr, boolean muted) {
        vr.muteBtn.setIcon(muted ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_ON, PcViews.SUBTEXT);
        vr.slider.configure(0, 100, 1, muted ? PcViews.MUTED : PcViews.TEXT, false);
        vr.value.setTextColor(muted ? PcViews.MUTED : PcViews.SUBTEXT);
    }
}
