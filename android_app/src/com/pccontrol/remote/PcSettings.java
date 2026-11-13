package com.pccontrol.remote;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Settings modal (index.html #settingsModalBackdrop + i18n.js): tabs Language / Server / About.
 * Server tab = routing mode (auto / home LAN / Tailscale / custom), saved addresses, MAC, password,
 * token rotation, WOL relay, connection test, logout, stop server.
 */
final class PcSettings {
    private final MainActivity a;
    private final Context c;
    PcModal modal;
    private TextView[] tabs;
    private LinearLayout paneLang, paneServer, paneAbout;
    private int tab;

    // server tab
    private LinearLayout optAuto, optLan, optVpn, optCustom;
    private TextView urlAuto, urlLan, urlVpn, urlCustom, badgeAuto, badgeLan, badgeVpn, badgeCustom, testBox;
    private boolean revAuto, revLan, revVpn, revCustom;
    private EditText fLan, fVpn, fCustom, fMac, fToken, fRelay;

    private static final String MASK = "••••••••••••";

    PcSettings(MainActivity act) {
        a = act;
        c = act;
    }

    private int dp(float v) {
        return PcViews.dp(c, v);
    }

    private String t(String k, Object... v) {
        return a.t(k, v);
    }

    boolean isOpen() {
        return modal != null && modal.isShowing();
    }

    void open(int tabIndex) {
        if (isOpen()) {
            selectTab(tabIndex);
            return;
        }
        revAuto = revLan = revVpn = revCustom = false;
        modal = new PcModal(c, PcModal.KIND_SETTINGS, 420);
        modal.onBackRequest = this::requestClose;
        LinearLayout ct = modal.content;
        ct.addView(PcModal.header(c, PcAppIcons.GEAR, t("settings_title"), null, this::requestClose));
        LinearLayout tabsHolder = PcViews.col(c);
        tabs = PcModal.tabs(c, tabsHolder, new String[]{t("tab_settings_lang"), t("tab_settings_server"), t("tab_settings_about")}, null, 12f, 8);
        LinearLayout.LayoutParams thp = PcViews.matchWrap();
        thp.bottomMargin = dp(14);
        ct.addView(tabsHolder, thp);
        for (int i = 0; i < 3; i++) {
            final int idx = i;
            tabs[i].setOnClickListener(v -> selectTab(idx));
        }
        paneLang = buildLang();
        paneServer = buildServer();
        paneAbout = buildAbout();
        ct.addView(paneLang, PcViews.matchWrap());
        ct.addView(paneServer, PcViews.matchWrap());
        ct.addView(paneAbout, PcViews.matchWrap());
        tab = -1;
        selectTab(tabIndex);
        modal.show(a.root);
        a.registerModal(modal);
    }

    void close() {
        cancelDownload();
        if (modal != null) {
            a.hideKeyboard(modal);
            modal.dismiss();
        }
    }

    private void selectTab(int i) {
        if (tab == i) return;
        tab = i;
        PcModal.selectTab(c, tabs, i);
        paneLang.setVisibility(i == 0 ? View.VISIBLE : View.GONE);
        paneServer.setVisibility(i == 1 ? View.VISIBLE : View.GONE);
        paneAbout.setVisibility(i == 2 ? View.VISIBLE : View.GONE);
        PcViews.fadeIn(i == 0 ? paneLang : i == 1 ? paneServer : paneAbout);
        if (i == 1) renderConn();
        if (i == 2 && apkInfo == null && !checking) checkUpdate(true);
    }

    private TextView sub(String s) {
        TextView t = PcViews.text(c, s, 12f, PcViews.SUBTEXT, 400);
        LinearLayout.LayoutParams p = PcViews.matchWrap();
        p.bottomMargin = dp(12);
        t.setLayoutParams(p);
        return t;
    }

    // ------------------------------------------------------------------ language
    private LinearLayout buildLang() {
        LinearLayout p = PcViews.col(c);
        p.addView(sub(t("lang_select_heading")));
        String[][] langs = {{"uk", "UA", "lang_ua_name", "lang_ua_sub"}, {"ru", "RU", "lang_ru_name", "lang_ru_sub"},
                {"en", "EN", "lang_en_name", "lang_en_sub"}};
        for (int i = 0; i < langs.length; i++) {
            final String code = langs[i][0];
            boolean on = code.equals(a.i18n.lang());
            LinearLayout card = PcViews.row(c);
            card.setPadding(dp(14), dp(12), dp(14), dp(12));
            card.setBackground(on ? PcViews.rect(c, 0x1FFF0033, 14, PcViews.RED, 1) : PcViews.rect(c, PcViews.SURFACE2, 14, PcViews.BORDER, 1));
            TextView flag = PcViews.text(c, langs[i][1], 11f, PcViews.TEXT, 700);
            flag.setBackground(PcViews.rect(c, PcViews.SURFACE2, 6, PcViews.BORDER, 1));
            flag.setPadding(dp(6), dp(3), dp(6), dp(3));
            card.addView(flag);
            LinearLayout names = PcViews.col(c);
            names.addView(PcViews.text(c, t(langs[i][2]), 14f, PcViews.TEXT, 600));
            TextView st = PcViews.text(c, t(langs[i][3]), 11f, PcViews.SUBTEXT, 400);
            st.setPadding(0, dp(2), 0, 0);
            names.addView(st);
            LinearLayout.LayoutParams np = PcViews.weight(1);
            np.leftMargin = dp(12);
            card.addView(names, np);
            card.addView(PcViews.text(c, on ? "✓" : "", 16f, PcViews.RED, 700));
            card.setClickable(true);
            PcViews.pressable(card, 0.98f);
            card.setOnClickListener(v -> a.setAppLanguage(code));
            LinearLayout.LayoutParams cp = PcViews.matchWrap();
            if (i > 0) cp.topMargin = dp(8);
            p.addView(card, cp);
        }
        return p;
    }

    // ------------------------------------------------------------------ server
    private LinearLayout buildServer() {
        LinearLayout p = PcViews.col(c);
        p.addView(sub(t("server_heading")));
        LinearLayout list = PcViews.col(c);
        optAuto = connOpt(list, t("server_mode_auto"), PcConn.MODE_AUTO, false);
        urlAuto = (TextView) optAuto.getTag(R_URL);
        badgeAuto = (TextView) optAuto.getTag(R_BADGE);
        optLan = connOpt(list, t("server_mode_lan"), PcConn.MODE_LAN, true);
        urlLan = (TextView) optLan.getTag(R_URL);
        badgeLan = (TextView) optLan.getTag(R_BADGE);
        optVpn = connOpt(list, t("server_mode_vpn"), PcConn.MODE_VPN, true);
        urlVpn = (TextView) optVpn.getTag(R_URL);
        badgeVpn = (TextView) optVpn.getTag(R_BADGE);
        optCustom = connOpt(list, t("server_mode_custom"), PcConn.MODE_CUSTOM, true);
        urlCustom = (TextView) optCustom.getTag(R_URL);
        badgeCustom = (TextView) optCustom.getTag(R_BADGE);
        LinearLayout.LayoutParams lp = PcViews.matchWrap();
        lp.bottomMargin = dp(10);
        p.addView(list, lp);
        // USB cable (adb reverse / USB tethering): how-to + shortcuts to the system settings
        PcViews.Btn usb = sec("🔌 " + t("usb_help_btn"));
        usb.setOnClickListener(v -> a.showUsbHelp());
        LinearLayout.LayoutParams ulp = PcViews.matchWrap();
        ulp.bottomMargin = dp(14);
        p.addView(usb, ulp);

        fLan = secretField(p, t("server_lan_lbl"), t("server_lan_placeholder"), a.conn.savedRaw(PcConn.K_LAN).isEmpty() ? a.conn.lanHost() : a.conn.savedRaw(PcConn.K_LAN));
        fVpn = secretField(p, t("server_vpn_lbl"), t("server_vpn_placeholder"), a.conn.vpnHost());
        fCustom = secretField(p, t("server_custom_lbl"), t("server_custom_placeholder"), a.conn.customHost());
        fMac = secretField(p, t("server_mac_lbl"), t("server_mac_placeholder"), a.conn.mac());
        fToken = secretField(p, t("server_token_lbl"), t("server_token_placeholder"), a.conn.token());

        PcViews.Btn rotate = sec(t("btn_rotate_token"));
        rotate.size(12f);
        rotate.setOnClickListener(v -> rotateToken());
        LinearLayout.LayoutParams rp = PcViews.matchWrap();
        rp.topMargin = dp(6);
        rp.bottomMargin = dp(12);
        p.addView(rotate, rp);

        fRelay = secretField(p, t("server_relay_lbl"), t("server_relay_placeholder"), a.conn.relay());
        fieldsSnapshot = fieldsNow();

        testBox = PcViews.monoText(c, "", 12f, PcViews.SUBTEXT);
        testBox.setPadding(dp(12), dp(10), dp(12), dp(10));
        testBox.setVisibility(View.GONE);
        p.addView(testBox, PcViews.top(PcViews.matchWrap(), c, 10));

        PcViews.Grid g = new PcViews.Grid(c, 2, 0, 8);
        PcViews.Btn test = sec(t("btn_server_test"));
        test.setOnClickListener(v -> testConnection());
        PcViews.Btn save = new PcViews.Btn(c, null, t("btn_server_save"));
        save.setStyle(PcViews.B_RED);
        save.pad(12, 10).size(12.5f);
        save.setOnClickListener(v -> save());
        g.addView(test);
        g.addView(save);
        p.addView(g, PcViews.top(PcViews.matchWrap(), c, 12));
        PcViews.Btn logout = sec(t("btn_logout"));
        logout.setOnClickListener(v -> a.confirmLogout());
        p.addView(logout, PcViews.top(PcViews.matchWrap(), c, 8));

        LinearLayout stopBox = PcViews.col(c);
        stopBox.addView(PcViews.hr(c));
        TextView sl = PcViews.text(c, t("server_stop_heading"), 11.5f, 0xFFFF5555, 600);
        sl.setPadding(0, dp(16), 0, dp(5));
        stopBox.addView(sl);
        PcViews.Btn stop = new PcViews.Btn(c, null, t("btn_server_stop"));
        stop.setStyle(PcViews.B_DANGER);
        stop.pad(10, 10);
        stop.label.setTypeface(PcViews.face(600));
        stop.label.setSingleLine(false);
        stop.setOnClickListener(v -> stopServer());
        stopBox.addView(stop, PcViews.top(PcViews.matchWrap(), c, 4));
        TextView tip = PcViews.text(c, t("server_stop_tip"), 11f, PcViews.MUTED, 400);
        tip.setLineSpacing(0, 1.4f);
        stopBox.addView(tip, PcViews.top(PcViews.matchWrap(), c, 6));
        p.addView(stopBox, PcViews.top(PcViews.matchWrap(), c, 20));
        return p;
    }

    private static final int R_URL = 0x7f0a0001, R_BADGE = 0x7f0a0002;

    private LinearLayout connOpt(LinearLayout parent, String name, final String mode, boolean copy) {
        final LinearLayout o = PcViews.row(c);
        o.setPadding(dp(13), dp(11), dp(13), dp(11));
        LinearLayout meta = PcViews.col(c);
        meta.addView(PcViews.text(c, name, 13f, PcViews.TEXT, 600));
        TextView url = PcViews.single(PcViews.monoText(c, MASK, 11f, PcViews.SUBTEXT));
        url.setPadding(0, dp(2), 0, 0);
        meta.addView(url);
        o.addView(meta, PcViews.weight(1));
        final PcViews.SecBtn eye = new PcViews.SecBtn(c, true, true);
        eye.setOnClickListener(v -> {
            boolean nv;
            switch (mode) {
                case PcConn.MODE_AUTO: nv = revAuto = !revAuto; break;
                case PcConn.MODE_LAN: nv = revLan = !revLan; break;
                case PcConn.MODE_VPN: nv = revVpn = !revVpn; break;
                default: nv = revCustom = !revCustom; break;
            }
            eye.setOn(nv, true);
            View u = (View) o.getTag(R_URL);
            u.animate().alpha(0.3f).setDuration(80).withEndAction(() -> {
                renderConn();
                u.animate().alpha(1f).setDuration(90).start();
            }).start();
        });
        LinearLayout.LayoutParams ep = PcViews.lp(dp(28), dp(28));
        ep.leftMargin = dp(6);
        o.addView(eye, ep);
        if (copy) {
            final PcViews.SecBtn cp = new PcViews.SecBtn(c, false, true);
            cp.setOnClickListener(v -> {
                String val = PcConn.MODE_LAN.equals(mode) ? a.conn.lanHost() : PcConn.MODE_VPN.equals(mode) ? a.conn.vpnHost()
                        : (a.conn.customHost().isEmpty() ? a.conn.lanHost() : a.conn.customHost());
                if (!val.isEmpty()) {
                    a.copyText(val);
                    cp.flashCopied();
                }
            });
            LinearLayout.LayoutParams cpp = PcViews.lp(dp(28), dp(28));
            cpp.leftMargin = dp(6);
            o.addView(cp, cpp);
        }
        TextView badge = PcViews.text(c, "", 13f, PcViews.TEXT, 700);
        badge.setMinWidth(dp(12));
        badge.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams bp = PcViews.wrap();
        bp.leftMargin = dp(6);
        o.addView(badge, bp);
        o.setTag(R_URL, url);
        o.setTag(R_BADGE, badge);
        o.setClickable(true);
        PcViews.pressable(o, 0.98f);
        o.setOnClickListener(v -> {
            // QA U-39 / P-8: the mode used to apply at once while typed addresses waited for «Сохранить»
            // (lost on close; the app silently went through Tailscale) — apply them together.
            if (fieldsDirty()) applyFields();
            a.conn.setMode(mode);
            renderConn();
            a.reconnect(true);
        });
        LinearLayout.LayoutParams lp = PcViews.matchWrap();
        if (parent.getChildCount() > 0) lp.topMargin = dp(7);
        parent.addView(o, lp);
        return o;
    }

    private EditText secretField(LinearLayout parent, String label, String hint, String value) {
        parent.addView(PcModal.label(c, label));
        LinearLayout wrap = PcViews.row(c);
        final EditText f = PcViews.field(c, hint, true, 13f);
        f.setText(value);
        PcViews.setMasked(f, true);
        wrap.addView(f, PcViews.weight(1));
        final PcViews.SecBtn eye = new PcViews.SecBtn(c, true, false);
        eye.setOnClickListener(v -> {
            boolean on = !eye.isOn();
            eye.setOn(on, true);
            PcViews.setMasked(f, !on);
        });
        LinearLayout.LayoutParams ep = PcViews.lp(dp(36), dp(36));
        ep.leftMargin = dp(6);
        wrap.addView(eye, ep);
        final PcViews.SecBtn cp = new PcViews.SecBtn(c, false, false);
        cp.setOnClickListener(v -> {
            String s = f.getText().toString().trim();
            if (!s.isEmpty()) {
                a.copyText(s);
                cp.flashCopied();
            }
        });
        LinearLayout.LayoutParams cpp = PcViews.lp(dp(36), dp(36));
        cpp.leftMargin = dp(6);
        wrap.addView(cp, cpp);
        LinearLayout.LayoutParams wp = PcViews.matchWrap();
        wp.bottomMargin = dp(10);
        parent.addView(wrap, wp);
        if (label.equals(t("server_lan_lbl"))) {
            f.addTextChangedListener(new android.text.TextWatcher() {
                @Override public void beforeTextChanged(CharSequence s, int st, int co, int af) {}
                @Override public void onTextChanged(CharSequence s, int st, int be, int co) {}
                @Override public void afterTextChanged(android.text.Editable s) { renderConn(); }
            });
        }
        return f;
    }

    private PcViews.Btn sec(String s) {
        PcViews.Btn b = new PcViews.Btn(c, null, s);
        b.setStyle(PcViews.B_SEC);
        b.pad(12, 10).size(12.5f);
        return b;
    }

    /** web renderConnModal(). */
    void renderConn() {
        if (optAuto == null) return;
        String mode = a.conn.mode();
        String lanTyped = fLan != null ? PcConn.normalizeHostUrl(fLan.getText().toString()) : "";
        String lan = lanTyped.isEmpty() ? a.conn.lanHost() : lanTyped;
        String vpn = a.conn.vpnHost();
        urlLan.setText(revLan ? (lan.isEmpty() ? "—" : lan) : MASK);
        urlVpn.setText(revVpn ? (vpn.isEmpty() ? "—" : vpn) : MASK);
        urlCustom.setText(revCustom ? (a.conn.customHost().isEmpty() ? "—" : a.conn.customHost()) : MASK);
        String dl = (revAuto || revLan) ? PcConn.hostOnly(lan) : MASK;
        String dv = (revAuto || revVpn) ? PcConn.hostOnly(vpn) : MASK;
        urlAuto.setText(t("server_mode_auto_sub", "lan", dl, "vpn", dv));
        styleOpt(optAuto, badgeAuto, PcConn.MODE_AUTO.equals(mode));
        styleOpt(optLan, badgeLan, PcConn.MODE_LAN.equals(mode));
        styleOpt(optVpn, badgeVpn, PcConn.MODE_VPN.equals(mode));
        styleOpt(optCustom, badgeCustom, PcConn.MODE_CUSTOM.equals(mode));
    }

    private void styleOpt(LinearLayout o, TextView badge, boolean on) {
        o.setBackground(on ? PcViews.rect(c, 0x1FFF0033, 12, PcViews.RED, 1) : PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        badge.setText(on ? "✓" : "");
    }

    private void showTest(int kind, String text) {
        testBox.setVisibility(View.VISIBLE);
        int bg, br, fg;
        if (kind == 0) { bg = 0x0FFFFFFF; br = PcViews.BORDER; fg = PcViews.SUBTEXT; }
        else if (kind == 1) { bg = 0x2622C55E; br = 0x6622C55E; fg = PcViews.GREEN_TEXT; }
        else { bg = 0x26EF4444; br = 0x66EF4444; fg = 0xFFFCA5A5; }
        testBox.setBackground(PcViews.rect(c, bg, 12, br, 1));
        testBox.setTextColor(fg);
        testBox.setText(text);
    }

    /** web testServerConnection(). */
    private void testConnection() {
        showTest(0, t("server_test_testing"));
        String mode = a.conn.mode();
        String lanIn = fLan.getText().toString().trim(), customIn = fCustom.getText().toString().trim();
        final String tok = fToken.getText().toString().trim().isEmpty() ? a.conn.token() : fToken.getText().toString().trim();
        String base;
        if (PcConn.MODE_LAN.equals(mode)) base = !lanIn.isEmpty() ? PcConn.normalizeHostUrl(lanIn) : a.conn.lanHost();
        else if (PcConn.MODE_CUSTOM.equals(mode)) base = !customIn.isEmpty() ? PcConn.normalizeHostUrl(customIn) : a.conn.customHost();
        else if (PcConn.MODE_VPN.equals(mode)) base = a.conn.vpnHost();
        else base = !lanIn.isEmpty() ? PcConn.normalizeHostUrl(lanIn) : a.conn.apiBase();
        final String target = base;
        a.bg(() -> {
            final PcHttp.Resp r = PcHttp.request(target, "GET", "/status", tok, null, 3500, 3500, null);
            a.ui(() -> {
                if (!isOpen()) return;
                if (r.ok()) {
                    showTest(1, t("server_test_success") + r.millis + " ms (" + r.json().str("hostname", "PC") + ")");
                } else {
                    String why = r.error != null ? (r.timedOut() ? "timeout" : String.valueOf(r.error.getMessage())) : ("HTTP " + r.code);
                    showTest(2, t("server_test_fail") + " (" + why + ")");
                }
            });
        });
    }

    /** web saveCustomConn(). */
    private void save() {
        applyFields();
        renderConn();
        showTest(1, t("btn_server_save"));
        close();
        a.reconnect(true);
    }

    /** Field texts when the server tab was built (QA U-39: unsaved-changes check). */
    private String fieldsSnapshot = "";

    private String fieldsNow() {
        if (fLan == null) return "";
        return fLan.getText() + "\u0001" + fVpn.getText() + "\u0001" + fCustom.getText() + "\u0001" + fMac.getText()
                + "\u0001" + fToken.getText() + "\u0001" + fRelay.getText();
    }

    private boolean fieldsDirty() {
        return fLan != null && !fieldsNow().equals(fieldsSnapshot);
    }

    /** QA U-39 / P-8: closing with typed but unsaved addresses asks [Не сохранять] [Сохранить]. */
    private void requestClose() {
        if (!fieldsDirty()) {
            close();
            return;
        }
        a.confirm(t("conn_unsaved_title"), t("conn_unsaved_desc"), new String[]{t("btn_discard"), t("btn_server_save")},
                new int[]{PcViews.B_SEC, PcViews.B_RED}, choice -> {
                    if (choice == 1) save();
                    else if (choice == 0) close();
                });
    }

    /** Saves the typed addresses / password / MAC / relay (without closing). */
    private void applyFields() {
        a.conn.putOrRemove(PcConn.K_LAN, PcConn.normalizeHostUrl(fLan.getText().toString()));
        a.conn.putOrRemove(PcConn.K_VPN, PcConn.normalizeHostUrl(fVpn.getText().toString()));
        a.conn.putOrRemove(PcConn.K_CUSTOM, PcConn.normalizeHostUrl(fCustom.getText().toString()));
        // addresses saved here by the user are trusted (a deep link without credentials is not)
        a.conn.markTrusted(PcConn.normalizeHostUrl(fLan.getText().toString()));
        a.conn.markTrusted(PcConn.normalizeHostUrl(fVpn.getText().toString()));
        a.conn.markTrusted(PcConn.normalizeHostUrl(fCustom.getText().toString()));
        a.conn.putOrRemove(PcConn.K_MAC, fMac.getText().toString().trim());
        String tok = fToken.getText().toString().trim();
        if (!tok.isEmpty()) a.conn.setToken(tok, true);
        a.conn.putOrRemove(PcConn.K_RELAY, PcConn.stripSlash(fRelay.getText().toString()));
        fieldsSnapshot = fieldsNow();
    }

    private void rotateToken() {
        a.confirm(t("btn_rotate_token"), t("confirm_rotate_token"), new String[]{t("btn_cancel"), t("btn_continue")},
                new int[]{PcViews.B_SEC, PcViews.B_RED}, choice -> {
                    if (choice != 1) return;
                    a.api("POST", "/api/auth/rotate", null, 8000, r -> {
                        PcJson.O d = r.json();
                        if (r.ok() && d.bool("ok", false) && !d.str("token").isEmpty()) {
                            a.conn.setToken(d.str("token"), true);
                            if (fToken != null) fToken.setText(d.str("token"));
                            a.toast(t("token_rotated"));
                            a.refreshAll();
                        } else if (r.error == null) {
                            a.toast(d.str("message", "Error"));
                        }
                    });
                });
    }

    private void stopServer() {
        a.confirm(t("server_stop_title"), t("server_stop_desc"), new String[]{t("preset_btn_cancel"), t("btn_server_stop")},
                new int[]{PcViews.B_SEC, PcViews.B_DANGER}, choice -> {
                    if (choice != 1) return;
                    a.api("POST", "/api/server/stop", null, 8000, r -> {
                        close();
                        a.alert(r.ok() ? (r.message().isEmpty() ? t("msg_server_stopped") : r.message()) : t("msg_server_stopping"), null);
                    });
                });
    }

    // ------------------------------------------------------------------ about
    private LinearLayout buildAbout() {
        LinearLayout p = PcViews.col(c);
        LinearLayout hero = PcViews.row(c);
        hero.setPadding(0, 0, 0, dp(8));
        FrameLayout logo = new FrameLayout(c);
        logo.setBackground(PcViews.rect(c, 0xFF000000, 14, 0x66FF0000, 1));
        logo.setPadding(dp(4), dp(4), dp(4), dp(4));
        logo.setClipToOutline(true);
        logo.setElevation(dp(6));
        if (Build26.SDK >= 28) logo.setOutlineSpotShadowColor(0xFFFF0000);
        ImageView li = new ImageView(c);
        li.setImageResource(R.drawable.pc_logo);
        li.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.addView(li, new FrameLayout.LayoutParams(dp(40), dp(40), Gravity.CENTER));
        hero.addView(logo, PcViews.lp(dp(48), dp(48)));
        LinearLayout ht = PcViews.col(c);
        ht.addView(PcViews.text(c, "PC Control", 18f, PcViews.TEXT, 800));
        TextView ver = PcViews.monoText(c, t("about_version_lbl") + " " + a.versionName() + " · Build " + a.versionCode(), 11.5f, PcViews.SUBTEXT);
        ver.setPadding(0, dp(2), 0, 0);
        ht.addView(ver);
        LinearLayout.LayoutParams hp = PcViews.weight(1);
        hp.leftMargin = dp(12);
        hero.addView(ht, hp);
        p.addView(hero, PcViews.matchWrap());
        p.addView(buildUpdate(), PcViews.top(PcViews.matchWrap(), c, 4));
        p.addView(PcViews.hr(c), PcViews.top(PcViews.matchWrap(), c, 14));
        TextView desc = PcViews.text(c, t("about_desc"), 12f, PcViews.SUBTEXT, 400);
        desc.setLineSpacing(0, 1.45f);
        p.addView(desc, PcViews.top(PcViews.matchWrap(), c, 12));
        LinearLayout info = PcViews.col(c);
        info.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        info.setPadding(dp(12), dp(10), dp(12), dp(10));
        info.addView(infoRow(t("about_dev_lbl"), t("about_dev_val")));
        View r2 = infoRow(t("about_platform_lbl"), t("about_platform_val"));
        ((LinearLayout.LayoutParams) r2.getLayoutParams()).topMargin = dp(6);
        info.addView(r2);
        p.addView(info, PcViews.top(PcViews.matchWrap(), c, 12));
        LinearLayout notes = PcViews.col(c);
        GradientDrawable nb = PcViews.rect(c, 0x08FFFFFF, 12, 0, 0);
        nb.setStroke(Math.max(1, dp(1)), PcViews.BORDER_STRONG, dp(4), dp(3));
        notes.setBackground(nb);
        notes.setPadding(dp(12), dp(10), dp(12), dp(10));
        notes.addView(PcViews.text(c, t("about_notes_lbl"), 11.5f, PcViews.TEXT, 600));
        TextView nt = PcViews.text(c, t("about_notes_val"), 11.5f, PcViews.SUBTEXT, 400);
        nt.setLineSpacing(0, 1.4f);
        notes.addView(nt, PcViews.top(PcViews.matchWrap(), c, 4));
        p.addView(notes, PcViews.top(PcViews.matchWrap(), c, 12));
        return p;
    }

    private View infoRow(String k, String v) {
        LinearLayout r = PcViews.row(c);
        r.addView(PcViews.text(c, k, 12f, PcViews.MUTED, 400), PcViews.weight(1));
        r.addView(PcViews.text(c, v, 12f, PcViews.TEXT, 500));
        r.setLayoutParams(PcViews.matchWrap());
        return r;
    }

    // ------------------------------------------------------------------ app update (about tab)
    // Состояние живёт в PcSettings (не в окне): переживает пересборку окна при смене языка;
    // поворот экрана обрабатывается без пересоздания активности (configChanges в манифесте).
    private PcJson.O apkInfo;
    private int upd = -1;
    private boolean checking, downloading, installing, awaitingPermission, autoChecked;
    private long dlDone, dlTotal;
    private java.util.concurrent.atomic.AtomicBoolean dlCancel;
    private TextView updPc, updStatus, updProgText;
    private LinearLayout updProg;
    private View updFill;
    private FrameLayout updTrack;
    private PcViews.Btn updBtn;

    private java.io.File apkFile() {
        java.io.File dir = new java.io.File(a.getCacheDir(), "update");
        if (!dir.isDirectory()) dir.mkdirs();
        return new java.io.File(dir, "PC_Control.apk");
    }

    private LinearLayout buildUpdate() {
        LinearLayout box = PcViews.col(c);
        box.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        box.setPadding(dp(12), dp(10), dp(12), dp(12));
        box.addView(PcViews.text(c, t("apk_upd_title"), 11.5f, PcViews.TEXT, 600));
        View inst = infoRow(t("apk_upd_installed_lbl"), PcUpdate.label(a.versionName(), a.versionCode()));
        ((LinearLayout.LayoutParams) inst.getLayoutParams()).topMargin = dp(8);
        box.addView(inst);
        LinearLayout pcRow = PcViews.row(c);
        pcRow.addView(PcViews.text(c, t("apk_upd_pc_lbl"), 12f, PcViews.MUTED, 400), PcViews.weight(1));
        updPc = PcViews.text(c, "—", 12f, PcViews.TEXT, 500);
        pcRow.addView(updPc);
        box.addView(pcRow, PcViews.top(PcViews.matchWrap(), c, 6));
        updStatus = PcViews.text(c, "", 11.5f, PcViews.SUBTEXT, 400);
        updStatus.setLineSpacing(0, 1.35f);
        box.addView(updStatus, PcViews.top(PcViews.matchWrap(), c, 8));

        // полоса загрузки — как дорожка ползунков (PcViews.Slider): 4dp, rgba(255,255,255,.16), заливка красным
        updProg = PcViews.col(c);
        updTrack = new FrameLayout(c);
        updTrack.setBackground(PcViews.rect(c, 0x29FFFFFF, 2, 0, 0));
        updFill = new View(c);
        updFill.setBackground(PcViews.rect(c, PcViews.RED, 2, 0, 0));
        updTrack.addView(updFill, new FrameLayout.LayoutParams(0, FrameLayout.LayoutParams.MATCH_PARENT));
        updProg.addView(updTrack, PcViews.lp(FrameLayout.LayoutParams.MATCH_PARENT, dp(4)));
        updProgText = PcViews.monoText(c, "", 11f, PcViews.SUBTEXT);
        updProg.addView(updProgText, PcViews.top(PcViews.matchWrap(), c, 6));
        box.addView(updProg, PcViews.top(PcViews.matchWrap(), c, 10));
        updTrack.addOnLayoutChangeListener((v, l, tp, r, b, ol, ot, or, ob) -> {
            if (r - l != or - ol) v.post(this::renderProgress);
        });

        updBtn = sec(t("apk_upd_btn_check"));
        updBtn.label.setSingleLine(false);
        updBtn.label.setMaxLines(2);
        updBtn.setOnClickListener(v -> onUpdateButton());
        box.addView(updBtn, PcViews.top(PcViews.matchWrap(), c, 10));
        renderUpdate();
        return box;
    }

    private void renderUpdate() {
        if (updBtn == null) return;
        String pcName = apkInfo == null ? "" : apkInfo.str("version_name");
        if (checking && apkInfo == null) updPc.setText(t("apk_upd_checking"));
        else if (apkInfo == null) updPc.setText("—");
        else if (upd == PcUpdate.NO_APK) updPc.setText(t("apk_upd_no_apk"));
        else updPc.setText(PcUpdate.label(pcName, apkInfo.lng("version_code", 0)));

        String st = "";
        int stColor = PcViews.SUBTEXT;
        if (installing) st = t("apk_upd_installing");
        else if (downloading) st = t("apk_upd_downloading") + "…";
        else if (upd == PcUpdate.UP_TO_DATE) { st = "✓ " + t("apk_upd_latest"); stColor = PcViews.GREEN_TEXT; }
        else if (upd == PcUpdate.NEWER) { st = t("apk_upd_available", "ver", pcName); stColor = PcViews.TEXT; }
        else if (upd == PcUpdate.OLDER_ON_PC) st = t("apk_upd_pc_older");
        updStatus.setText(st);
        updStatus.setTextColor(stColor);
        updStatus.setVisibility(st.isEmpty() ? View.GONE : View.VISIBLE);

        updProg.setVisibility(downloading ? View.VISIBLE : View.GONE);
        renderProgress();

        boolean busy = checking || installing;
        if (downloading) {
            updBtn.setStyle(PcViews.B_SEC);
            updBtn.setText(t("btn_cancel"));
        } else if (upd == PcUpdate.NEWER) {
            updBtn.setStyle(PcViews.B_RED);
            updBtn.setText(t("apk_upd_btn_update", "ver", pcName));
        } else {
            updBtn.setStyle(PcViews.B_SEC);
            updBtn.setText(checking ? t("apk_upd_checking") : t("apk_upd_btn_check"));
        }
        updBtn.setEnabled(!busy);
        updBtn.setAlpha(busy ? 0.55f : 1f);
    }

    private void renderProgress() {
        if (updTrack == null || !downloading) return;
        int pct = PcUpdate.percent(dlDone, dlTotal);
        int w = updTrack.getWidth();
        FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) updFill.getLayoutParams();
        int nw = pct < 0 ? 0 : w * pct / 100;
        if (lp.width != nw) {
            lp.width = nw;
            updFill.setLayoutParams(lp);
        }
        updProgText.setText((pct < 0 ? "" : pct + "% · ") + PcUpdate.sizeText(dlDone, dlTotal));
    }

    private void onUpdateButton() {
        if (downloading) {
            cancelDownload();
            return;
        }
        if (checking || installing) return;
        if (upd == PcUpdate.NEWER && apkInfo != null) startUpdate();
        else checkUpdate(false);
    }

    /** Одна тихая проверка после подключения (точка у входа в настройки). */
    void checkUpdateOnConnect() {
        if (autoChecked) return;
        autoChecked = true;
        checkUpdate(true);
    }

    private void checkUpdate(final boolean quiet) {
        if (checking) return;
        checking = true;
        renderUpdate();
        a.api("GET", "/api/apk/info", null, 8000, r -> {
            checking = false;
            if (r.ok()) {
                apkInfo = r.json();
                upd = PcUpdate.decide(a.versionCode(), apkInfo);
                if (!quiet) {
                    if (upd == PcUpdate.UP_TO_DATE) a.sideToast(t("apk_upd_latest"), false);
                    else if (upd == PcUpdate.OLDER_ON_PC) a.sideToast(t("apk_upd_pc_older"), false);
                    else if (upd == PcUpdate.NO_APK) a.sideToast(t("apk_upd_no_apk"), true);
                }
            } else if (!quiet && !r.unauthorized()) {
                a.sideToast(r.error == null && r.code == 404 ? t("apk_upd_err_server_old") : t("apk_upd_err_check"), true);
            }
            a.setUpdateBadge(upd == PcUpdate.NEWER);
            renderUpdate();
        });
    }

    private void startUpdate() {
        final String sha = apkInfo.str("sha256");
        final long size = apkInfo.lng("size", 0);
        final java.io.File out = apkFile();
        final String base = a.conn.apiBase(), token = a.conn.token();
        final java.util.concurrent.atomic.AtomicBoolean cancel = new java.util.concurrent.atomic.AtomicBoolean();
        dlCancel = cancel;
        downloading = true;
        dlDone = 0;
        dlTotal = size;
        renderUpdate();
        a.bg(() -> {
            // уже скачанный и проверенный файл (например, после выдачи разрешения) — повторно не качаем
            if (out.isFile() && PcUpdate.sha256Matches(sha, PcUpdate.sha256(out))) {
                a.ui(() -> {
                    downloading = false;
                    beginInstall();
                });
                return;
            }
            final PcUpdate.Result res = PcUpdate.download(base, "/download/apk", token, out, size,
                    (d, total) -> a.ui(() -> {
                        if (cancel.get()) return;
                        dlDone = d;
                        dlTotal = total;
                        renderProgress();
                    }), cancel);
            if (res.ok && !PcUpdate.sha256Matches(sha, res.sha256)) out.delete();
            a.ui(() -> {
                if (dlCancel == cancel) dlCancel = null;
                downloading = false;
                if (res.cancelled || cancel.get()) {
                    a.sideToast(t("apk_upd_cancelled"), false);
                } else if (!res.ok) {
                    a.sideToast(t("apk_upd_err_download") + (res.error.isEmpty() ? "" : " (" + res.error + ")"), true);
                } else if (!PcUpdate.sha256Matches(sha, res.sha256)) {
                    a.sideToast(t("apk_upd_err_sha"), true);
                } else {
                    beginInstall();
                }
                renderUpdate();
            });
        });
    }

    /** Отмена загрузки (кнопка «Отмена», закрытие настроек, закрытие приложения). */
    void cancelDownload() {
        java.util.concurrent.atomic.AtomicBoolean cn = dlCancel;
        if (cn != null) cn.set(true);
    }

    private void beginInstall() {
        if (!PcApkInstaller.canInstall(a)) {
            awaitingPermission = true;
            a.sideToast(t("apk_upd_need_perm"), false);
            if (!PcApkInstaller.requestPermission(a)) {
                awaitingPermission = false;
                a.sideToast(t("apk_upd_perm_denied"), true);
            }
            renderUpdate();
            return;
        }
        installing = true;
        renderUpdate();
        final java.io.File f = apkFile();
        a.bg(() -> {
            try {
                PcApkInstaller.install(a, f);
            } catch (Exception e) {
                a.ui(() -> {
                    installing = false;
                    a.sideToast(t("apk_upd_err_install") + " (" + e.getClass().getSimpleName() + ")", true);
                    renderUpdate();
                });
            }
        });
    }

    /** Возврат в приложение: после экрана разрешения продолжаем установку. */
    void onResume() {
        if (!awaitingPermission) return;
        awaitingPermission = false;
        if (PcApkInstaller.canInstall(a)) beginInstall();
        else a.sideToast(t("apk_upd_perm_denied"), true);
        renderUpdate();
    }

    /** Итог сессии PackageInstaller (UI-поток). */
    void onInstallStatus(int status, String message) {
        if (status == android.content.pm.PackageInstaller.STATUS_PENDING_USER_ACTION) {
            a.sideToast(t("apk_upd_confirm"), false);
            return;
        }
        installing = false;
        String key = PcUpdate.statusKey(status);
        if (status == android.content.pm.PackageInstaller.STATUS_SUCCESS) {
            apkFile().delete();
            a.sideToast(t(key), false);
        } else if ("apk_upd_err_conflict".equals(key)) {
            a.alert(t(key), null);
        } else {
            a.sideToast(t(key), status != android.content.pm.PackageInstaller.STATUS_FAILURE_ABORTED);
        }
        renderUpdate();
    }

    /** tiny indirection so the about pane compiles against API 24 while using API 28 shadow colours. */
    private static final class Build26 {
        static final int SDK = android.os.Build.VERSION.SDK_INT;
    }
}
