package com.pccontrol.remote;

import android.content.Context;
import android.text.InputType;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Card "Управление питанием": Wake-on-LAN, sleep / lock / reboot / shutdown, shutdown timer. */
final class PcPowerCard {
    private final MainActivity a;
    private final Context c;
    final LinearLayout root;
    final PcViews.Btn wolBtn;
    private final EditText minutes;
    private final TextView countdown;
    private long countdownEnd; // elapsedRealtime ms, 0 = none
    private final Runnable countdownTick = new Runnable() {
        @Override
        public void run() {
            long rem = (countdownEnd - android.os.SystemClock.elapsedRealtime() + 999) / 1000;
            if (countdownEnd == 0 || rem <= 0) {
                countdown.setText("");
                countdown.setVisibility(android.view.View.GONE);
                countdownEnd = 0;
                return;
            }
            countdown.setVisibility(android.view.View.VISIBLE);
            countdown.setText(a.t("timer_countdown_prefix") + PcConn.fmtCountdown(rem));
            a.ui.postDelayed(this, 1000);
        }
    };

    PcPowerCard(MainActivity act) {
        a = act;
        c = act;
        root = PcViews.card(c);
        root.addView(PcViews.cardTitle(c, a.t("card_power")));

        wolBtn = new PcViews.Btn(c, PcAppIcons.POWER, a.t("btn_wol"), 18);
        wolBtn.setStyle(PcViews.B_WOL);
        wolBtn.radius(14);
        wolBtn.setStyle(PcViews.B_DEFAULT);
        wolBtn.setStyle(PcViews.B_WOL);
        wolBtn.pad(16, 12);
        wolBtn.setOnClickListener(v -> a.wakeOnLan());
        LinearLayout.LayoutParams wp = PcViews.matchWrap();
        wp.bottomMargin = PcViews.dp(c, 10);
        root.addView(wolBtn, wp);

        PcViews.Grid g = new PcViews.Grid(c, 2, 0, 8);
        g.addView(action("btn_sleep", "sleep", false));
        g.addView(action("btn_lock", "lock", false));
        g.addView(action("btn_reboot", "reboot", true));
        g.addView(action("btn_shutdown", "shutdown", true));
        root.addView(g, PcViews.matchWrap());

        LinearLayout tr = PcViews.row(c);
        minutes = PcViews.field(c, a.t("timer_placeholder"), false, 13.5f);
        minutes.setInputType(InputType.TYPE_CLASS_NUMBER);
        minutes.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        minutes.setOnFocusChangeListener((v, has) -> v.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, has ? 0x47FFFFFF : PcViews.BORDER, 1)));
        tr.addView(minutes, PcViews.lp(PcViews.dp(c, 105), LinearLayout.LayoutParams.WRAP_CONTENT));
        PcViews.Btn start = new PcViews.Btn(c, null, a.t("btn_timer_start"));
        start.setOnClickListener(v -> startTimer());
        LinearLayout.LayoutParams sp = PcViews.weight(1);
        sp.leftMargin = PcViews.dp(c, 8);
        tr.addView(start, sp);
        PcViews.Btn cancel = new PcViews.Btn(c, null, a.t("btn_timer_cancel"));
        cancel.setStyle(PcViews.B_DANGER);
        cancel.pad(14, 10);
        cancel.setMinimumHeight(PcViews.dp(c, 42));
        cancel.setOnClickListener(v -> cancelTimer());
        LinearLayout.LayoutParams cp = PcViews.wrap();
        cp.leftMargin = PcViews.dp(c, 8);
        tr.addView(cancel, cp);
        root.addView(tr, PcViews.top(PcViews.matchWrap(), c, 10));

        countdown = PcViews.monoText(c, "", 12f, PcViews.RED);
        countdown.setGravity(Gravity.CENTER);
        countdown.setVisibility(android.view.View.GONE);
        root.addView(countdown, PcViews.top(PcViews.matchWrap(), c, 8));
    }

    private PcViews.Btn action(String key, final String action, boolean danger) {
        PcViews.Btn b = new PcViews.Btn(c, null, a.t(key));
        if (danger) b.setStyle(PcViews.B_DANGER);
        // QA P-1 / U-20: one stray tap used to put the PC to sleep / turn it off. [Cancel] [Action].
        b.setOnClickListener(v -> a.confirm(a.t(key), a.t("confirm_power_" + action),
                new String[]{a.t("btn_cancel"), a.t(key)},
                new int[]{PcViews.B_SEC, danger ? PcViews.B_DANGER : PcViews.B_RED},
                i -> {
                    if (i == 1) send(action);
                }));
        return b;
    }

    /** web send(action): POST /action. */
    private void send(String action) {
        a.status(a.t("msg_sending"));
        a.api("POST", "/action", PcJson.map("action", action), 10000, r -> {
            if (r.error != null) a.status(a.t(r.timedOut() ? "msg_timeout" : "msg_server_err"));
            else if (!r.unauthorized()) {
                a.status(r.message());
                if (!r.message().isEmpty()) a.toast(r.message()); // QA U-4: visible where the user looks
            }
        });
    }

    void checkTimerStatus() {
        a.api("GET", "/shutdown_timer/status", null, 6000, r -> {
            if (!r.ok()) return;
            PcJson.O d = r.json();
            if (d.bool("active", false)) startCountdown(d.lng("remaining", 0));
        });
    }

    private void startTimer() {
        int m;
        try {
            m = Integer.parseInt(minutes.getText().toString().trim());
        } catch (NumberFormatException e) {
            m = 0;
        }
        if (m <= 0) {
            // QA U-21: an empty field used to come back as a server error (in Russian)
            a.toast(a.t("timer_enter_minutes"));
            a.showKeyboard(minutes);
            return;
        }
        final int mins = m;
        a.api("POST", "/shutdown_timer", PcJson.map("minutes", mins), 6000, r -> {
            if (r.error != null) {
                a.status(a.t("msg_server_err"));
                return;
            }
            a.status(r.message());
            if (r.ok() && mins > 0) startCountdown(mins * 60L);
        });
        a.hideKeyboard(minutes);
    }

    private void cancelTimer() {
        a.api("POST", "/shutdown_timer/cancel", null, 6000, r -> {
            if (r.error != null) return;
            a.status(r.message());
            countdownEnd = 0;
            a.ui.removeCallbacks(countdownTick);
            countdown.setText("");
            countdown.setVisibility(android.view.View.GONE);
        });
    }

    private void startCountdown(long seconds) {
        a.ui.removeCallbacks(countdownTick);
        countdownEnd = android.os.SystemClock.elapsedRealtime() + seconds * 1000L;
        countdownTick.run();
    }

    void dispose() {
        a.ui.removeCallbacks(countdownTick);
    }
}
