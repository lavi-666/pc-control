package com.pccontrol.remote;

import android.content.Context;
import android.graphics.drawable.ColorDrawable;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Card "Ввод и система" (index.html card 3): Windows input language, screenshot, processes with
 * search / terminate, launch routines button and the routine buttons grid.
 */
final class PcInputCard {
    private final MainActivity a;
    private final Context c;
    final LinearLayout root;

    private PcViews.Btn langBtn, procBtn;
    private TextView langBadge;
    private PopupWindow langMenu;
    private String langCurrent = "";
    private List<PcJson.O> languages = new ArrayList<>();

    private LinearLayout procBox, procList;
    private EditText procSearch;
    private TextView procCount, procClear;
    boolean procOpen;
    private List<PcJson.O> procs = new ArrayList<>();
    private final Map<String, View> procRows = new HashMap<>();
    private PcViews.MaxScroll procScroll;
    private final Runnable procFilter = this::renderProcesses;

    final PcViews.Grid presetsFlow;

    PcInputCard(MainActivity act) {
        a = act;
        c = act;
        root = PcViews.card(c);
        root.addView(PcViews.cardTitle(c, a.t("card_input_system")));

        // language picker: button + badge in the lower-right corner
        FrameLayout picker = new FrameLayout(c);
        langBtn = new PcViews.Btn(c, PcAppIcons.KEYBOARD, a.t("btn_kb_lang")).start();
        langBtn.setPadding(dp(16), dp(13), dp(16), dp(13));
        langBtn.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        langBtn.setOnClickListener(v -> toggleLangMenu());
        picker.addView(langBtn, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        langBadge = PcViews.monoText(c, "—", 10.5f, PcViews.SUBTEXT);
        langBadge.setTypeface(android.graphics.Typeface.create(PcViews.mono(), android.graphics.Typeface.BOLD));
        langBadge.setLetterSpacing(0.05f);
        FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.END | Gravity.BOTTOM);
        bp.rightMargin = dp(9);
        bp.bottomMargin = dp(5);
        picker.addView(langBadge, bp);
        LinearLayout.LayoutParams pp = PcViews.matchWrap();
        pp.bottomMargin = dp(8);
        root.addView(picker, pp);

        PcViews.Grid g = new PcViews.Grid(c, 2, 0, 8);
        PcViews.Btn shot = new PcViews.Btn(c, PcAppIcons.IMAGE, a.t("btn_screenshot"));
        shot.setOnClickListener(v -> a.takeScreenshot());
        procBtn = new PcViews.Btn(c, PcAppIcons.LIST, a.t("btn_processes"));
        procBtn.setOnClickListener(v -> toggleProcesses());
        g.addView(shot);
        g.addView(procBtn);
        root.addView(g, PcViews.matchWrap());

        buildProcesses();

        PcViews.Btn presetsBtn = new PcViews.Btn(c, PcAppIcons.SPARKLE, a.t("btn_presets"));
        presetsBtn.setStyle(PcViews.B_PRESETS);
        presetsBtn.setOnClickListener(v -> a.presets.open());
        root.addView(presetsBtn, PcViews.top(PcViews.matchWrap(), c, 8));

        presetsFlow = new PcViews.Grid(c, 0, 130, 8);
        root.addView(presetsFlow, PcViews.top(PcViews.matchWrap(), c, 8));
    }

    private int dp(float v) {
        return PcViews.dp(c, v);
    }

    // ------------------------------------------------------------------ Windows input language
    void loadLanguages() {
        a.api("GET", "/keyboard/languages", null, 6000, r -> {
            if (!r.ok()) return;
            PcJson.O d = r.json();
            langCurrent = d.str("current");
            languages = d.objs("languages");
            renderBadge();
        });
    }

    private void renderBadge() {
        String abbr = "—";
        for (PcJson.O l : languages) if (l.str("id").equals(langCurrent)) abbr = l.str("abbr");
        langBadge.setText(abbr);
    }

    private void toggleLangMenu() {
        if (langMenu != null && langMenu.isShowing()) {
            langMenu.dismiss();
            return;
        }
        LinearLayout box = PcViews.col(c);
        box.setBackground(PcViews.rect(c, 0xFF1E1E1E, 14, PcViews.BORDER_STRONG, 1));
        box.setPadding(dp(5), dp(5), dp(5), dp(5));
        box.setElevation(dp(14));
        final LinearLayout items = PcViews.col(c);
        PcViews.MaxScroll sc = new PcViews.MaxScroll(c, 250);
        sc.addView(items);
        box.addView(sc, PcViews.matchWrap());
        fillLangItems(items);
        FrameLayout holder = new FrameLayout(c);
        int pad = dp(14);
        holder.setPadding(pad, 0, pad, pad);
        holder.addView(box, new FrameLayout.LayoutParams(langBtn.getWidth(), ViewGroup.LayoutParams.WRAP_CONTENT));
        langMenu = new PopupWindow(holder, langBtn.getWidth() + 2 * pad, ViewGroup.LayoutParams.WRAP_CONTENT, true);
        langMenu.setBackgroundDrawable(new ColorDrawable(0));
        langMenu.setOutsideTouchable(true);
        langMenu.setAnimationStyle(android.R.style.Animation_Dialog);
        langMenu.showAsDropDown(langBtn, -pad, dp(6));
        a.api("GET", "/keyboard/languages", null, 6000, r -> {
            if (!r.ok()) return;
            langCurrent = r.json().str("current");
            languages = r.json().objs("languages");
            renderBadge();
            if (langMenu != null && langMenu.isShowing()) fillLangItems(items);
        });
    }

    private void fillLangItems(LinearLayout items) {
        items.removeAllViews();
        if (languages.isEmpty()) {
            TextView e = PcViews.text(c, a.t("msg_loading"), 13f, PcViews.MUTED, 400);
            e.setPadding(dp(10), dp(10), dp(10), dp(10));
            items.addView(e);
            return;
        }
        for (final PcJson.O l : languages) {
            boolean cur = l.str("id").equals(langCurrent);
            LinearLayout it = PcViews.row(c);
            it.setPadding(dp(12), dp(10), dp(12), dp(10));
            it.setBackground(cur ? PcViews.rect(c, 0x14FFFFFF, 10, 0, 0) : null);
            TextView chk = PcViews.text(c, cur ? "✓" : "", 13.5f, PcViews.RED, 700);
            it.addView(chk, PcViews.lp(dp(14), ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView ab = PcViews.monoText(c, l.str("abbr"), 12f, PcViews.SUBTEXT);
            ab.setTypeface(android.graphics.Typeface.create(PcViews.mono(), android.graphics.Typeface.BOLD));
            ab.setMinWidth(dp(24));
            LinearLayout.LayoutParams ap = PcViews.wrap();
            ap.leftMargin = dp(10);
            it.addView(ab, ap);
            TextView nm = PcViews.single(PcViews.text(c, l.str("name"), 13.5f, PcViews.TEXT, 500));
            LinearLayout.LayoutParams np = PcViews.weight(1);
            np.leftMargin = dp(10);
            it.addView(nm, np);
            TextView loc = PcViews.monoText(c, l.str("locale"), 11.5f, PcViews.MUTED);
            loc.setPadding(dp(12), 0, 0, 0);
            it.addView(loc);
            it.setClickable(true);
            PcViews.pressable(it);
            it.setOnClickListener(v -> setLanguage(l.str("id")));
            items.addView(it, PcViews.matchWrap());
        }
    }

    private void setLanguage(String id) {
        if (langMenu != null) langMenu.dismiss();
        a.api("POST", "/keyboard/set_language", PcJson.map("id", id), 6000, r -> {
            if (r.error != null) {
                a.status(a.t("msg_server_err"));
                return;
            }
            a.status(r.message());
            if (r.json().has("current")) {
                langCurrent = r.json().str("current");
                renderBadge();
            }
        });
    }

    void dismissPopups() {
        if (langMenu != null && langMenu.isShowing()) langMenu.dismiss();
    }

    // ------------------------------------------------------------------ processes
    private void buildProcesses() {
        procBox = PcViews.col(c);
        procBox.addView(PcViews.hr(c));
        LinearLayout bar = PcViews.row(c);
        bar.setPadding(0, dp(8), 0, dp(8));
        FrameLayout sw = new FrameLayout(c);
        procSearch = PcViews.field(c, a.t("proc_search_ph"), false, 12.5f);
        procSearch.setPadding(dp(30), dp(7), dp(28), dp(7));
        procSearch.setBackground(PcViews.rect(c, PcViews.SURFACE2, 10, PcViews.BORDER, 1));
        procSearch.setOnFocusChangeListener(null);
        procSearch.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int st, int co, int af) {}
            @Override public void onTextChanged(CharSequence s, int st, int be, int co) {}
            @Override public void afterTextChanged(Editable s) {
                a.ui.removeCallbacks(procFilter);
                a.ui.postDelayed(procFilter, 100);
            }
        });
        sw.addView(procSearch, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        ImageView si = PcViews.icon(c, PcAppIcons.SEARCH, PcViews.MUTED, 14);
        FrameLayout.LayoutParams sip = new FrameLayout.LayoutParams(dp(14), dp(14), Gravity.START | Gravity.CENTER_VERTICAL);
        sip.leftMargin = dp(9);
        sw.addView(si, sip);
        procClear = PcViews.text(c, "✕", 11f, PcViews.MUTED, 400);
        procClear.setGravity(Gravity.CENTER);
        procClear.setVisibility(View.GONE);
        procClear.setClickable(true);
        procClear.setOnClickListener(v -> {
            procSearch.setText("");
            procSearch.requestFocus();
        });
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(dp(20), dp(20), Gravity.END | Gravity.CENTER_VERTICAL);
        cp.rightMargin = dp(6);
        sw.addView(procClear, cp);
        bar.addView(sw, PcViews.weight(1));
        procCount = PcViews.monoText(c, "—", 11f, PcViews.MUTED);
        LinearLayout.LayoutParams cnt = PcViews.wrap();
        cnt.leftMargin = dp(8);
        bar.addView(procCount, cnt);
        PcViews.Btn refresh = new PcViews.Btn(c, PcAppIcons.REFRESH, "", 13);
        refresh.pad(10, 6).radius(8);
        refresh.setContentDescription(a.t("proc_refresh_tip"));
        refresh.setOnClickListener(v -> loadProcesses(false));
        LinearLayout.LayoutParams rp = PcViews.wrap();
        rp.leftMargin = dp(8);
        bar.addView(refresh, rp);
        procBox.addView(bar, PcViews.matchWrap());
        procBox.addView(PcViews.hr(c));
        procScroll = new PcViews.MaxScroll(c, 220);
        procList = PcViews.col(c);
        procScroll.addView(procList);
        procBox.addView(procScroll, PcViews.matchWrap());
        procBox.setVisibility(View.GONE);
        root.addView(procBox, PcViews.top(PcViews.matchWrap(), c, 10));
    }

    boolean closeProcessesIfOpen() {
        if (procOpen) {
            toggleProcesses();
            return true;
        }
        return false;
    }

    private void toggleProcesses() {
        procOpen = !procOpen;
        procBtn.setStyle(procOpen ? PcViews.B_ACTIVE : PcViews.B_DEFAULT);
        PcViews.animateHeight(procBox, procOpen, 240);
        if (procOpen) {
            loadProcesses(false);
            a.scrollIntoView(procBox);
        }
    }

    void loadProcesses(final boolean silent) {
        a.api("GET", "/processes", null, 10000, r -> {
            if (!r.ok()) {
                if (!silent && r.error != null) {
                    procList.removeAllViews();
                    procRows.clear();
                    procList.addView(emptyText(a.t("msg_server_err")));
                }
                return;
            }
            procs = r.jsonArray();
            renderProcesses();
        });
    }

    private TextView emptyText(String s) {
        TextView t = PcViews.text(c, s, 12f, PcViews.MUTED, 400);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(6), dp(14), dp(6), dp(14));
        return t;
    }

    private void renderProcesses() {
        String q = procSearch.getText().toString();
        procClear.setVisibility(q.trim().isEmpty() ? View.GONE : View.VISIBLE);
        List<PcJson.O> f = PcConn.filterProcesses(procs, q);
        procCount.setText(f.size() + " / " + procs.size());
        int scroll = procScroll.getScrollY();
        procList.removeAllViews();
        if (f.isEmpty()) {
            procRows.clear();
            procList.addView(emptyText(a.t(procs.isEmpty() ? "proc_empty" : "proc_not_found")));
            return;
        }
        Map<String, View> keep = new HashMap<>();
        for (int i = 0; i < f.size(); i++) {
            PcJson.O p = f.get(i);
            String key = p.str("pid") + "|" + p.str("name");
            View row = procRows.get(key);
            if (row == null) row = procRow(p);
            if (row.getParent() != null) ((ViewGroup) row.getParent()).removeView(row);
            procList.addView(row, PcViews.matchWrap());
            keep.put(key, row);
            View line = row.findViewWithTag("line");
            if (line != null) line.setVisibility(i == f.size() - 1 ? View.GONE : View.VISIBLE);
        }
        procRows.clear();
        procRows.putAll(keep);
        procScroll.post(() -> procScroll.scrollTo(0, scroll));
    }

    private View procRow(final PcJson.O p) {
        LinearLayout wrap = PcViews.col(c);
        LinearLayout row = PcViews.row(c);
        row.setPadding(dp(4), dp(7), dp(4), dp(7));
        TextView nm = PcViews.single(PcViews.text(c, p.str("name"), 12.5f, PcViews.TEXT, 500));
        row.addView(nm, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView pid = PcViews.monoText(c, "#" + p.str("pid"), 11f, PcViews.MUTED);
        LinearLayout.LayoutParams pp = PcViews.wrap();
        pp.leftMargin = dp(6);
        pp.rightMargin = dp(8);
        row.addView(pid, pp);
        PcViews.Btn kill = new PcViews.Btn(c, null, a.t("btn_terminate"));
        kill.pad(10, 5).size(11.5f).radius(8);
        kill.setStyle(PcViews.B_DANGER);
        kill.setOnClickListener(v -> confirmKill(p));
        row.addView(kill);
        wrap.addView(row, PcViews.matchWrap());
        View line = PcViews.hr(c);
        line.setTag("line");
        wrap.addView(line);
        return wrap;
    }

    private void confirmKill(final PcJson.O p) {
        final String name = p.str("name");
        a.confirm(a.t("btn_terminate"), a.t("msg_confirm_kill", "name", name, "pid", p.str("pid")),
                new String[]{a.t("btn_cancel"), a.t("btn_terminate")},
                new int[]{PcViews.B_SEC, PcViews.B_DANGER}, choice -> {
                    if (choice != 1) return;
                    a.api("POST", "/processes/kill", PcJson.map("pid", p.integer("pid", 0), "expected_name", name,
                            "create_time", p.num("create_time", 0.0)), 10000, r -> {
                        if (!r.message().isEmpty()) a.status(r.message());
                        loadProcesses(false);
                    });
                });
    }
}
