package com.pccontrol.remote;

import android.animation.ObjectAnimator;
import android.animation.ValueAnimator;
import android.content.Context;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.LinearInterpolator;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Launch routines (web/js/presets.js): main-screen routine buttons (run / cancel with live
 * status), the routines modal (list, editor with icon picker, ordered steps app / link / pause,
 * program search, unsaved-changes guards) — same endpoints /api/presets*, /api/programs/search.
 */
final class PcPresets {
    private final MainActivity a;
    private final Context c;

    private List<PcJson.O> presets = new ArrayList<>();
    private PcJson.O active = new PcJson.O(null);

    // editor state
    private Map<String, Object> editing;          // {id, name, icon, steps:[{type,name,target,seconds}]}
    private int editingStep = -1;
    private String stepTab = "app";
    private String snapshot;
    private boolean animatingMove;

    // modal views
    PcModal modal;
    private LinearLayout listView, listCards, editorView, stepsBox, iconPicker, suggestBox;
    private TextView editorTitle, actionHeading, cancelStepBtn;
    private EditText nameField, progSearch, progPath, urlField, urlName, delaySec;
    private TextView[] stepTabs;
    private LinearLayout paneApp, paneUrl, paneDelay;
    private PcViews.Btn submitApp, submitUrl, submitDelay, deleteBtn;
    private final Runnable searchRunner = this::runProgramSearch;
    private boolean suppressSearch;

    PcPresets(MainActivity act) {
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

    boolean anyRunning() {
        for (Object v : active.map.values()) {
            if (v instanceof Map) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ data
    void load() {
        a.api("GET", "/api/presets", null, 8000, r -> {
            if (!r.ok()) return;
            presets = r.json().objs("presets");
            active = r.json().obj("active");
            renderMainButtons();
            if (isOpen()) renderList();
        });
    }

    void pollStatus() {
        a.api("GET", "/api/presets/status", null, 6000, r -> {
            if (!r.ok()) return;
            PcJson.O old = active;
            active = r.json().obj("active");
            for (Map.Entry<String, Object> e : active.map.entrySet()) {
                PcJson.O st = active.obj(e.getKey());
                if ("error".equals(st.str("status"))) {
                    String err = st.str("error");
                    a.status(err.isEmpty() ? t("preset_err_run") : err);
                }
            }
            for (String pid : old.map.keySet()) {
                String name = nameOf(pid);
                String was = old.obj(pid).str("status");
                if ("running".equals(was) && !active.has(pid)) a.status(t("preset_msg_completed", "name", name));
                else if ("cancelling".equals(was) && !active.has(pid)) a.status(t("preset_msg_cancelled", "name", name));
            }
            renderMainButtons();
        });
    }

    private String nameOf(String id) {
        for (PcJson.O p : presets) if (p.str("id").equals(id)) return p.str("name");
        return id;
    }

    private PcJson.O find(String id) {
        for (PcJson.O p : presets) if (p.str("id").equals(id)) return p;
        return null;
    }

    // ------------------------------------------------------------------ main buttons
    void renderMainButtons() {
        PcViews.Grid flow = a.input != null ? a.input.presetsFlow : null;
        if (flow == null) return;
        flow.removeAllViews();
        for (final PcJson.O p : presets) {
            final String id = p.str("id");
            final String name = p.str("name").isEmpty() ? t("preset_default_name") : p.str("name");
            String st = active.obj(id).str("status", "idle");
            boolean hasSteps = !p.list("steps").isEmpty();
            PcViews.Btn b;
            if ("running".equals(st)) {
                b = new PcViews.Btn(c, PcAppIcons.SPINNER, name + " (" + t("preset_status_running") + ")", 16);
                b.setStyle(PcViews.B_RUNNING);
                spin(b.iconView);
                b.setOnClickListener(v -> cancel(id, name));
            } else if ("cancelling".equals(st)) {
                b = new PcViews.Btn(c, PcAppIcons.CLOSE, t("preset_status_cancelling"), 16);
                b.setStyle(PcViews.B_CANCELLING);
            } else {
                b = new PcViews.Btn(c, PcAppIcons.preset(p.str("icon")), hasSteps ? name : name + " (0)", 15);
                b.setStyle(PcViews.B_SEC);
                b.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
                b.size(13f);
                if (!hasSteps) b.setContentDescription(t("preset_empty_steps_tip"));
                b.setOnClickListener(v -> run(id, name));
            }
            b.pad(12, 11);
            b.setMinimumHeight(dp(42));
            b.label.setSingleLine(false);
            b.label.setMaxLines(2);
            ((LinearLayout.LayoutParams) b.label.getLayoutParams()).leftMargin = dp(7);
            flow.addView(b);
        }
    }

    private static void spin(View v) {
        if (v == null) return;
        ObjectAnimator an = ObjectAnimator.ofFloat(v, "rotation", 0f, 360f);
        an.setDuration(1000);
        an.setRepeatCount(ValueAnimator.INFINITE);
        an.setInterpolator(new LinearInterpolator());
        an.start();
    }

    private void run(final String id, final String name) {
        PcJson.O p = find(id);
        if (p != null && p.list("steps").isEmpty()) {
            String msg = t("preset_msg_no_steps", "name", name);
            a.status(msg);
            a.alert(msg, () -> {
                open();
                edit(id);
            });
            return;
        }
        a.status(t("preset_msg_started", "name", name));
        active.map.put(id, PcJson.map("status", "running"));
        renderMainButtons();
        a.api("POST", "/api/presets/run", PcJson.map("id", id), 10000, r -> {
            if (!r.ok()) {
                active.map.remove(id);
                renderMainButtons();
                if (r.error != null) return;
                String err = r.message().isEmpty() ? t("preset_err_launch") : r.message();
                a.status(err);
                a.alert(err, null);
                return;
            }
            if (!r.message().isEmpty()) a.status(r.message());
            pollStatus();
        });
    }

    private void cancel(final String id, String name) {
        a.status(t("preset_msg_cancelling", "name", name));
        active.map.put(id, PcJson.map("status", "cancelling"));
        renderMainButtons();
        a.api("POST", "/api/presets/cancel", PcJson.map("id", id), 8000, r -> {
            if (!r.message().isEmpty()) a.status(r.message());
            pollStatus();
        });
    }

    // ------------------------------------------------------------------ modal
    void open() {
        if (isOpen()) return;
        buildModal();
        backToList(true);
        modal.show(a.root);
        a.registerModal(modal);
        load();
    }

    void close() {
        checkUnsavedAndProceed(() -> {
            if (modal != null) modal.dismiss();
            load();
        });
    }

    private void buildModal() {
        modal = new PcModal(c, PcModal.KIND_SETTINGS, 440);
        modal.onBackRequest = this::close;
        LinearLayout ct = modal.content;
        ct.addView(PcModal.header(c, PcAppIcons.SPARKLE, t("presets_modal_title"), t("presets_modal_sub"), this::close));

        // list view
        listView = PcViews.col(c);
        listCards = PcViews.col(c);
        LinearLayout.LayoutParams lcp = PcViews.matchWrap();
        lcp.bottomMargin = dp(12);
        listView.addView(listCards, lcp);
        PcViews.Btn add = new PcViews.Btn(c, null, t("preset_btn_add"));
        add.setStyle(PcViews.B_RED);
        add.pad(14, 12);
        add.setOnClickListener(v -> checkUnsavedAndProceed(this::startNew));
        listView.addView(add, PcViews.matchWrap());
        ct.addView(listView, PcViews.matchWrap());

        // editor view
        editorView = PcViews.col(c);
        LinearLayout top = PcViews.row(c);
        editorTitle = PcViews.text(c, t("preset_editor_new_title"), 14f, PcViews.TEXT, 700);
        top.addView(editorTitle, PcViews.weight(1));
        TextView back = PcViews.text(c, t("preset_btn_back"), 12f, PcViews.SUBTEXT, 400);
        back.setPadding(dp(6), dp(4), 0, dp(4));
        back.setClickable(true);
        back.setOnClickListener(v -> checkUnsavedAndProceed(this::doBackToList));
        top.addView(back);
        LinearLayout.LayoutParams tp = PcViews.matchWrap();
        tp.bottomMargin = dp(10);
        editorView.addView(top, tp);

        editorView.addView(PcModal.label(c, t("preset_lbl_name")));
        nameField = PcViews.field(c, t("preset_name_placeholder"), true, 13f);
        editorView.addView(nameField, PcViews.top(PcViews.matchWrap(), c, 0));

        TextView il = PcModal.label(c, t("preset_lbl_icon"));
        ((LinearLayout.LayoutParams) il.getLayoutParams()).topMargin = dp(10);
        editorView.addView(il);
        HorizontalScrollView hs = new HorizontalScrollView(c);
        hs.setHorizontalScrollBarEnabled(false);
        iconPicker = PcViews.row(c);
        iconPicker.setPadding(dp(1), dp(3), dp(1), dp(7));
        hs.addView(iconPicker);
        LinearLayout.LayoutParams hsp = PcViews.matchWrap();
        hsp.bottomMargin = dp(8);
        editorView.addView(hs, hsp);

        TextView sl = PcModal.label(c, t("preset_steps_heading"));
        editorView.addView(sl);
        stepsBox = PcViews.col(c);
        LinearLayout.LayoutParams sbp = PcViews.matchWrap();
        sbp.bottomMargin = dp(10);
        editorView.addView(stepsBox, sbp);

        // add-action box
        LinearLayout box = PcViews.col(c);
        box.setBackground(PcViews.rect(c, PcViews.SURFACE2, 14, PcViews.BORDER, 1));
        box.setPadding(dp(10), dp(10), dp(10), dp(10));
        LinearLayout bh = PcViews.row(c);
        actionHeading = PcViews.text(c, t("preset_add_action_lbl"), 11.5f, PcViews.SUBTEXT, 600);
        bh.addView(actionHeading, PcViews.weight(1));
        cancelStepBtn = PcViews.text(c, t("preset_btn_cancel_step"), 11.5f, 0xFFEF4444, 600);
        cancelStepBtn.setPadding(dp(6), dp(2), dp(6), dp(2));
        cancelStepBtn.setClickable(true);
        cancelStepBtn.setVisibility(View.GONE);
        cancelStepBtn.setOnClickListener(v -> requestCancelEditingStep());
        bh.addView(cancelStepBtn);
        LinearLayout.LayoutParams bhp = PcViews.matchWrap();
        bhp.bottomMargin = dp(8);
        box.addView(bh, bhp);
        LinearLayout tabsHolder = PcViews.col(c);
        stepTabs = PcModal.tabs(c, tabsHolder, new String[]{t("preset_tab_app"), t("preset_tab_url"), t("preset_tab_delay")},
                new String[][]{PcAppIcons.P_APP, PcAppIcons.P_WEB, PcAppIcons.P_DELAY}, 11.5f, 6);
        // the step tabs are plain buttons in a row (no bar background) in the web UI
        View bar = tabsHolder.getChildAt(0);
        bar.setBackground(null);
        bar.setPadding(0, 0, 0, 0);
        for (int i = 0; i < 3; i++) {
            final String k = i == 0 ? "app" : i == 1 ? "url" : "delay";
            stepTabs[i].setOnClickListener(v -> switchStepTab(k));
            ((LinearLayout.LayoutParams) stepTabs[i].getLayoutParams()).leftMargin = i == 0 ? 0 : dp(5);
        }
        LinearLayout.LayoutParams thp = PcViews.matchWrap();
        thp.bottomMargin = dp(10);
        box.addView(tabsHolder, thp);

        paneApp = PcViews.col(c);
        progSearch = PcViews.field(c, t("preset_search_placeholder"), true, 13f);
        progSearch.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int st, int co, int af) {}
            @Override public void onTextChanged(CharSequence s, int st, int be, int co) {}
            @Override public void afterTextChanged(Editable s) {
                if (suppressSearch) return;
                a.ui.removeCallbacks(searchRunner);
                if (s.toString().trim().isEmpty()) suggestBox.setVisibility(View.GONE);
                else a.ui.postDelayed(searchRunner, 220);
            }
        });
        paneApp.addView(progSearch, PcViews.matchWrap());
        suggestBox = PcViews.col(c);
        suggestBox.setBackground(PcViews.rect(c, PcViews.SURFACE, 10, PcViews.BORDER, 1));
        suggestBox.setVisibility(View.GONE);
        paneApp.addView(suggestBox, PcViews.top(PcViews.matchWrap(), c, 4));
        TextView ml = PcViews.text(c, t("preset_manual_path_lbl"), 11f, PcViews.MUTED, 400);
        paneApp.addView(ml, PcViews.top(PcViews.matchWrap(), c, 6));
        progPath = PcViews.field(c, t("preset_manual_path_placeholder"), true, 12f);
        LinearLayout.LayoutParams ppp = PcViews.top(PcViews.matchWrap(), c, 3);
        ppp.bottomMargin = dp(8);
        paneApp.addView(progPath, ppp);
        submitApp = secBtn(t("preset_btn_add_step"));
        submitApp.setOnClickListener(v -> addAppStep());
        paneApp.addView(submitApp, PcViews.matchWrap());
        box.addView(paneApp, PcViews.matchWrap());

        paneUrl = PcViews.col(c);
        urlField = PcViews.field(c, t("preset_url_placeholder"), true, 13f);
        urlField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        LinearLayout.LayoutParams up = PcViews.matchWrap();
        up.bottomMargin = dp(6);
        paneUrl.addView(urlField, up);
        urlName = PcViews.field(c, t("preset_url_name_placeholder"), true, 13f);
        LinearLayout.LayoutParams unp = PcViews.matchWrap();
        unp.bottomMargin = dp(8);
        paneUrl.addView(urlName, unp);
        submitUrl = secBtn(t("preset_btn_add_step"));
        submitUrl.setOnClickListener(v -> addUrlStep());
        paneUrl.addView(submitUrl, PcViews.matchWrap());
        paneUrl.setVisibility(View.GONE);
        box.addView(paneUrl, PcViews.matchWrap());

        paneDelay = PcViews.col(c);
        LinearLayout dr = PcViews.row(c);
        delaySec = PcViews.field(c, "", true, 13f);
        delaySec.setInputType(InputType.TYPE_CLASS_NUMBER);
        delaySec.setGravity(Gravity.CENTER);
        delaySec.setText("3");
        dr.addView(delaySec, PcViews.lp(dp(90), ViewGroup.LayoutParams.WRAP_CONTENT));
        TextView dl = PcViews.text(c, t("preset_delay_lbl"), 12.5f, PcViews.SUBTEXT, 400);
        LinearLayout.LayoutParams dlp = PcViews.wrap();
        dlp.leftMargin = dp(8);
        dr.addView(dl, dlp);
        LinearLayout.LayoutParams drp = PcViews.matchWrap();
        drp.bottomMargin = dp(8);
        paneDelay.addView(dr, drp);
        LinearLayout quick = PcViews.row(c);
        int[] secs = {1, 3, 5, 10};
        for (int i = 0; i < secs.length; i++) {
            final int s = secs[i];
            PcViews.Btn q = secBtn(t("delay_sec_short", "n", s));
            q.pad(5, 5);
            q.setOnClickListener(v -> delaySec.setText(String.valueOf(s)));
            LinearLayout.LayoutParams qp = PcViews.weight(1);
            if (i > 0) qp.leftMargin = dp(6);
            quick.addView(q, qp);
        }
        LinearLayout.LayoutParams qrp = PcViews.matchWrap();
        qrp.bottomMargin = dp(8);
        paneDelay.addView(quick, qrp);
        submitDelay = secBtn(t("preset_btn_add_step"));
        submitDelay.setOnClickListener(v -> addDelayStep());
        paneDelay.addView(submitDelay, PcViews.matchWrap());
        paneDelay.setVisibility(View.GONE);
        box.addView(paneDelay, PcViews.matchWrap());

        LinearLayout.LayoutParams boxp = PcViews.matchWrap();
        boxp.bottomMargin = dp(12);
        editorView.addView(box, boxp);

        LinearLayout actions = PcViews.row(c);
        deleteBtn = new PcViews.Btn(c, null, t("preset_btn_delete"));
        deleteBtn.setStyle(PcViews.B_DANGER);
        deleteBtn.pad(14, 10).size(12.5f);
        deleteBtn.label.setTypeface(PcViews.face(600));
        deleteBtn.setOnClickListener(v -> {
            if (editing != null && !str(editing.get("id")).isEmpty()) {
                confirmDelete(str(editing.get("id")), str(editing.get("name")).isEmpty() ? t("preset_default_name") : str(editing.get("name")));
            }
        });
        actions.addView(deleteBtn, PcViews.wrap());
        PcViews.Btn save = new PcViews.Btn(c, null, t("preset_btn_save"));
        save.setStyle(PcViews.B_RED);
        save.pad(14, 10);
        save.setOnClickListener(v -> saveEditing(true, null));
        LinearLayout.LayoutParams svp = PcViews.weight(1);
        svp.leftMargin = dp(8);
        actions.addView(save, svp);
        editorView.addView(actions, PcViews.matchWrap());
        editorView.setVisibility(View.GONE);
        ct.addView(editorView, PcViews.matchWrap());
    }

    private PcViews.Btn secBtn(String s) {
        PcViews.Btn b = new PcViews.Btn(c, null, s);
        b.setStyle(PcViews.B_SEC);
        b.pad(10, 8).size(12.5f);
        return b;
    }

    // ------------------------------------------------------------------ list
    private void renderList() {
        if (listCards == null) return;
        listCards.removeAllViews();
        if (presets.isEmpty()) {
            TextView e = PcViews.text(c, t("preset_empty_list"), 12.5f, PcViews.MUTED, 400);
            e.setGravity(Gravity.CENTER);
            e.setPadding(dp(14), dp(14), dp(14), dp(14));
            e.setBackground(PcViews.rect(c, PcViews.SURFACE2, 14, PcViews.BORDER, 1));
            listCards.addView(e, PcViews.matchWrap());
            return;
        }
        for (int i = 0; i < presets.size(); i++) {
            final PcJson.O p = presets.get(i);
            LinearLayout card = PcViews.col(c);
            card.setBackground(PcViews.rect(c, PcViews.SURFACE2, 14, PcViews.BORDER, 1));
            card.setPadding(dp(12), dp(12), dp(12), dp(12));
            LinearLayout head = PcViews.row(c);
            FrameLayout ib = new FrameLayout(c);
            ib.setBackground(PcViews.rect(c, 0x1FFF0033, 8, 0, 0));
            ib.addView(PcViews.icon(c, PcAppIcons.preset(p.str("icon")), PcViews.PRESET_RED, 15),
                    new FrameLayout.LayoutParams(dp(15), dp(15), Gravity.CENTER));
            head.addView(ib, PcViews.lp(dp(28), dp(28)));
            String name = p.str("name").isEmpty() ? t("preset_default_name") : p.str("name");
            TextView nt = PcViews.single(PcViews.text(c, name, 14f, PcViews.TEXT, 600));
            LinearLayout.LayoutParams np = PcViews.weight(1);
            np.leftMargin = dp(8);
            head.addView(nt, np);
            head.addView(PcViews.monoText(c, p.list("steps").size() + " " + t("preset_steps_cnt"), 11f, PcViews.MUTED));
            card.addView(head, PcViews.matchWrap());
            TextView steps = PcViews.text(c, stepsSummary(p), 11.5f, PcViews.SUBTEXT, 400);
            steps.setLineSpacing(0, 1.4f);
            card.addView(steps, PcViews.top(PcViews.matchWrap(), c, 6));
            LinearLayout act = PcViews.row(c);
            PcViews.Btn edit = new PcViews.Btn(c, PcAppIcons.PENCIL, t("preset_btn_edit"), 13);
            edit.setStyle(PcViews.B_SEC);
            edit.pad(10, 7).size(12f);
            ((LinearLayout.LayoutParams) edit.label.getLayoutParams()).leftMargin = dp(6);
            edit.setOnClickListener(v -> edit(p.str("id")));
            act.addView(edit, PcViews.weight(1));
            PcViews.Btn del = new PcViews.Btn(c, PcAppIcons.TRASH, "", 13);
            del.setStyle(PcViews.B_DANGER);
            del.pad(12, 7);
            del.setContentDescription(t("preset_btn_delete"));
            del.setOnClickListener(v -> confirmDelete(p.str("id"), name));
            LinearLayout.LayoutParams dp2 = PcViews.wrap();
            dp2.leftMargin = dp(6);
            act.addView(del, dp2);
            card.addView(act, PcViews.top(PcViews.matchWrap(), c, 10));
            LinearLayout.LayoutParams cp = PcViews.matchWrap();
            if (i > 0) cp.topMargin = dp(8);
            listCards.addView(card, cp);
        }
    }

    private String stepsSummary(PcJson.O p) {
        StringBuilder sb = new StringBuilder();
        for (PcJson.O s : p.objs("steps")) {
            String type = s.str("type");
            String part;
            if ("app".equals(type)) part = s.str("name").isEmpty() ? t("preset_step_app") : s.str("name");
            else if ("url".equals(type)) part = !s.str("name").isEmpty() ? s.str("name") : (!s.str("target").isEmpty() ? s.str("target") : t("preset_step_url"));
            else if ("delay".equals(type)) part = s.integer("seconds", 1) + " " + t("preset_delay_lbl");
            else part = s.str("name");
            if (sb.length() > 0) sb.append("  →  ");
            sb.append(part);
        }
        return sb.length() > 0 ? sb.toString() : t("preset_no_steps");
    }

    private void backToList(boolean force) {
        if (!force) {
            checkUnsavedAndProceed(this::doBackToList);
            return;
        }
        doBackToList();
    }

    private void doBackToList() {
        editingStep = -1;
        snapshot = null;
        editing = null;
        if (editorView == null) return;
        editorView.setVisibility(View.GONE);
        listView.setVisibility(View.VISIBLE);
        PcViews.fadeIn(listView);
        a.hideKeyboard(modal);
        renderList();
    }

    // ------------------------------------------------------------------ editor
    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> steps() {
        Object s = editing.get("steps");
        if (!(s instanceof List)) {
            s = new ArrayList<Map<String, Object>>();
            editing.put("steps", s);
        }
        return (List<Map<String, Object>>) s;
    }

    private String snapshotOf() {
        return PcJson.stringify(PcJson.map("id", str(editing.get("id")), "name", nameField.getText().toString().trim(),
                "icon", str(editing.get("icon")).isEmpty() ? "bolt" : str(editing.get("icon")), "steps", steps()));
    }

    private void startNew() {
        editingStep = -1;
        editing = new LinkedHashMap<>();
        editing.put("id", "");
        editing.put("name", "");
        editing.put("icon", "bolt");
        editing.put("steps", new ArrayList<Map<String, Object>>());
        nameField.setText("");
        snapshot = snapshotOf();
        editorTitle.setText(t("preset_editor_new_title"));
        deleteBtn.setVisibility(View.GONE);
        showEditor();
    }

    void edit(final String id) {
        checkUnsavedAndProceed(() -> doEdit(id));
    }

    @SuppressWarnings("unchecked")
    private void doEdit(String id) {
        PcJson.O found = find(id);
        if (found == null || listView == null) return;
        editingStep = -1;
        editing = (Map<String, Object>) PcJson.parse(PcJson.stringify(found.map)); // deep copy
        if (!PcAppIcons.isPresetKey(str(editing.get("icon")))) editing.put("icon", "bolt");
        nameField.setText(str(editing.get("name")));
        snapshot = snapshotOf();
        editorTitle.setText(t("preset_editor_edit_title"));
        deleteBtn.setVisibility(View.VISIBLE);
        showEditor();
    }

    private void showEditor() {
        listView.setVisibility(View.GONE);
        editorView.setVisibility(View.VISIBLE);
        PcViews.fadeIn(editorView);
        resetStepInputs();
        switchStepTab("app");
        renderIconPicker();
        renderSteps();
        updateActionBox();
        modal.box.post(() -> modal.box.scrollTo(0, 0));
    }

    private void renderIconPicker() {
        iconPicker.removeAllViews();
        String cur = str(editing.get("icon"));
        String[] names = {"preset_icon_bolt", "preset_icon_game", "preset_icon_rocket", "preset_icon_web",
                "preset_icon_terminal", "preset_icon_music", "preset_icon_app", "preset_icon_delay"};
        for (int i = 0; i < PcAppIcons.PRESET_KEYS.length; i++) {
            final String k = PcAppIcons.PRESET_KEYS[i];
            boolean on = k.equals(cur);
            FrameLayout b = new FrameLayout(c);
            b.setBackground(on ? PcViews.rect(c, 0x26FF0033, 10, PcViews.RED, 1) : PcViews.rect(c, PcViews.SURFACE, 10, PcViews.BORDER, 1));
            b.addView(PcViews.icon(c, PcAppIcons.preset(k), on ? PcViews.PRESET_RED : PcViews.SUBTEXT, 17),
                    new FrameLayout.LayoutParams(dp(17), dp(17), Gravity.CENTER));
            b.setContentDescription(t(names[i]));
            b.setClickable(true);
            PcViews.pressable(b, 0.92f);
            b.setOnClickListener(v -> {
                editing.put("icon", k);
                renderIconPicker();
            });
            LinearLayout.LayoutParams p = PcViews.lp(dp(36), dp(36));
            if (i > 0) p.leftMargin = dp(6);
            iconPicker.addView(b, p);
        }
    }

    private void switchStepTab(String tab) {
        stepTab = tab;
        int idx = "app".equals(tab) ? 0 : "url".equals(tab) ? 1 : 2;
        PcModal.selectTab(c, stepTabs, idx);
        paneApp.setVisibility(idx == 0 ? View.VISIBLE : View.GONE);
        paneUrl.setVisibility(idx == 1 ? View.VISIBLE : View.GONE);
        paneDelay.setVisibility(idx == 2 ? View.VISIBLE : View.GONE);
    }

    private void updateActionBox() {
        if (editingStep >= 0) {
            int n = editingStep + 1;
            actionHeading.setText(t("preset_edit_action_lbl", "num", n));
            cancelStepBtn.setVisibility(View.VISIBLE);
            String s = t("preset_btn_save_step", "num", n);
            submitApp.setText(s);
            submitUrl.setText(s);
            submitDelay.setText(s);
        } else {
            actionHeading.setText(t("preset_add_action_lbl"));
            cancelStepBtn.setVisibility(View.GONE);
            String s = t("preset_btn_add_step");
            submitApp.setText(s);
            submitUrl.setText(s);
            submitDelay.setText(s);
        }
    }

    private void renderSteps() {
        stepsBox.removeAllViews();
        List<Map<String, Object>> st = steps();
        if (st.isEmpty()) {
            TextView e = PcViews.text(c, t("preset_no_steps"), 12f, PcViews.MUTED, 400);
            e.setGravity(Gravity.CENTER);
            e.setPadding(dp(10), dp(10), dp(10), dp(10));
            e.setBackground(PcViews.rect(c, PcViews.SURFACE2, 10, PcViews.BORDER, 1));
            stepsBox.addView(e, PcViews.matchWrap());
            return;
        }
        for (int i = 0; i < st.size(); i++) {
            final int idx = i;
            Map<String, Object> s = st.get(i);
            String type = str(s.get("type"));
            boolean editingThis = editingStep == i;
            LinearLayout row = PcViews.row(c);
            row.setPadding(dp(10), dp(8), dp(10), dp(8));
            row.setBackground(editingThis ? PcViews.rect(c, 0x14FF0033, 10, PcViews.RED, 1) : PcViews.rect(c, PcViews.SURFACE, 10, PcViews.BORDER, 1));
            TextView num = PcViews.text(c, "#" + (i + 1), 11f, PcViews.MUTED, 700);
            num.setMinWidth(dp(18));
            row.addView(num);
            LinearLayout badge = PcViews.row(c);
            badge.setBackground(PcViews.rect(c, 0x14FFFFFF, 6, 0, 0));
            badge.setPadding(dp(6), dp(3), dp(6), dp(3));
            badge.addView(PcViews.icon(c, "url".equals(type) ? PcAppIcons.P_WEB : "delay".equals(type) ? PcAppIcons.P_DELAY : PcAppIcons.P_APP, PcViews.SUBTEXT, 12));
            TextView bt = PcViews.text(c, "url".equals(type) ? "URL" : "delay".equals(type) ? "DELAY" : "APP", 10f, PcViews.SUBTEXT, 700);
            bt.setLetterSpacing(0.03f);
            LinearLayout.LayoutParams btp = PcViews.wrap();
            btp.leftMargin = dp(4);
            badge.addView(bt, btp);
            LinearLayout.LayoutParams bp = PcViews.wrap();
            bp.leftMargin = dp(8);
            row.addView(badge, bp);
            String desc = "delay".equals(type) ? (str(s.get("seconds")).replaceAll("\\.0$", "") + " " + t("preset_delay_lbl"))
                    : (str(s.get("name")) + (!str(s.get("target")).isEmpty() && !str(s.get("target")).equals(str(s.get("name"))) ? " (" + str(s.get("target")) + ")" : ""));
            TextView body = PcViews.single(PcViews.text(c, desc, 12f, PcViews.TEXT, 400));
            LinearLayout.LayoutParams bdp = PcViews.weight(1);
            bdp.leftMargin = dp(8);
            row.addView(body, bdp);
            row.addView(stepBtn(PcAppIcons.PENCIL, editingThis ? PcViews.PRESET_RED : PcViews.SUBTEXT,
                    editingThis ? 0x2EFF0033 : 0x0FFFFFFF, t("preset_btn_edit"), v -> requestStartEditingStep(idx)));
            if (i > 0) row.addView(stepBtn(PcAppIcons.UP, PcViews.SUBTEXT, 0x0FFFFFFF, t("tip_move_up"), v -> moveStep(idx, -1)));
            if (i < st.size() - 1) row.addView(stepBtn(PcAppIcons.DOWN, PcViews.SUBTEXT, 0x0FFFFFFF, t("tip_move_down"), v -> moveStep(idx, 1)));
            row.addView(stepBtn(PcAppIcons.TRASH, 0xFFEF4444, 0x0FFFFFFF, t("tip_delete"), v -> removeStep(idx)));
            row.setClickable(true);
            row.setOnClickListener(v -> {
                if (editingStep == idx) requestCancelEditingStep();
                else requestStartEditingStep(idx);
            });
            LinearLayout.LayoutParams rp = PcViews.matchWrap();
            rp.bottomMargin = dp(6);
            stepsBox.addView(row, rp);
        }
    }

    private View stepBtn(String[] icon, int color, int bg, String desc, View.OnClickListener l) {
        FrameLayout b = new FrameLayout(c);
        b.setBackground(PcViews.rect(c, bg, 6, 0, 0));
        b.addView(PcViews.icon(c, icon, color, 12), new FrameLayout.LayoutParams(dp(12), dp(12), Gravity.CENTER));
        b.setContentDescription(desc);
        b.setClickable(true);
        PcViews.pressable(b, 0.9f);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams p = PcViews.lp(dp(26), dp(26));
        p.leftMargin = dp(4);
        b.setLayoutParams(p);
        return b;
    }

    private void moveStep(final int idx, int dir) {
        if (animatingMove) return;
        final List<Map<String, Object>> st = steps();
        final int target = idx + dir;
        if (target < 0 || target >= st.size()) return;
        final View rowA = stepsBox.getChildAt(idx), rowB = stepsBox.getChildAt(target);
        Runnable swap = () -> {
            Map<String, Object> tmp = st.get(idx);
            st.set(idx, st.get(target));
            st.set(target, tmp);
            if (editingStep == idx) editingStep = target;
            else if (editingStep == target) editingStep = idx;
            updateActionBox();
            renderSteps();
            animatingMove = false;
        };
        if (rowA != null && rowB != null) {
            animatingMove = true;
            float diff = rowB.getTop() - rowA.getTop();
            rowA.setElevation(dp(6));
            rowA.animate().translationY(diff).setDuration(260).setInterpolator(new android.view.animation.PathInterpolator(0.2f, 0.85f, 0.3f, 1f)).start();
            rowB.animate().translationY(-diff).setDuration(260).setInterpolator(new android.view.animation.PathInterpolator(0.2f, 0.85f, 0.3f, 1f)).withEndAction(swap).start();
        } else {
            swap.run();
        }
    }

    private void removeStep(final int idx) {
        final List<Map<String, Object>> st = steps();
        Runnable doIt = () -> {
            if (idx >= st.size()) return;
            st.remove(idx);
            if (editingStep == idx) cancelEditingStep();
            else {
                if (editingStep > idx) editingStep--;
                updateActionBox();
                renderSteps();
            }
        };
        View row = stepsBox.getChildAt(idx);
        if (row != null) row.animate().alpha(0f).scaleX(0.92f).scaleY(0.92f).setDuration(200).withEndAction(doIt).start();
        else doIt.run();
    }

    private void resetStepInputs() {
        suppressSearch = true;
        progSearch.setText("");
        progPath.setText("");
        urlField.setText("");
        urlName.setText("");
        delaySec.setText("3");
        suppressSearch = false;
        suggestBox.setVisibility(View.GONE);
    }

    private boolean hasUnsavedStepInput() {
        if (editing == null) return false;
        String n = progSearch.getText().toString().trim(), p = progPath.getText().toString().trim();
        String u = urlField.getText().toString().trim(), un = urlName.getText().toString().trim();
        if (editingStep == -1) {
            if ("app".equals(stepTab)) return !n.isEmpty() || !p.isEmpty();
            if ("url".equals(stepTab)) return !u.isEmpty() || !un.isEmpty();
            return false;
        }
        List<Map<String, Object>> st = steps();
        if (editingStep >= st.size()) return false;
        Map<String, Object> s = st.get(editingStep);
        if (!stepTab.equals(str(s.get("type")))) return true;
        if ("app".equals(stepTab)) return !n.equals(str(s.get("name")).trim()) || !p.equals(str(s.get("target")).trim());
        if ("url".equals(stepTab)) return !u.equals(str(s.get("target")).trim()) || !un.equals(str(s.get("name")).trim());
        int sec;
        try {
            sec = Integer.parseInt(delaySec.getText().toString().trim());
        } catch (NumberFormatException e) {
            sec = 3;
        }
        Object so = s.get("seconds");
        int orig = so instanceof Number ? ((Number) so).intValue() : 3;
        return sec != orig;
    }

    private boolean hasUnsavedChanges() {
        if (editing == null || editorView == null || editorView.getVisibility() != View.VISIBLE) return false;
        if (snapshot == null) {
            return !nameField.getText().toString().trim().isEmpty() || !steps().isEmpty() || hasUnsavedStepInput();
        }
        return !snapshotOf().equals(snapshot) || hasUnsavedStepInput();
    }

    private String pendingStepName() {
        if ("app".equals(stepTab)) {
            String n = progSearch.getText().toString().trim(), p = progPath.getText().toString().trim();
            String r = !n.isEmpty() ? n : (!p.isEmpty() ? PcConn.appStepName("", p) : "");
            return r.isEmpty() ? t("preset_tab_app") : r;
        }
        if ("url".equals(stepTab)) {
            String n = urlName.getText().toString().trim(), u = urlField.getText().toString().trim();
            String r = !n.isEmpty() ? n : (!u.isEmpty() ? PcConn.urlStepName("", u) : "");
            return r.isEmpty() ? t("preset_tab_url") : r;
        }
        String s = delaySec.getText().toString().trim();
        return (s.isEmpty() ? "3" : s) + " " + t("preset_delay_lbl");
    }

    private boolean savePendingStep() {
        if ("app".equals(stepTab)) return addAppStep();
        if ("url".equals(stepTab)) return addUrlStep();
        return addDelayStep();
    }

    private void checkUnsavedAndProceed(final Runnable proceed) {
        if (!hasUnsavedChanges()) {
            proceed.run();
            return;
        }
        a.confirm(t("preset_unsaved_title"), t("preset_unsaved_desc"),
                new String[]{t("preset_btn_save"), t("preset_btn_discard"), t("preset_btn_cancel")},
                new int[]{PcViews.B_RED, PcViews.B_SEC, PcViews.B_SEC}, choice -> {
                    if (choice == 0) {
                        saveEditing(false, () -> {
                            snapshot = null;
                            proceed.run();
                        });
                    } else if (choice == 1) {
                        snapshot = null;
                        editing = null;
                        proceed.run();
                    }
                });
    }

    private void requestStartEditingStep(final int target) {
        if (editing == null || target >= steps().size() || editingStep == target) return;
        if (hasUnsavedStepInput()) {
            boolean isNew = editingStep == -1;
            String name = pendingStepName();
            String msg = isNew ? t("preset_step_unsaved_desc_new", "name", name)
                    : t("preset_step_unsaved_desc_edit", "num", editingStep + 1, "name", name);
            String saveTxt = isNew ? t("preset_btn_add_step") : t("preset_btn_save_step", "num", editingStep + 1);
            a.confirm(t("preset_step_unsaved_title"), msg, new String[]{saveTxt, t("preset_btn_discard"), t("preset_btn_cancel")},
                    new int[]{PcViews.B_RED, PcViews.B_SEC, PcViews.B_SEC}, choice -> {
                        if (choice == 0) {
                            if (!savePendingStep()) return;
                        } else if (choice == 1) {
                            resetStepInputs();
                            editingStep = -1;
                        } else {
                            return;
                        }
                        doStartEditingStep(target);
                    });
            return;
        }
        doStartEditingStep(target);
    }

    private void doStartEditingStep(int idx) {
        List<Map<String, Object>> st = steps();
        if (idx >= st.size()) return;
        editingStep = idx;
        Map<String, Object> s = st.get(idx);
        String type = str(s.get("type"));
        suppressSearch = true;
        if ("url".equals(type)) {
            switchStepTab("url");
            urlField.setText(str(s.get("target")));
            urlName.setText(str(s.get("name")));
        } else if ("delay".equals(type)) {
            switchStepTab("delay");
            Object so = s.get("seconds");
            delaySec.setText(String.valueOf(so instanceof Number ? ((Number) so).intValue() : 3));
        } else {
            switchStepTab("app");
            progSearch.setText(str(s.get("name")));
            progPath.setText(str(s.get("target")));
        }
        suppressSearch = false;
        updateActionBox();
        renderSteps();
    }

    private void cancelEditingStep() {
        editingStep = -1;
        resetStepInputs();
        updateActionBox();
        renderSteps();
    }

    private void requestCancelEditingStep() {
        if (hasUnsavedStepInput()) {
            a.confirm(t("preset_step_unsaved_title"), t("preset_step_cancel_confirm"),
                    // QA U-33: [Cancel] left, [Action] right - as everywhere else
                    new String[]{t("preset_btn_cancel"), t("preset_btn_discard")},
                    new int[]{PcViews.B_SEC, PcViews.B_RED}, choice -> {
                        if (choice == 1) cancelEditingStep();
                    });
            return;
        }
        cancelEditingStep();
    }

    private void putStep(Map<String, Object> step) {
        List<Map<String, Object>> st = steps();
        if (editingStep >= 0 && editingStep < st.size()) {
            st.set(editingStep, step);
            cancelEditingStep();
        } else {
            st.add(step);
            resetStepInputs();
            renderSteps();
        }
    }

    private boolean addAppStep() {
        if (editing == null) return false;
        String n = progSearch.getText().toString().trim(), p = progPath.getText().toString().trim();
        String target = !p.isEmpty() ? p : n;
        if (target.isEmpty()) {
            a.alert(t("preset_alert_app_target"), null);
            return false;
        }
        putStep(PcJson.map("type", "app", "name", PcConn.appStepName(n, target), "target", target));
        return true;
    }

    private boolean addUrlStep() {
        if (editing == null) return false;
        String target = PcConn.normalizeStepUrl(urlField.getText().toString());
        if (target.isEmpty()) {
            a.alert(t("preset_alert_url_target"), null);
            return false;
        }
        putStep(PcJson.map("type", "url", "name", PcConn.urlStepName(urlName.getText().toString(), target), "target", target));
        return true;
    }

    private boolean addDelayStep() {
        if (editing == null) return false;
        int sec = PcConn.clampDelay(delaySec.getText().toString());
        Map<String, Object> s = PcJson.map("type", "delay", "name", sec + " " + t("preset_delay_lbl"), "seconds", sec);
        List<Map<String, Object>> st = steps();
        if (editingStep >= 0 && editingStep < st.size()) {
            st.set(editingStep, s);
            cancelEditingStep();
        } else {
            st.add(s);
            renderSteps();
        }
        return true;
    }

    private void runProgramSearch() {
        final String q = progSearch.getText().toString().trim();
        if (q.isEmpty()) return;
        a.api("GET", "/api/programs/search?q=" + PcConn.encodeURIComponent(q) + "&limit=8", null, 8000, r -> {
            if (!r.ok() || !q.equals(progSearch.getText().toString().trim())) return;
            List<PcJson.O> items = r.jsonArray();
            suggestBox.removeAllViews();
            if (items.isEmpty()) {
                TextView e = PcViews.text(c, t("preset_search_none"), 11.5f, PcViews.MUTED, 400);
                e.setPadding(dp(10), dp(8), dp(10), dp(8));
                suggestBox.addView(e);
                suggestBox.setVisibility(View.VISIBLE);
                return;
            }
            PcViews.MaxScroll sc = new PcViews.MaxScroll(c, 160);
            LinearLayout list = PcViews.col(c);
            sc.addView(list);
            for (final PcJson.O it : items) {
                LinearLayout row = PcViews.row(c);
                row.setPadding(dp(10), dp(8), dp(10), dp(8));
                LinearLayout col = PcViews.col(c);
                String disp = it.str("display_name").isEmpty() ? it.str("name") : it.str("display_name");
                col.addView(PcViews.single(PcViews.text(c, disp, 12f, PcViews.TEXT, 600)));
                TextView path = PcViews.single(PcViews.text(c, it.str("path"), 10f, PcViews.SUBTEXT, 400));
                path.setPadding(0, dp(2), 0, 0);
                col.addView(path);
                row.addView(col, PcViews.weight(1));
                TextView type = PcViews.monoText(c, it.str("type"), 10f, PcViews.MUTED);
                type.setPadding(dp(8), 0, 0, 0);
                row.addView(type);
                row.setClickable(true);
                row.setOnClickListener(v -> {
                    suppressSearch = true;
                    progSearch.setText(it.str("name"));
                    progPath.setText(it.str("path"));
                    suppressSearch = false;
                    suggestBox.setVisibility(View.GONE);
                });
                list.addView(row, PcViews.matchWrap());
                View line = new View(c);
                line.setBackgroundColor(0x0AFFFFFF);
                list.addView(line, PcViews.lp(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(1))));
            }
            suggestBox.addView(sc, PcViews.matchWrap());
            suggestBox.setVisibility(View.VISIBLE);
        });
    }

    private void saveEditing(final boolean andClose, final Runnable onSaved) {
        if (editing == null) return;
        String name = nameField.getText().toString().trim();
        if (name.isEmpty()) {
            a.alert(t("preset_alert_empty_name"), () -> nameField.requestFocus());
            return;
        }
        editing.put("name", name);
        if (hasUnsavedStepInput()) savePendingStep();
        if (steps().isEmpty()) {
            a.alert(t("preset_alert_no_steps"), () -> progSearch.requestFocus());
            return;
        }
        a.api("POST", "/api/presets/save", editing, 10000, r -> {
            if (r.ok()) {
                if (r.json().has("id") && str(editing.get("id")).isEmpty()) editing.put("id", r.json().str("id"));
                snapshot = snapshotOf();
                if (andClose) {
                    doBackToList();
                    load();
                }
                if (onSaved != null) onSaved.run();
            } else if (r.error != null) {
                a.alert(t("msg_server_unreachable"), null);
            } else if (!r.unauthorized()) {
                a.alert(r.message().isEmpty() ? t("preset_err_save") : r.message(), null);
            }
        });
    }

    private void confirmDelete(final String id, String name) {
        a.confirm(t("preset_del_title"), t("preset_del_desc", "name", name),
                new String[]{t("preset_btn_cancel"), t("preset_btn_delete")}, // QA U-33
                new int[]{PcViews.B_SEC, PcViews.B_RED_DARK}, choice -> {
                    if (choice != 1) return;
                    a.api("POST", "/api/presets/delete", PcJson.map("id", id), 8000, r -> {
                        if (r.ok()) {
                            snapshot = null;
                            editing = null;
                            doBackToList();
                            load();
                        } else if (!r.message().isEmpty()) {
                            a.status(r.message());
                        }
                    });
                });
    }
}
