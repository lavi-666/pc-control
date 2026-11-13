package com.pccontrol.remote;

import android.content.Context;
import android.content.res.ColorStateList;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Login window (index.html #loginModalBackdrop): logo, title, error box, password with
 * show/hide, "remember on this device", sign-in — plus the server address field the native app
 * needs on first start (QR deep links fill it automatically). POST /api/auth/login {password}.
 */
final class PcLogin {
    private final MainActivity a;
    private final Context c;
    PcModal modal;
    private TextView error;
    private EditText server, password;
    private CheckBox remember;
    private PcViews.Btn submit;
    private boolean busy;

    PcLogin(MainActivity act) {
        a = act;
        c = act;
    }

    private int dp(float v) {
        return PcViews.dp(c, v);
    }

    boolean isOpen() {
        return modal != null && modal.isShowing();
    }

    void open(String errorMessage) {
        if (isOpen()) {
            showError(errorMessage);
            return;
        }
        modal = new PcModal(c, PcModal.KIND_SETTINGS, 380);
        modal.dismissOnBackdrop = false;
        modal.onBackRequest = () -> a.moveTaskToBack(true);
        LinearLayout ct = modal.content;
        ct.setPadding(dp(24), dp(28), dp(24), dp(28));
        ct.setGravity(Gravity.CENTER_HORIZONTAL);

        FrameLayout logo = new FrameLayout(c);
        logo.setBackground(PcViews.rect(c, 0xFF000000, 12, 0, 0));
        logo.setClipToOutline(true);
        logo.setElevation(dp(8));
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            logo.setOutlineSpotShadowColor(0xFFFF0033);
            logo.setOutlineAmbientShadowColor(0xFFFF0033);
        }
        ImageView li = new ImageView(c);
        li.setImageResource(R.drawable.pc_logo);
        li.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.addView(li, new FrameLayout.LayoutParams(dp(56), dp(56)));
        LinearLayout.LayoutParams lp = PcViews.lp(dp(56), dp(56));
        lp.bottomMargin = dp(16);
        ct.addView(logo, lp);

        TextView title = PcViews.text(c, a.t("login_title"), 20f, PcViews.TEXT, 700);
        title.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tp = PcViews.wrap();
        tp.bottomMargin = dp(6);
        ct.addView(title, tp);
        TextView sub = PcViews.text(c, a.t("login_subtitle"), 13f, PcViews.MUTED, 400);
        sub.setGravity(Gravity.CENTER);
        sub.setLineSpacing(0, 1.4f);
        LinearLayout.LayoutParams sp = PcViews.matchWrap();
        sp.bottomMargin = dp(20);
        ct.addView(sub, sp);

        error = PcViews.text(c, "", 13f, 0xFFFF5555, 400);
        error.setBackground(PcViews.rect(c, 0x1AFF3333, 8, 0x80FF3333, 1));
        error.setPadding(dp(14), dp(10), dp(14), dp(10));
        error.setVisibility(View.GONE);
        LinearLayout.LayoutParams ep = PcViews.matchWrap();
        ep.bottomMargin = dp(16);
        ct.addView(error, ep);

        // server address (native addition, same .conn-field style)
        TextView sl = PcModal.label(c, a.t("login_server_lbl"));
        sl.setGravity(Gravity.START);
        ct.addView(sl);
        server = PcViews.field(c, a.t("login_server_placeholder"), true, 13f);
        server.setText(a.conn.apiBase());
        server.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        server.setImeOptions(EditorInfo.IME_ACTION_NEXT | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        LinearLayout.LayoutParams svp = PcViews.matchWrap();
        svp.bottomMargin = dp(14);
        ct.addView(server, svp);

        LinearLayout pw = PcViews.row(c);
        password = PcViews.field(c, a.t("login_pwd_placeholder"), true, 15f);
        PcViews.setMasked(password, true);
        password.setImeOptions(EditorInfo.IME_ACTION_GO | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        password.setOnEditorActionListener((v, actionId, ev) -> {
            if (actionId == EditorInfo.IME_ACTION_GO || actionId == EditorInfo.IME_ACTION_DONE) {
                submit();
                return true;
            }
            return false;
        });
        pw.addView(password, PcViews.weight(1));
        final PcViews.SecBtn eye = new PcViews.SecBtn(c, true, false);
        eye.setOnClickListener(v -> {
            boolean on = !eye.isOn();
            eye.setOn(on, true);
            PcViews.setMasked(password, !on);
        });
        LinearLayout.LayoutParams eyp = PcViews.lp(dp(36), dp(36));
        eyp.leftMargin = dp(6);
        pw.addView(eye, eyp);
        LinearLayout.LayoutParams pwp = PcViews.matchWrap();
        pwp.bottomMargin = dp(14);
        ct.addView(pw, pwp);

        remember = new CheckBox(c);
        remember.setChecked(true);
        remember.setText(a.t("login_remember"));
        remember.setTextColor(PcViews.MUTED);
        remember.setTextSize(13f);
        remember.setButtonTintList(ColorStateList.valueOf(PcViews.RED));
        LinearLayout.LayoutParams rp = PcViews.matchWrap();
        rp.bottomMargin = dp(18);
        ct.addView(remember, rp);

        submit = new PcViews.Btn(c, null, a.t("login_btn"));
        submit.setStyle(PcViews.B_RED);
        submit.pad(14, 12).size(15f);
        submit.setOnClickListener(v -> submit());
        ct.addView(submit, PcViews.matchWrap());

        PcViews.Btn conn = new PcViews.Btn(c, PcAppIcons.GEAR, a.t("login_conn_settings"), 15);
        conn.setStyle(PcViews.B_SEC);
        conn.pad(12, 9).size(12.5f);
        conn.setOnClickListener(v -> a.settings.open(1));
        ct.addView(conn, PcViews.top(PcViews.matchWrap(), c, 10));

        showError(errorMessage);
        modal.show(a.root);
        a.registerModal(modal);
        password.postDelayed(() -> {
            if (server.getText().toString().trim().isEmpty()) a.showKeyboard(server);
            else a.showKeyboard(password);
        }, 150);
    }

    private void showError(String msg) {
        if (error == null) return;
        if (msg == null || msg.isEmpty()) {
            error.setVisibility(View.GONE);
        } else {
            error.setText(msg);
            error.setVisibility(View.VISIBLE);
        }
    }

    /** The app found the PC on another route (e.g. USB cable) while the window is open. */
    void suggestServer(String oldBase, String url) {
        if (server == null || url == null || url.isEmpty()) return;
        String cur = server.getText().toString().trim();
        if (cur.isEmpty() || cur.equals(oldBase)) server.setText(url);
    }

    void close() {
        if (modal != null) {
            a.hideKeyboard(modal);
            modal.dismiss();
        }
    }

    /** web submitLoginForm(). */
    private void submit() {
        if (busy) return;
        final String pwd = password.getText().toString().trim();
        String srvRaw = server.getText().toString().trim();
        if (srvRaw.isEmpty()) {
            showError(a.t("msg_no_server"));
            a.showKeyboard(server);
            return;
        }
        if (pwd.isEmpty()) {
            showError(a.t("msg_password_empty")); // QA U-37: was the field's placeholder text
            a.showKeyboard(password);
            return;
        }
        final String base = PcConn.normalizeHostUrl(srvRaw);
        final boolean keep = remember.isChecked();
        busy = true;
        final CharSequence prev = submit.label.getText();
        submit.setText("...");
        submit.setAlpha(0.7f);
        a.bg(() -> {
            final PcHttp.Resp r = PcHttp.request(base, "POST", "/api/auth/login", null, PcJson.map("password", pwd), 4000, 8000, null);
            a.ui(() -> {
                busy = false;
                submit.setText(prev);
                submit.setAlpha(1f);
                if (r.ok() && r.json().bool("ok", false)) {
                    a.onLoggedIn(base, pwd, keep);
                    close();
                    return;
                }
                if (r.error != null) {
                    showError(a.t(r.timedOut() ? "msg_timeout" : "msg_server_unreachable_net"));
                } else {
                    String m = r.message();
                    showError(m.isEmpty() ? a.t("msg_auth_err") : m);
                    password.selectAll();
                    a.showKeyboard(password);
                }
            });
        });
    }
}
