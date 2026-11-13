package com.pccontrol.remote;

import android.content.Context;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/**
 * "YouTube Music" player card = web/index.html .ytm-player + web/js/media.js:
 * now playing, timeline with seek, mode menu, transport, player volume, queue / history panel.
 */
final class PcMediaCard {
    private final MainActivity a;
    private final Context c;
    final LinearLayout root;

    // views
    private LinearLayout empty, body, timeline, queuePanel, queueTabs;
    private ImageView thumb, artFallback;
    private TextView title, artist, curTime, durTime, queueCount, tabQueue, tabHistory;
    private PcViews.Slider seek;
    private PcViews.RoundIcon modeBtn, historyBtn, prevBtn, nextBtn, scrollActiveBtn, refreshBtn;
    private FrameLayout playBtn;
    private ImageView playIcon;
    private PcViews.Btn queuePill;
    private PcViews.VolRow vol;
    private LinearLayout queueList;
    private PcViews.MaxScroll queueScroll;
    private PopupWindow modeMenu;

    // state (media.js mediaState)
    boolean playing;
    private double position, duration, anchorPos, seekTarget;
    private long anchorTime, seekDeadline;
    private boolean seeking, seekDragging, playerVolDragging, playerMuted, available;
    private String mode = "normal", lastTitle = "", lastQueueVersion = "", thumbUrl = "";
    private int lastQueueIdx = Integer.MIN_VALUE;
    private int pollSeq;
    private long lastCmd;
    private boolean cmdPending, queueLoading;
    // queue cache
    boolean queueOpen;
    private String queueTab = "queue";
    private List<PcJson.O> tracks = new ArrayList<>(), history = new ArrayList<>();
    private int currentIndex = 0;
    private String queueSource = "";
    private int lastScrolledIdx = Integer.MIN_VALUE;
    private final Runnable volRelease = new Runnable() {
        @Override public void run() { playerVolDragging = false; }
    };

    PcMediaCard(MainActivity act) {
        a = act;
        c = act;
        root = PcViews.col(c);
        // .ytm-player: 165deg gradient, border-strong, radius 22, padding 18/16/16
        root.setBackground(PcViews.gradient(c, GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{0xFF1C1417, 0xFF121212, 0xFF0E0E0E}, new float[]{0f, 0.55f, 1f}, 22, PcViews.BORDER_STRONG, 1));
        root.setPadding(dp(16), dp(18), dp(16), dp(16));
        root.setElevation(dp(10));
        buildEmpty();
        buildBody();
        showAvailable(false);
    }

    private int dp(float v) {
        return PcViews.dp(c, v);
    }

    // ------------------------------------------------------------------ build
    private void buildEmpty() {
        empty = PcViews.row(c);
        empty.setPadding(dp(2), dp(6), dp(2), dp(6));
        FrameLayout art = new FrameLayout(c);
        art.setBackground(PcViews.rect(c, PcViews.SURFACE2, 10, 0, 0));
        art.addView(PcViews.icon(c, PcAppIcons.MUSIC, PcViews.MUTED, 22), new FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER));
        empty.addView(art, PcViews.lp(dp(52), dp(52)));
        LinearLayout txt = PcViews.col(c);
        TextView t1 = PcViews.text(c, a.t("media_empty_title"), 14f, PcViews.TEXT, 600);
        TextView t2 = PcViews.text(c, a.t("media_empty_sub"), 12f, PcViews.MUTED, 400);
        t2.setPadding(0, dp(3), 0, 0);
        txt.addView(t1);
        txt.addView(t2);
        LinearLayout.LayoutParams tp = PcViews.weight(1);
        tp.leftMargin = dp(14);
        empty.addView(txt, tp);
        root.addView(empty, PcViews.matchWrap());
    }

    private void buildBody() {
        body = PcViews.col(c);
        // header: art 72 · title/artist · history button
        LinearLayout head = PcViews.row(c);
        FrameLayout art = new FrameLayout(c);
        art.setBackground(PcViews.rect(c, 0xFF1F1F1F, 10, 0x0FFFFFFF, 1));
        art.setClipToOutline(true);
        art.setElevation(dp(8));
        artFallback = PcViews.icon(c, PcAppIcons.MUSIC, PcViews.MUTED, 28);
        art.addView(artFallback, new FrameLayout.LayoutParams(dp(28), dp(28), Gravity.CENTER));
        thumb = new ImageView(c);
        thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
        thumb.setVisibility(View.GONE);
        art.addView(thumb, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        head.addView(art, PcViews.lp(dp(72), dp(72)));
        LinearLayout info = PcViews.col(c);
        title = PcViews.single(PcViews.text(c, "—", 16.5f, PcViews.TEXT, 700));
        title.setLetterSpacing(-0.01f);
        artist = PcViews.single(PcViews.text(c, "", 13.5f, PcViews.SUBTEXT, 400));
        artist.setPadding(0, dp(5), 0, 0);
        info.addView(title, PcViews.matchWrap());
        info.addView(artist, PcViews.matchWrap());
        LinearLayout.LayoutParams ip = PcViews.weight(1);
        ip.leftMargin = dp(14);
        ip.rightMargin = dp(8);
        head.addView(info, ip);
        historyBtn = new PcViews.RoundIcon(c, PcAppIcons.HISTORY, 40, 22, PcViews.SUBTEXT);
        historyBtn.setContentDescription(a.t("media_history_tip"));
        historyBtn.setOnClickListener(v -> openQueueTab("history"));
        head.addView(historyBtn);
        LinearLayout.LayoutParams hp = PcViews.matchWrap();
        hp.bottomMargin = dp(14);
        body.addView(head, hp);

        // timeline
        timeline = PcViews.col(c);
        seek = new PcViews.Slider(c);
        seek.configure(0, 100, 0.5f, PcViews.RED, true);
        seek.setLayoutParams(PcViews.lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(30)));
        seek.setListener(new PcViews.SliderListener() {
            @Override public void onInput(float v) {
                seeking = true;
                seekDragging = true;
                updateSeekVisual(v, duration);
            }

            @Override public void onCommit(float v) {
                commitSeek(v);
            }
        });
        timeline.addView(seek);
        LinearLayout times = PcViews.row(c);
        curTime = PcViews.text(c, "0:00", 11.5f, PcViews.SUBTEXT, 400);
        durTime = PcViews.text(c, "0:00", 11.5f, PcViews.SUBTEXT, 400);
        curTime.setFontFeatureSettings("tnum");
        durTime.setFontFeatureSettings("tnum");
        times.addView(curTime, PcViews.weight(1));
        times.addView(durTime);
        LinearLayout.LayoutParams tmp = PcViews.matchWrap();
        tmp.topMargin = -dp(3);
        times.setPadding(dp(2), 0, dp(2), 0);
        timeline.addView(times, tmp);
        timeline.setVisibility(View.GONE);
        LinearLayout.LayoutParams tlp = PcViews.matchWrap();
        tlp.bottomMargin = dp(10);
        body.addView(timeline, tlp);

        // transport: mode · prev / play / next · queue
        // Раньше — FrameLayout (центр по центру, пилюля прижата вправо): на узком экране
        // пилюля «Очередь» наезжала на «Вперёд». Теперь своя раскладка (PcLayoutMath.transport).
        TransportRow transport = new TransportRow(c);
        modeBtn = new PcViews.RoundIcon(c, PcAppIcons.MODE_NORMAL, 40, 22, PcViews.TEXT);
        modeBtn.setContentDescription(a.t("media_mode_tip"));
        modeBtn.setOnClickListener(v -> toggleModeMenu());
        transport.addView(modeBtn);
        prevBtn = new PcViews.RoundIcon(c, PcAppIcons.PREV, 40, 22, PcViews.TEXT);
        prevBtn.setContentDescription(a.t("media_prev_tip"));
        prevBtn.setOnClickListener(v -> control("prev", v));
        transport.addView(prevBtn);
        playBtn = new FrameLayout(c);
        playBtn.setBackground(PcViews.oval(PcViews.TEXT));
        playBtn.setElevation(dp(6));
        playIcon = PcViews.icon(c, PcAppIcons.PLAY, PcViews.BG, 26);
        playBtn.addView(playIcon, new FrameLayout.LayoutParams(dp(26), dp(26), Gravity.CENTER));
        playBtn.setClickable(true);
        playBtn.setContentDescription(a.t("media_playpause_tip"));
        PcViews.pressable(playBtn, 0.94f);
        playBtn.setOnClickListener(v -> control("playpause", v));
        transport.addView(playBtn);
        nextBtn = new PcViews.RoundIcon(c, PcAppIcons.NEXT, 40, 22, PcViews.TEXT);
        nextBtn.setContentDescription(a.t("media_next_tip"));
        nextBtn.setOnClickListener(v -> control("next", v));
        transport.addView(nextBtn);
        queuePill = new PcViews.Btn(c, PcAppIcons.QUEUE, a.t("media_queue_btn"), 16);
        queuePill.pad(12, 8).size(12.5f).radius(999);
        queuePill.setContentDescription(a.t("media_queue_btn"));
        ((LinearLayout.LayoutParams) queuePill.label.getLayoutParams()).leftMargin = dp(6);
        queuePill.setOnClickListener(v -> toggleQueuePanel());
        styleQueuePill();
        transport.addView(queuePill);
        LinearLayout.LayoutParams trp = PcViews.matchWrap();
        trp.topMargin = dp(6);
        trp.bottomMargin = dp(14);
        body.addView(transport, trp);

        // player volume
        vol = new PcViews.VolRow(c, true, PcAppIcons.VOL_LOW);
        vol.muteBtn.setContentDescription(a.t("media_vol_tip"));
        vol.slider.configure(0, 100, 1, PcViews.TEXT, false);
        vol.slider.setValue(100);
        vol.value.setText("100%");
        vol.slider.setListener(new PcViews.SliderListener() {
            @Override public void onInput(float v) {
                playerVolDragging = true;
                a.ui.removeCallbacks(volRelease);
                vol.value.setText(Math.round(v) + "%");
            }

            @Override public void onCommit(float v) {
                commitPlayerVolume(Math.round(v));
            }
        });
        vol.muteBtn.setOnClickListener(v -> togglePlayerMute());
        // QA U-7: caption — the audio card has a second (system) volume slider
        TextView volCap = PcViews.text(c, a.t("media_vol_tip"), 11f, PcViews.MUTED, 500);
        volCap.setPadding(dp(4), 0, 0, dp(3));
        body.addView(volCap, PcViews.matchWrap());
        body.addView(vol, PcViews.matchWrap());

        buildQueuePanel();
        root.addView(body, PcViews.matchWrap());
    }

    private void styleQueuePill() {
        if (queueOpen) {
            queuePill.setBackground(PcViews.pill(c, PcViews.TEXT, 0));
            queuePill.label.setTextColor(PcViews.BG);
            PcViews.tintIcon(queuePill.iconView, PcViews.BG);
        } else {
            queuePill.setBackground(PcViews.pill(c, PcViews.SURFACE2, PcViews.BORDER));
            queuePill.label.setTextColor(PcViews.TEXT);
            PcViews.tintIcon(queuePill.iconView, PcViews.TEXT);
        }
        queuePill.label.setTypeface(PcViews.face(600));
    }

    private void buildQueuePanel() {
        queuePanel = PcViews.col(c);
        queuePanel.addView(PcViews.hr(c));
        // Шапка: вкладки слева, кнопки справа; подпись источника между ними, а если не влезает —
        // своей строкой под вкладками (раньше «Songs · 13 / 58» наезжала на вкладки)
        QueueHead head = new QueueHead(c);
        head.setPadding(dp(2), dp(12), dp(2), 0);
        queueTabs = PcViews.row(c);
        queueTabs.setBackground(PcViews.pill(c, PcViews.SURFACE2, PcViews.BORDER));
        queueTabs.setPadding(dp(3), dp(3), dp(3), dp(3));
        tabQueue = qTab(a.t("tab_queue"));
        tabHistory = qTab(a.t("tab_history"));
        tabQueue.setOnClickListener(v -> switchQueueTab("queue"));
        tabHistory.setOnClickListener(v -> switchQueueTab("history"));
        queueTabs.addView(tabQueue);
        LinearLayout.LayoutParams hp = PcViews.wrap();
        hp.leftMargin = dp(3);
        queueTabs.addView(tabHistory, hp);
        head.addView(queueTabs);
        queueCount = PcViews.single(PcViews.monoText(c, "", 11f, PcViews.SUBTEXT));
        head.addView(queueCount);
        LinearLayout headBtns = PcViews.row(c);
        scrollActiveBtn = new PcViews.RoundIcon(c, PcAppIcons.TARGET, 24, 14, PcViews.SUBTEXT);
        scrollActiveBtn.setContentDescription(a.t("queue_to_current_tip"));
        scrollActiveBtn.setOnClickListener(v -> scrollToActive(true));
        LinearLayout.LayoutParams sp = PcViews.lp(dp(40), dp(40)); // QA U-8: touch zone >= 40dp (icon stays small)
        sp.topMargin = sp.bottomMargin = -dp(8);
        sp.leftMargin = dp(6);
        headBtns.addView(scrollActiveBtn, sp);
        refreshBtn = new PcViews.RoundIcon(c, PcAppIcons.SYNC, 24, 13, PcViews.SUBTEXT);
        refreshBtn.setContentDescription(a.t("queue_refresh_tip"));
        refreshBtn.setOnClickListener(v -> refreshQueueExplicit());
        LinearLayout.LayoutParams rp = PcViews.lp(dp(40), dp(40)); // QA U-8: touch zone >= 40dp (icon stays small)
        rp.topMargin = rp.bottomMargin = -dp(8);
        rp.leftMargin = dp(6);
        headBtns.addView(refreshBtn, rp);
        head.addView(headBtns);
        LinearLayout.LayoutParams hlp = PcViews.matchWrap();
        hlp.bottomMargin = dp(10);
        queuePanel.addView(head, hlp);
        queueScroll = new PcViews.MaxScroll(c, 320);
        queueList = PcViews.col(c);
        queueScroll.addView(queueList, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        queuePanel.addView(queueScroll, PcViews.matchWrap());
        queuePanel.setVisibility(View.GONE);
        LinearLayout.LayoutParams qp = PcViews.matchWrap();
        qp.topMargin = dp(14);
        body.addView(queuePanel, qp);
        syncQueueTabs();
    }

    private TextView qTab(String s) {
        TextView t = PcViews.single(PcViews.text(c, s, 12f, PcViews.SUBTEXT, 600));
        t.setPadding(dp(12), dp(5), dp(12), dp(5));
        t.setClickable(true);
        PcViews.pressable(t);
        return t;
    }

    private void syncQueueTabs() {
        boolean q = "queue".equals(queueTab);
        tabQueue.setBackground(q ? PcViews.pill(c, PcViews.TEXT, 0) : null);
        tabQueue.setTextColor(q ? PcViews.BG : PcViews.SUBTEXT);
        tabHistory.setBackground(!q ? PcViews.pill(c, PcViews.TEXT, 0) : null);
        tabHistory.setTextColor(!q ? PcViews.BG : PcViews.SUBTEXT);
        historyBtn.setHighlighted(queueOpen && !q);
        scrollActiveBtn.setVisibility(q ? View.VISIBLE : View.GONE);
    }

    // ------------------------------------------------------------------ rendering
    private void showAvailable(boolean on) {
        available = on;
        empty.setVisibility(on ? View.GONE : View.VISIBLE);
        body.setVisibility(on ? View.VISIBLE : View.GONE);
    }

    private void updateSeekVisual(double pos, double dur) {
        timeline.setVisibility(View.VISIBLE);
        double eff = dur > 0 ? dur : (duration > 0 ? duration : 200);
        double cl = Math.max(0, Math.min(eff, pos));
        seek.setRange(0, (float) eff);
        if (!seek.isDragging() || seekDragging) seek.setValue((float) cl);
        curTime.setText(PcConn.fmtTime(cl));
        durTime.setText(dur > 0 ? PcConn.fmtTime(dur) : "—");
    }

    private void renderMode(String m) {
        mode = m == null || m.isEmpty() ? "normal" : m;
        String[] icon = "repeat".equals(mode) ? PcAppIcons.MODE_REPEAT : "shuffle".equals(mode) ? PcAppIcons.MODE_SHUFFLE : PcAppIcons.MODE_NORMAL;
        modeBtn.setIcon(icon, PcViews.TEXT);
        modeBtn.setModeActive(!"normal".equals(mode));
    }

    private void setPlayIcon() {
        PcViews.setIcon(playIcon, playing ? PcAppIcons.PAUSE : PcAppIcons.PLAY, PcViews.BG);
    }

    // ------------------------------------------------------------------ polling
    void pollMedia() {
        final int seq = ++pollSeq;
        a.api("GET", "/media/now", null, 6000, r -> {
            if (seq != pollSeq) return;
            PcJson.O d = r.json();
            if (!r.ok() || !d.bool("available", false)) {
                showAvailable(false);
                playing = false;
                return;
            }
            showAvailable(true);
            String tt = d.str("title");
            title.setText(tt.isEmpty() ? a.t("track_untitled") : tt);
            StringBuilder sub = new StringBuilder();
            String ar = d.str("artist"), al = d.str("album");
            if (!ar.isEmpty()) sub.append(ar);
            if (!al.isEmpty() && !al.equals(ar) && !al.equals(tt)) {
                if (sub.length() > 0) sub.append(" • ");
                sub.append(al);
            }
            artist.setText(sub.length() > 0 ? sub.toString() : "YouTube Music");
            String th = d.str("thumbnail");
            if (!th.isEmpty()) {
                if (!th.equals(thumbUrl)) {
                    thumbUrl = th;
                    PcImages.load(thumb, th, dp(72), ok -> {
                        thumb.setVisibility(ok ? View.VISIBLE : View.GONE);
                        artFallback.setVisibility(ok ? View.GONE : View.VISIBLE);
                    });
                }
            } else {
                thumbUrl = "";
                thumb.setVisibility(View.GONE);
                thumb.setImageDrawable(null);
                artFallback.setVisibility(View.VISIBLE);
            }
            boolean was = playing;
            playing = "playing".equals(d.str("status"));
            setPlayIcon();
            double srvPos = d.num("position", 0), srvDur = d.num("duration", 0);
            long now = SystemClock.elapsedRealtime();
            if (seeking && !seekDragging) {
                boolean confirmed = Math.abs(srvPos - seekTarget) < 3;
                if (confirmed || now > seekDeadline) {
                    seeking = false;
                    anchorPos = srvPos;
                    anchorTime = now;
                    position = srvPos;
                }
            }
            if (!seeking) {
                duration = srvDur;
                double live = (anchorTime > 0 && playing) ? anchorPos + (now - anchorTime) / 1000.0 : position;
                if (Math.abs(live - srvPos) > 1.5 || (!was && playing) || !tt.equals(lastTitle)) {
                    anchorPos = srvPos;
                    anchorTime = now;
                    position = srvPos;
                }
                updateSeekVisual(position, duration);
            }
            if (!playerVolDragging && d.has("volume")) {
                int v = d.integer("volume", 100);
                vol.slider.setValue(v);
                // volume_ok=false: the player's volume is not known yet — no invented "100%"
                vol.value.setText(d.has("volume_ok") && !d.bool("volume_ok", true) ? "—" : v + "%");
                playerMuted = d.bool("muted", false);
                vol.muteBtn.setIcon(playerMuted ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_LOW, PcViews.SUBTEXT);
            }
            if (d.has("mode")) renderMode(d.str("mode"));
            boolean titleChanged = !tt.isEmpty() && !tt.equals(lastTitle);
            String qv = d.str("queue_version");
            boolean versionChanged = !qv.isEmpty() && !qv.equals(lastQueueVersion);
            boolean idxChanged = d.has("queue_current_index") && d.integer("queue_current_index", 0) != lastQueueIdx;
            if (titleChanged || versionChanged || idxChanged) {
                if (!tt.isEmpty()) lastTitle = tt;
                if (!qv.isEmpty()) lastQueueVersion = qv;
                if (d.has("queue_current_index")) lastQueueIdx = d.integer("queue_current_index", 0);
                loadQueue(false, titleChanged || idxChanged);
            }
        });
    }

    /** 400 ms timeline ticker (startMediaTimelineTicker). */
    void tick() {
        if (playing && !seekDragging && duration > 0 && anchorTime > 0 && available && !seeking) {
            double live = Math.min(duration, Math.max(0, anchorPos + (SystemClock.elapsedRealtime() - anchorTime) / 1000.0));
            position = live;
            updateSeekVisual(live, duration);
        }
    }

    long pollInterval() {
        return playing ? 2500 : (duration > 0 ? 5000 : 9000);
    }

    private void commitSeek(float v) {
        seekDragging = false;
        seeking = true;
        seekTarget = v;
        long now = SystemClock.elapsedRealtime();
        seekDeadline = now + 4000;
        position = v;
        anchorPos = v;
        anchorTime = now;
        updateSeekVisual(v, duration);
        a.api("POST", "/media/control", PcJson.map("action", "seek", "position", (double) v), 8000, r -> {
            if (!r.ok()) {
                if (!r.message().isEmpty()) a.status(r.message());
                seeking = false;
            }
        });
        a.ui.postDelayed(this::pollMedia, 300);
        a.ui.postDelayed(this::pollMedia, 1000);
    }

    private void commitPlayerVolume(final int pct) {
        vol.value.setText(pct + "%");
        a.api("POST", "/media/volume", PcJson.map("percent", pct), 6000, r -> {
            PcJson.O d = r.json();
            if (r.ok() && d.has("percent")) {
                vol.slider.setValue(d.integer("percent", pct));
                vol.value.setText(d.integer("percent", pct) + "%");
            }
            if (!r.message().isEmpty()) a.status(r.message());
            a.ui.removeCallbacks(volRelease);
            a.ui.postDelayed(volRelease, 1200);
        });
    }

    private void togglePlayerMute() {
        final boolean wanted = !playerMuted;
        playerMuted = wanted;
        vol.muteBtn.setIcon(playerMuted ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_LOW, PcViews.SUBTEXT);
        a.api("POST", "/media/volume", PcJson.map("mute", wanted), 6000, r -> {
            PcJson.O d = r.json();
            if (r.ok()) {
                if (d.raw("muted") instanceof Boolean) playerMuted = d.bool("muted", wanted);
            } else {
                playerMuted = !wanted; // not applied on the PC: show the real state and the reason
                if (!r.message().isEmpty()) a.status(r.message());
            }
            vol.muteBtn.setIcon(playerMuted ? PcAppIcons.VOL_MUTE : PcAppIcons.VOL_LOW, PcViews.SUBTEXT);
        });
    }

    private void control(String action, final View pressed) {
        long now = SystemClock.elapsedRealtime();
        if (now - lastCmd < 300) return;
        if (cmdPending && now - lastCmd < 1500) return;
        lastCmd = now;
        cmdPending = true;
        if (pressed != null) pressed.setAlpha(0.55f);
        if ("playpause".equals(action)) {
            playing = !playing;
            setPlayIcon();
            anchorPos = position;
            anchorTime = now;
        }
        a.api("POST", "/media/control", PcJson.map("action", action), 8000, r -> {
            cmdPending = false;
            if (pressed != null) pressed.animate().alpha(1f).setDuration(150).start();
            if (!r.ok() && !r.message().isEmpty()) a.status(r.message());
            a.ui.postDelayed(() -> {
                pollMedia();
                loadQueue(false, false);
            }, 200);
        });
    }

    // ------------------------------------------------------------------ mode menu
    private void toggleModeMenu() {
        if (modeMenu != null && modeMenu.isShowing()) {
            modeMenu.dismiss();
            return;
        }
        LinearLayout box = PcViews.col(c);
        box.setBackground(PcViews.rect(c, 0xFF212121, 14, PcViews.BORDER_STRONG, 1));
        box.setPadding(dp(5), dp(5), dp(5), dp(5));
        box.setElevation(dp(14));
        String[] keys = {"normal", "repeat", "shuffle"};
        String[][] icons = {PcAppIcons.MODE_NORMAL, PcAppIcons.MODE_REPEAT, PcAppIcons.MODE_SHUFFLE};
        String[] labels = {a.t("mode_normal"), a.t("mode_repeat"), a.t("mode_shuffle")};
        for (int i = 0; i < 3; i++) {
            final String k = keys[i];
            boolean on = k.equals(mode);
            LinearLayout it = PcViews.row(c);
            it.setPadding(dp(12), dp(10), dp(12), dp(10));
            it.setBackground(on ? PcViews.rect(c, 0x1AFFFFFF, 10, 0, 0) : null);
            it.addView(PcViews.icon(c, icons[i], PcViews.TEXT, 22));
            TextView lt = PcViews.text(c, labels[i], 13f, PcViews.TEXT, 500);
            LinearLayout.LayoutParams lp = PcViews.weight(1);
            lp.leftMargin = dp(10);
            it.addView(lt, lp);
            it.addView(PcViews.text(c, on ? "✓" : "", 13f, PcViews.RED, 700));
            it.setClickable(true);
            PcViews.pressable(it);
            it.setOnClickListener(v -> {
                if (modeMenu != null) modeMenu.dismiss();
                setPlaybackMode(k);
            });
            box.addView(it, PcViews.matchWrap());
        }
        FrameLayout holder = new FrameLayout(c);
        int pad = dp(14);
        holder.setPadding(pad, pad, pad, pad);
        holder.addView(box, new FrameLayout.LayoutParams(dp(235), ViewGroup.LayoutParams.WRAP_CONTENT));
        holder.measure(View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
        modeMenu = new PopupWindow(holder, ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, true);
        modeMenu.setBackgroundDrawable(new ColorDrawable(0));
        modeMenu.setOutsideTouchable(true);
        modeMenu.setAnimationStyle(android.R.style.Animation_Dialog);
        int h = holder.getMeasuredHeight();
        modeMenu.showAsDropDown(modeBtn, -pad, -(modeBtn.getHeight() + h - pad + dp(8)));
    }

    void dismissPopups() {
        if (modeMenu != null && modeMenu.isShowing()) modeMenu.dismiss();
    }

    private void setPlaybackMode(String m) {
        renderMode(m);
        a.api("POST", "/media/mode", PcJson.map("mode", m), 6000, r -> {
            if (r.ok() && r.json().has("mode")) renderMode(r.json().str("mode"));
            if (!r.message().isEmpty()) a.status(r.message());
            a.ui.postDelayed(this::pollMedia, 600);
        });
    }

    // ------------------------------------------------------------------ queue
    boolean closeQueueIfOpen() {
        if (queueOpen) {
            toggleQueuePanel();
            return true;
        }
        return false;
    }

    private void toggleQueuePanel() {
        queueOpen = !queueOpen;
        PcViews.animateHeight(queuePanel, queueOpen, 260);
        styleQueuePill();
        syncQueueTabs();
        if (queueOpen) {
            renderQueue(true);
            loadQueue(false, true);
            a.scrollIntoView(queuePanel);
        }
    }

    private void openQueueTab(String tab) {
        if (queueOpen && queueTab.equals(tab)) {
            toggleQueuePanel();
            return;
        }
        queueTab = tab;
        if (!queueOpen) {
            queueOpen = true;
            PcViews.animateHeight(queuePanel, true, 260);
            styleQueuePill();
        }
        syncQueueTabs();
        renderQueue(true);
        loadQueue(false, true);
        a.scrollIntoView(queuePanel);
    }

    private void switchQueueTab(String tab) {
        queueTab = tab;
        syncQueueTabs();
        renderQueue("queue".equals(tab));
        loadQueue(false, "queue".equals(tab));
    }

    void loadQueue(final boolean force, final boolean autoScroll) {
        if (queueLoading) return;
        queueLoading = true;
        a.api("GET", "/media/queue", null, 8000, r -> {
            queueLoading = false;
            if (!r.ok()) return;
            int prev = currentIndex;
            applyQueue(r.json());
            lastQueueVersion = r.json().str("queue_version", lastQueueVersion);
            lastQueueIdx = currentIndex;
            if (queueOpen) renderQueue(autoScroll || prev != currentIndex);
        });
    }

    private void applyQueue(PcJson.O d) {
        if (d.has("tracks")) tracks = d.objs("tracks");
        if (d.has("history")) history = d.objs("history");
        currentIndex = d.integer("current_index", 0);
        if (d.has("queue_source")) queueSource = d.str("queue_source");
    }

    private void refreshQueueExplicit() {
        refreshBtn.animate().rotationBy(360).setDuration(800).start();
        queueList.setAlpha(0.35f);
        a.api("POST", "/media/queue/refresh", null, 15000, r -> {
            queueList.animate().alpha(1f).setDuration(200).start();
            if (r.ok()) {
                applyQueue(r.json());
                renderQueue(true);
            }
        });
    }

    private void renderQueue(boolean autoScroll) {
        boolean hist = "history".equals(queueTab);
        List<PcJson.O> items = hist ? history : tracks;
        if (hist) {
            queueCount.setText(items.isEmpty() ? "" : items.size() + a.t("history_listened_suffix"));
        } else if (!items.isEmpty()) {
            int cur = currentIndex >= 0 ? currentIndex + 1 : 1;
            queueCount.setText((queueSource.isEmpty() ? "" : queueSource + " · ") + cur + " / " + items.size());
        } else {
            queueCount.setText("");
        }
        queueList.removeAllViews();
        if (items.isEmpty()) {
            TextView e = PcViews.text(c, a.t(hist ? "history_empty" : "queue_empty"), 12.5f, PcViews.MUTED, 400);
            e.setPadding(dp(10), dp(10), dp(10), dp(10));
            queueList.addView(e, PcViews.matchWrap());
            return;
        }
        View activeRow = null;
        for (int i = 0; i < items.size(); i++) {
            PcJson.O tr = items.get(i);
            View row = queueRow(tr, i, hist);
            LinearLayout.LayoutParams p = PcViews.matchWrap();
            if (i > 0) p.topMargin = dp(2);
            queueList.addView(row, p);
            if (tr.bool("active", false)) activeRow = row;
        }
        if (!hist && (autoScroll || currentIndex != lastScrolledIdx)) {
            lastScrolledIdx = currentIndex;
            final View target = activeRow;
            if (target != null) queueList.postDelayed(() -> scrollTo(target, true), 60);
        }
    }

    private View queueRow(final PcJson.O tr, int i, final boolean hist) {
        boolean active = tr.bool("active", false);
        LinearLayout row = PcViews.row(c);
        row.setPadding(dp(8), dp(6), dp(8), dp(6));
        row.setBackground(active ? PcViews.rect(c, 0x24FF0033, 10, 0x47FF0033, 1) : PcViews.rect(c, 0, 10, 0, 0));
        row.setTag(active ? "active" : null);
        TextView idx = PcViews.monoText(c, active ? "▶" : String.valueOf(i + 1), 11f, active ? PcViews.PINK : PcViews.MUTED);
        if (active) idx.setTypeface(android.graphics.Typeface.create(PcViews.mono(), android.graphics.Typeface.BOLD));
        idx.setGravity(Gravity.CENTER);
        idx.setMinWidth(dp(20));
        row.addView(idx);
        FrameLayout th = new FrameLayout(c);
        th.setBackground(PcViews.rect(c, 0xFF222222, 6, 0, 0));
        th.setClipToOutline(true);
        final ImageView fb = PcViews.icon(c, PcAppIcons.MUSIC, PcViews.MUTED, 18);
        th.addView(fb, new FrameLayout.LayoutParams(dp(18), dp(18), Gravity.CENTER));
        String thumbUrl = tr.str("thumbnail");
        if (!thumbUrl.isEmpty()) {
            final ImageView img = new ImageView(c);
            img.setScaleType(ImageView.ScaleType.CENTER_CROP);
            th.addView(img, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            PcImages.load(img, thumbUrl, dp(40), ok -> fb.setVisibility(ok ? View.GONE : View.VISIBLE));
        }
        LinearLayout.LayoutParams thp = PcViews.lp(dp(40), dp(40));
        thp.leftMargin = dp(10);
        row.addView(th, thp);
        LinearLayout meta = PcViews.col(c);
        String tt = tr.str("title");
        TextView t1 = PcViews.single(PcViews.text(c, tt.isEmpty() ? a.t("track_untitled") : tt, 13.5f,
                active ? PcViews.PINK : PcViews.TEXT, active ? 600 : 500));
        TextView t2 = PcViews.single(PcViews.text(c, tr.str("artist"), 12f, PcViews.SUBTEXT, 400));
        t2.setPadding(0, dp(2), 0, 0);
        meta.addView(t1, PcViews.matchWrap());
        meta.addView(t2, PcViews.matchWrap());
        LinearLayout.LayoutParams mp = PcViews.weight(1);
        mp.leftMargin = dp(10);
        row.addView(meta, mp);
        String durText;
        if (hist) {
            String time = active ? a.t("badge_now") : PcConn.fmtClock(tr.num("ts", 0));
            String dur = tr.str("duration");
            durText = (!time.isEmpty() && !dur.isEmpty()) ? dur + " · " + time : (!dur.isEmpty() ? dur : time);
        } else {
            durText = tr.str("duration");
        }
        TextView du = PcViews.monoText(c, durText, 11.5f, PcViews.MUTED);
        du.setGravity(Gravity.END);
        du.setMinWidth(dp(34));
        LinearLayout.LayoutParams dpp = PcViews.wrap();
        dpp.leftMargin = dp(4);
        row.addView(du, dpp);
        if (!hist && !active) {
            row.addView(actBtn(PcAppIcons.NEXT, false, a.t("queue_play_next_tip"), v -> playNext(tr)));
            row.addView(actBtn(PcAppIcons.CLOSE, true, a.t("queue_remove_tip"), v -> removeTrack(tr)));
        }
        row.setClickable(true);
        PcViews.pressable(row, 0.985f);
        row.setOnClickListener(v -> {
            if (hist) playHistory(tr);
            else playQueueItem(tr);
        });
        return row;
    }

    private View actBtn(String[] icon, final boolean del, String desc, View.OnClickListener l) {
        final FrameLayout b = new FrameLayout(c);
        ImageView iv = PcViews.icon(c, icon, PcViews.MUTED, 13);
        b.addView(iv, new FrameLayout.LayoutParams(dp(13), dp(13), Gravity.CENTER));
        b.setAlpha(0.85f);
        b.setContentDescription(desc);
        b.setClickable(true);
        b.setOnClickListener(l);
        b.setOnTouchListener((v, ev) -> {
            int act = ev.getActionMasked();
            if (act == android.view.MotionEvent.ACTION_DOWN) {
                v.setAlpha(1f);
                v.setBackground(PcViews.rect(c, del ? 0x38FF0033 : 0x1FFFFFFF, 6, 0, 0));
                PcViews.tintIcon(iv, del ? PcViews.PINK : PcViews.TEXT);
            } else if (act == android.view.MotionEvent.ACTION_UP || act == android.view.MotionEvent.ACTION_CANCEL) {
                v.setAlpha(0.85f);
                v.setBackground(null);
                PcViews.tintIcon(iv, PcViews.MUTED);
            }
            return false;
        });
        LinearLayout.LayoutParams p = PcViews.lp(dp(40), dp(40)); // QA U-8: touch zone >= 40dp (icon stays small)
        p.topMargin = p.bottomMargin = -dp(8);
        p.leftMargin = dp(2);
        b.setLayoutParams(p);
        return b;
    }

    private void scrollToActive(boolean smooth) {
        if (!"queue".equals(queueTab)) return;
        for (int i = 0; i < queueList.getChildCount(); i++) {
            View ch = queueList.getChildAt(i);
            if ("active".equals(ch.getTag())) {
                scrollTo(ch, smooth);
                return;
            }
        }
    }

    private void scrollTo(View row, boolean smooth) {
        int target = Math.max(0, row.getTop() - queueScroll.getHeight() / 2 + row.getHeight() / 2);
        if (!smooth || Math.abs(queueScroll.getScrollY() - target) > dp(500)) queueScroll.scrollTo(0, target);
        else queueScroll.smoothScrollTo(0, target);
    }

    private void applyQueueResult(PcHttp.Resp r) {
        PcJson.O d = r.json();
        if (r.ok() && d.has("tracks")) {
            tracks = d.objs("tracks");
            if (d.has("history")) history = d.objs("history");
            currentIndex = d.integer("current_index", currentIndex);
            renderQueue(false);
        } else {
            loadQueue(false, false);
        }
        if (!r.message().isEmpty()) a.status(r.message());
    }

    private void removeTrack(PcJson.O tr) {
        a.api("POST", "/media/queue/remove", PcJson.map("index", tr.raw("index"), "title", tr.str("title"),
                "video_id", tr.str("video_id")), 8000, this::applyQueueResult);
    }

    private void playNext(PcJson.O tr) {
        a.api("POST", "/media/queue/play_next", PcJson.map("index", tr.raw("index"), "title", tr.str("title"),
                "video_id", tr.str("video_id")), 8000, this::applyQueueResult);
    }

    private void playQueueItem(PcJson.O tr) {
        String tt = tr.str("title");
        a.status(a.t("msg_play_track", "title", tt.isEmpty() ? a.t("track_untitled") : tt));
        queueList.setAlpha(0.5f);
        int idx = tr.integer("index", -1);
        for (PcJson.O x : tracks) x.map.put("active", x.integer("index", -2) == idx);
        currentIndex = idx;
        renderQueue(false);
        a.api("POST", "/media/queue/play", PcJson.map("index", tr.raw("index"), "title", tt,
                "artist", tr.str("artist"), "video_id", tr.str("video_id")), 10000, r -> {
            queueList.animate().alpha(1f).setDuration(200).start();
            if (!r.message().isEmpty()) a.status(r.message());
            a.ui.postDelayed(() -> { pollMedia(); loadQueue(false, false); }, 250);
            a.ui.postDelayed(() -> { pollMedia(); loadQueue(false, false); }, 750);
        });
    }

    private void playHistory(PcJson.O tr) {
        String tt = tr.str("title");
        a.status(a.t("msg_play_history", "title", tt.isEmpty() ? a.t("track_untitled") : tt));
        queueList.setAlpha(0.5f);
        a.api("POST", "/media/history/play", PcJson.map("h_index", tr.raw("h_index"), "title", tt,
                "artist", tr.str("artist"), "video_id", tr.str("video_id")), 10000, r -> {
            queueList.animate().alpha(1f).setDuration(200).start();
            if (!r.message().isEmpty()) a.status(r.message());
            queueTab = "queue";
            syncQueueTabs();
            a.ui.postDelayed(() -> { pollMedia(); loadQueue(true, true); }, 250);
            a.ui.postDelayed(() -> { pollMedia(); loadQueue(false, true); }, 850);
        });
    }

    // ------------------------------------------------------------------ layouts
    private static int exactly(int px) {
        return View.MeasureSpec.makeMeasureSpec(px, View.MeasureSpec.EXACTLY);
    }

    private static final int UNSPEC = View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED);

    /**
     * Строка управления: режим · назад ◯ вперёд · «Очередь» (web .ytm-transport grid 1fr auto 1fr).
     * Положения считает PcLayoutMath.transport: центр по центру, при нехватке места — меньше
     * промежутки, затем сдвиг центра влево, и только потом пилюля без текста. Без наложений.
     * Дети по порядку: modeBtn, prevBtn, playBtn, nextBtn, queuePill.
     */
    private final class TransportRow extends ViewGroup {
        private int gap, centerLeft;

        TransportRow(Context ctx) {
            super(ctx);
            setClipChildren(false);
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            int w = MeasureSpec.getSize(wSpec) - getPaddingLeft() - getPaddingRight();
            int b40 = dp(40), b56 = dp(56);
            modeBtn.measure(exactly(b40), exactly(b40));
            prevBtn.measure(exactly(b40), exactly(b40));
            nextBtn.measure(exactly(b40), exactly(b40));
            playBtn.measure(exactly(b56), exactly(b56));
            // ширину пилюли с текстом считаем без переключения видимости (иначе — цикл перерисовок)
            queuePill.label.measure(UNSPEC, UNSPEC);
            int iconOnly = queuePill.getPaddingLeft() + queuePill.getPaddingRight() + dp(16);
            int full = iconOnly + dp(6) + queuePill.label.getMeasuredWidth();
            int[] r = PcLayoutMath.transport(w, b40, b40, b56, full, iconOnly, dp(14), dp(8), dp(4));
            int want = r[PcLayoutMath.T_ICON_ONLY] == 1 ? GONE : VISIBLE;
            if (queuePill.label.getVisibility() != want) queuePill.label.setVisibility(want);
            queuePill.measure(UNSPEC, UNSPEC);
            gap = r[PcLayoutMath.T_GAP];
            centerLeft = r[PcLayoutMath.T_CENTER_LEFT];
            int h = Math.max(b56, queuePill.getMeasuredHeight());
            setMeasuredDimension(MeasureSpec.getSize(wSpec), h + getPaddingTop() + getPaddingBottom());
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            int pl = getPaddingLeft();
            int w = r - l - pl - getPaddingRight();
            int cy = getPaddingTop() + (b - t - getPaddingTop() - getPaddingBottom()) / 2;
            place(modeBtn, pl, cy);
            int x = pl + centerLeft;
            place(prevBtn, x, cy);
            x += prevBtn.getMeasuredWidth() + gap;
            place(playBtn, x, cy);
            x += playBtn.getMeasuredWidth() + gap;
            place(nextBtn, x, cy);
            place(queuePill, pl + w - queuePill.getMeasuredWidth(), cy);
        }

        private void place(View v, int x, int cy) {
            int h = v.getMeasuredHeight();
            v.layout(x, cy - h / 2, x + v.getMeasuredWidth(), cy - h / 2 + h);
        }
    }

    /**
     * Шапка панели очереди: [вкладки] … [подпись] [кнопки] в одну строку, если подпись влезает
     * целиком (PcLayoutMath.queueCountInline); иначе подпись — своей строкой под вкладками.
     * Дети по порядку: queueTabs, queueCount, ряд кнопок.
     */
    private final class QueueHead extends ViewGroup {
        private boolean inline = true;
        private int rowH;

        QueueHead(Context ctx) {
            super(ctx);
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            int w = MeasureSpec.getSize(wSpec) - getPaddingLeft() - getPaddingRight();
            View tabs = getChildAt(0), count = getChildAt(1), btns = getChildAt(2);
            btns.measure(UNSPEC, UNSPEC);
            int bw = btns.getMeasuredWidth();
            int gap = dp(8);
            tabs.measure(MeasureSpec.makeMeasureSpec(PcLayoutMath.queueTabsMax(w, bw, gap), MeasureSpec.AT_MOST), UNSPEC);
            boolean hasCount = count.getVisibility() != GONE && ((TextView) count).length() > 0;
            count.measure(UNSPEC, UNSPEC);
            int cw = hasCount ? count.getMeasuredWidth() : 0;
            inline = PcLayoutMath.queueCountInline(w, tabs.getMeasuredWidth(), cw, bw, gap);
            if (!inline) count.measure(MeasureSpec.makeMeasureSpec(Math.max(0, w), MeasureSpec.AT_MOST), UNSPEC);
            rowH = Math.max(tabs.getMeasuredHeight(), btns.getMeasuredHeight());
            if (inline) rowH = Math.max(rowH, count.getMeasuredHeight());
            int h = rowH + (inline || !hasCount ? 0 : dp(6) + count.getMeasuredHeight());
            setMeasuredDimension(MeasureSpec.getSize(wSpec), h + getPaddingTop() + getPaddingBottom());
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            View tabs = getChildAt(0), count = getChildAt(1), btns = getChildAt(2);
            int pl = getPaddingLeft(), pt = getPaddingTop();
            int right = r - l - getPaddingRight();
            int cy = pt + rowH / 2;
            layoutAt(tabs, pl, cy - tabs.getMeasuredHeight() / 2);
            int bx = right - btns.getMeasuredWidth();
            layoutAt(btns, bx, cy - btns.getMeasuredHeight() / 2);
            if (inline) layoutAt(count, bx - count.getMeasuredWidth(), cy - count.getMeasuredHeight() / 2);
            else layoutAt(count, pl + dp(2), pt + rowH + dp(6));
        }

        private void layoutAt(View v, int x, int y) {
            v.layout(x, y, x + v.getMeasuredWidth(), y + v.getMeasuredHeight());
        }
    }
}
