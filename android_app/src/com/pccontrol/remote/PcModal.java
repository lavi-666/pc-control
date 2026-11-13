package com.pccontrol.remote;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * Modal window = .conn-modal-backdrop + .conn-modal / .settings-modal (or .custom-modal-box):
 * dimmed backdrop, centred box (max width, 90% height, scrollable), pop-in animation.
 * Lives inside the activity's root FrameLayout so the back button and the design stay ours.
 */
class PcModal extends FrameLayout {
    static final int KIND_SETTINGS = 0;
    static final int KIND_CONFIRM = 1;

    final ScrollView box;
    final LinearLayout content;
    private final int maxWidthPx;
    private final int marginPx;
    boolean dismissOnBackdrop = true;
    Runnable onBackRequest;     // back / backdrop tap; default = dismiss
    Runnable onDismissed;
    private boolean dismissing;

    PcModal(Context c, int kind, float maxWidthDp) {
        super(c);
        marginPx = PcViews.dp(c, 16);
        maxWidthPx = PcViews.dp(c, maxWidthDp);
        setBackgroundColor(kind == KIND_CONFIRM ? 0xB8000000 : 0xC2000000);
        setClickable(true);
        box = new ScrollView(c) {
            @Override
            protected void onMeasure(int wSpec, int hSpec) {
                super.onMeasure(wSpec, hSpec);
            }
        };
        box.setFillViewport(false);
        box.setVerticalScrollBarEnabled(false);
        box.setOverScrollMode(OVER_SCROLL_NEVER);
        content = PcViews.col(c);
        if (kind == KIND_CONFIRM) {
            box.setBackground(PcViews.gradient(c, GradientDrawable.Orientation.TL_BR,
                    new int[]{0xFF221C1E, 0xFF171717, 0xFF121212}, new float[]{0f, 0.65f, 1f}, 18, 0x2EFFFFFF, 1));
            content.setPadding(PcViews.dp(c, 18), PcViews.dp(c, 20), PcViews.dp(c, 18), PcViews.dp(c, 18));
        } else {
            box.setBackground(PcViews.rect(c, 0xFF121212, 22, PcViews.BORDER_STRONG, 1));
            int p = PcViews.dp(c, 18);
            content.setPadding(p, p, p, p);
        }
        box.setClipToOutline(true);
        box.setElevation(PcViews.dp(c, 24));
        box.addView(content, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        addView(box, new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (dismissOnBackdrop) requestBack();
            }
        });
    }

    @Override
    protected void onMeasure(int wSpec, int hSpec) {
        int w = MeasureSpec.getSize(wSpec), h = MeasureSpec.getSize(hSpec);
        int bw = Math.min(maxWidthPx, w - 2 * marginPx);
        int bh = Math.max(0, Math.min((int) (h * 0.9f), h - 2 * marginPx));
        box.measure(MeasureSpec.makeMeasureSpec(Math.max(0, bw), MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(bh, MeasureSpec.AT_MOST));
        setMeasuredDimension(w, h);
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int w = r - l, h = b - t;
        int bw = box.getMeasuredWidth(), bh = box.getMeasuredHeight();
        int x = (w - bw) / 2, y = (h - bh) / 2;
        box.layout(x, y, x + bw, y + bh);
    }

    @Override
    public boolean onInterceptTouchEvent(MotionEvent ev) {
        return false;
    }

    void requestBack() {
        if (onBackRequest != null) onBackRequest.run();
        else dismiss();
    }

    void show(FrameLayout root) {
        if (getParent() != null) return;
        root.addView(this, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setAlpha(0f);
        animate().alpha(1f).setDuration(160).start();
        box.setScaleX(0.92f);
        box.setScaleY(0.92f);
        box.setAlpha(0f);
        box.animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(200)
                .setInterpolator(new PathInterpolator(0.16f, 1f, 0.3f, 1f)).start();
    }

    boolean isShowing() {
        return getParent() != null && !dismissing;
    }

    void dismiss() {
        if (getParent() == null || dismissing) return;
        dismissing = true;
        box.animate().scaleX(0.96f).scaleY(0.96f).alpha(0f).setDuration(130).setInterpolator(new DecelerateInterpolator()).start();
        animate().alpha(0f).setDuration(150).withEndAction(new Runnable() {
            @Override
            public void run() {
                ViewGroup p = (ViewGroup) getParent();
                if (p != null) p.removeView(PcModal.this);
                dismissing = false;
                if (onDismissed != null) onDismissed.run();
            }
        }).start();
    }

    // ------------------------------------------------------------------ header pieces
    /** .settings-modal-header: red icon tile, title (+ optional subtitle), round close button. */
    static LinearLayout header(Context c, String[] icon, String title, String subtitle, final Runnable onClose) {
        LinearLayout h = PcViews.row(c);
        LinearLayout.LayoutParams hp = PcViews.matchWrap();
        hp.bottomMargin = PcViews.dp(c, 14);
        h.setLayoutParams(hp);
        if (icon != null) {
            FrameLayout tile = new FrameLayout(c);
            tile.setBackground(PcViews.rect(c, 0x26FF0033, 8, 0, 0));
            ImageView iv = PcViews.icon(c, icon, PcViews.RED, 17);
            tile.addView(iv, new FrameLayout.LayoutParams(PcViews.dp(c, 17), PcViews.dp(c, 17), Gravity.CENTER));
            LinearLayout.LayoutParams tp = PcViews.lp(PcViews.dp(c, 28), PcViews.dp(c, 28));
            tp.rightMargin = PcViews.dp(c, 8);
            h.addView(tile, tp);
        }
        LinearLayout names = PcViews.col(c);
        TextView t = PcViews.text(c, title, 16f, PcViews.TEXT, 700);
        names.addView(t);
        if (subtitle != null) {
            TextView s = PcViews.text(c, subtitle, 11f, PcViews.SUBTEXT, 400);
            s.setPadding(0, PcViews.dp(c, 2), 0, 0);
            names.addView(s);
        }
        h.addView(names, PcViews.weight(1));
        h.addView(closeButton(c, onClose));
        return h;
    }

    /** .settings-modal-close: 30px circle, white 8%, X 16px. */
    static FrameLayout closeButton(Context c, final Runnable onClose) {
        FrameLayout b = new FrameLayout(c);
        b.setBackground(PcViews.oval(0x14FFFFFF));
        ImageView iv = PcViews.icon(c, PcAppIcons.CLOSE, 0x99FFFFFF, 16);
        b.addView(iv, new FrameLayout.LayoutParams(PcViews.dp(c, 16), PcViews.dp(c, 16), Gravity.CENTER));
        b.setLayoutParams(PcViews.lp(PcViews.dp(c, 30), PcViews.dp(c, 30)));
        b.setClickable(true);
        PcViews.pressable(b, 0.9f);
        b.setOnClickListener(new OnClickListener() {
            @Override
            public void onClick(View v) {
                if (onClose != null) onClose.run();
            }
        });
        return b;
    }

    /** .settings-tabs (pill bar, active tab red). Returns the tab views. */
    static TextView[] tabs(Context c, LinearLayout parent, String[] labels, String[][] icons, float sp, float padV) {
        LinearLayout bar = PcViews.row(c);
        bar.setBackground(PcViews.rect(c, PcViews.SURFACE2, 12, PcViews.BORDER, 1));
        int p = PcViews.dp(c, 4);
        bar.setPadding(p, p, p, p);
        TextView[] out = new TextView[labels.length];
        for (int i = 0; i < labels.length; i++) {
            TextView t = PcViews.text(c, labels[i], sp, PcViews.MUTED, 600);
            t.setGravity(Gravity.CENTER);
            PcViews.single(t);
            t.setPadding(PcViews.dp(c, 6), PcViews.dp(c, padV), PcViews.dp(c, 6), PcViews.dp(c, padV));
            if (icons != null && icons[i] != null) {
                PcIconDrawable d = new PcIconDrawable(icons[i], PcViews.MUTED, PcViews.dp(c, 13));
                d.setBounds(0, 0, PcViews.dp(c, 13), PcViews.dp(c, 13));
                t.setCompoundDrawables(d, null, null, null);
                t.setCompoundDrawablePadding(PcViews.dp(c, 5));
            }
            t.setClickable(true);
            LinearLayout.LayoutParams lp = PcViews.weight(1);
            if (i > 0) lp.leftMargin = PcViews.dp(c, 6);
            bar.addView(t, lp);
            out[i] = t;
        }
        parent.addView(bar, PcViews.matchWrap());
        return out;
    }

    static void selectTab(Context c, TextView[] tabs, int idx) {
        for (int i = 0; i < tabs.length; i++) {
            boolean on = i == idx;
            tabs[i].setBackground(on ? PcViews.rect(c, PcViews.RED, 8, 0, 0) : null);
            if (on) tabs[i].setElevation(PcViews.dp(c, 2));
            else tabs[i].setElevation(0);
            tabs[i].setTextColor(on ? PcViews.TEXT : PcViews.MUTED);
            android.graphics.drawable.Drawable[] ds = tabs[i].getCompoundDrawables();
            if (ds[0] instanceof PcIconDrawable) ((PcIconDrawable) ds[0]).setColor(on ? PcViews.TEXT : PcViews.MUTED);
        }
    }

    /** .settings-field-label. */
    static TextView label(Context c, String s) {
        TextView t = PcViews.text(c, s, 11.5f, PcViews.SUBTEXT, 400);
        LinearLayout.LayoutParams p = PcViews.matchWrap();
        p.bottomMargin = PcViews.dp(c, 5);
        t.setLayoutParams(p);
        return t;
    }
}
