package com.pccontrol.remote;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.os.Build;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

/**
 * Native UI kit of the player, built 1:1 on the design tokens of the PC Control app
 * (assets/css/styles.css :root, .card, button, .seg-group/.seg-btn, .settings-modal,
 * .lang-opt-card, .safe-range, .btn-ytm-red, .danger-soft, button.active).
 */
final class PcUi {
    private PcUi() {}

    // ---- colours = styles.css :root ----
    static final int BG = 0xFF030303;
    static final int SURFACE = 0xFF121212;
    static final int SURFACE2 = 0xFF1D1D1D;
    static final int SURFACE3 = 0xFF282828;
    static final int BORDER = 0x12FFFFFF;          // rgba(255,255,255,0.07)
    static final int BORDER_STRONG = 0x21FFFFFF;   // rgba(255,255,255,0.13)
    static final int TEXT = 0xFFFFFFFF;
    static final int SUBTEXT = 0xFFAAAAAA;
    static final int MUTED = 0xFF717171;
    static final int RED = 0xFFFF0033;             // --ytm-red (primary accent)
    static final int RED_SOFT = 0x26FF0033;        // rgba(255,0,51,0.15) (settings-modal-icon)
    static final int RED_SELECTED = 0x1FFF0033;    // rgba(255,0,51,0.12) (.lang-opt-card.active)
    static final int DANGER = 0xFFFF453A;
    static final int DANGER_BG = 0x21FF453A;       // rgba(255,69,58,0.13)
    static final int DANGER_BORDER = 0x2EFF453A;   // rgba(255,69,58,0.18)
    static final int ACTIVE_BG = 0x2EFFFFFF;       // button.active rgba(255,255,255,0.18)
    static final int ACTIVE_BORDER = 0x80FFFFFF;   // rgba(255,255,255,0.5)
    static final int PC_ACCENT = 0xFF38BDF8;       // button.btn-pc-control

    // Floating controls over the video: same surfaces, slightly translucent
    static final int FLOAT_BG = 0xE0121212;
    static final int FLOAT_ACTIVE_BG = 0xE6404040;  // white 18% over surface
    static final int FLOAT_ERROR_BG = 0xE6321A19;   // danger-bg over surface

    // ---- button states ----
    static final int ST_NORMAL = 0;
    static final int ST_ACTIVE = 1;
    static final int ST_ERROR = 2;
    static final int ST_PRIMARY = 3;
    static final int ST_DANGER = 4;
    static final int ST_FLOATING = 5;

    private static Typeface medium;

    static Typeface medium() {
        if (medium == null) medium = Typeface.create("sans-serif-medium", Typeface.NORMAL);
        return medium;
    }

    static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    static GradientDrawable shape(int fill, float radiusPx, int stroke, int strokePx) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(radiusPx);
        if (strokePx > 0) g.setStroke(strokePx, stroke);
        return g;
    }

    static GradientDrawable oval(int fill, int stroke, int strokePx) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(fill);
        if (strokePx > 0) g.setStroke(strokePx, stroke);
        return g;
    }

    /** button:active{transform:scale(0.97)} — applied without consuming the touch. */
    static void pressFeedback(View v, MotionEvent ev) {
        switch (ev.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                v.animate().scaleX(0.94f).scaleY(0.94f).setDuration(90)
                        .setInterpolator(new DecelerateInterpolator()).start();
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                v.animate().scaleX(1f).scaleY(1f).setDuration(140)
                        .setInterpolator(new DecelerateInterpolator()).start();
                break;
            default:
                break;
        }
    }

    static void pressable(View v) {
        v.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View view, MotionEvent ev) {
                pressFeedback(view, ev);
                return false;
            }
        });
    }

    static TextView text(Context c, String s, float sp, int color, Typeface tf) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (tf != null) t.setTypeface(tf);
        t.setIncludeFontPadding(false);
        return t;
    }

    /** .card-title: uppercase 11.5px, 600, letter-spacing .06em, muted. */
    static TextView sectionTitle(Context c, String s) {
        TextView t = text(c, s.toUpperCase(), 11.5f, MUTED, medium());
        t.setLetterSpacing(0.06f);
        t.setPadding(dp(c, 2), dp(c, 14), 0, dp(c, 8));
        return t;
    }

    static View divider(Context c) {
        View d = new View(c);
        d.setBackgroundColor(BORDER);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(c, 1)));
        lp.setMargins(0, dp(c, 12), 0, dp(c, 4));
        d.setLayoutParams(lp);
        return d;
    }

    // ------------------------------------------------------------------ icon button
    /** Round (floating) or rounded-square (toolbar) icon button. */
    static final class IconBtn extends ImageView {
        final PcIconDrawable icon;
        final boolean round;
        final int sizePx;
        private int state = -1;
        private int tint = TEXT;

        /** User-chosen icon colour (normal/active/floating states; errors stay red). */
        void setTint(int color) {
            if (tint == color) return;
            tint = color;
            int st = state;
            state = -1;
            setState(st);
        }

        int getState() {
            return state;
        }

        IconBtn(Context c, String[] iconData, int sizeDp, int iconDp, boolean round, String description) {
            super(c);
            this.round = round;
            this.sizePx = dp(c, sizeDp);
            icon = new PcIconDrawable(iconData, TEXT, dp(c, iconDp));
            setImageDrawable(icon);
            setScaleType(ScaleType.CENTER);
            setLayoutParams(new LinearLayout.LayoutParams(sizePx, sizePx));
            setContentDescription(description);
            setClickable(true);
            setFocusable(true);
            pressable(this);
            setState(round ? ST_FLOATING : ST_NORMAL);
        }

        void setState(int st) {
            if (st == state) return;
            state = st;
            Context c = getContext();
            float r = round ? sizePx / 2f : dp(c, 12);
            int stroke = dp(c, 1);
            switch (st) {
                case ST_ACTIVE:
                    setBackground(shape(round ? FLOAT_ACTIVE_BG : ACTIVE_BG, r, ACTIVE_BORDER, stroke));
                    icon.setColor(tint);
                    break;
                case ST_ERROR:
                case ST_DANGER:
                    setBackground(shape(round ? FLOAT_ERROR_BG : DANGER_BG, r, DANGER_BORDER, stroke));
                    icon.setColor(DANGER);
                    break;
                case ST_PRIMARY:
                    setBackground(shape(RED, r, 0, 0));
                    icon.setColor(TEXT);
                    break;
                case ST_FLOATING:
                    setBackground(shape(FLOAT_BG, r, BORDER_STRONG, stroke));
                    icon.setColor(tint);
                    break;
                default:
                    setBackground(shape(SURFACE2, r, BORDER, stroke));
                    icon.setColor(tint);
                    break;
            }
        }

        void setIcon(String[] data) {
            PcIconDrawable d = new PcIconDrawable(data, icon.getColor(), icon.getIntrinsicWidth());
            setImageDrawable(d);
        }
    }

    // ------------------------------------------------------------------ text button
    /** `button` of the app: icon + label, 13.5sp medium, radius 12, surface2. */
    static final class Btn extends LinearLayout {
        final ImageView iconView;
        final PcIconDrawable icon;
        final TextView label;
        private int state = -1;

        Btn(Context c, String[] iconData, String text, boolean alignStart) {
            super(c);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL | (alignStart ? Gravity.START : Gravity.CENTER_HORIZONTAL));
            setMinimumHeight(dp(c, 44));
            setPadding(dp(c, 14), dp(c, 10), dp(c, 14), dp(c, 10));
            if (iconData != null) {
                icon = new PcIconDrawable(iconData, TEXT, dp(c, 18));
                iconView = new ImageView(c);
                iconView.setImageDrawable(icon);
                addView(iconView, new LayoutParams(dp(c, 18), dp(c, 18)));
            } else {
                icon = null;
                iconView = null;
            }
            label = text(c, text, 13.5f, TEXT, medium());
            label.setSingleLine(true);
            label.setEllipsize(TextUtils.TruncateAt.END);
            LayoutParams lp = new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            if (iconData != null) lp.leftMargin = dp(c, 8);
            addView(label, lp);
            setClickable(true);
            setFocusable(true);
            pressable(this);
            setState(ST_NORMAL);
        }

        void setState(int st) {
            if (st == state) return;
            state = st;
            Context c = getContext();
            float r = dp(c, 12);
            int s1 = dp(c, 1);
            int fg = TEXT;
            switch (st) {
                case ST_ACTIVE:
                    setBackground(shape(ACTIVE_BG, r, ACTIVE_BORDER, s1));
                    break;
                case ST_ERROR:
                case ST_DANGER:
                    setBackground(shape(DANGER_BG, r, DANGER_BORDER, s1));
                    fg = DANGER;
                    break;
                case ST_PRIMARY:
                    setBackground(shape(RED, r, 0, 0));
                    label.setTypeface(Typeface.DEFAULT_BOLD);
                    break;
                default:
                    setBackground(shape(SURFACE2, r, BORDER, s1));
                    break;
            }
            label.setTextColor(fg);
            if (icon != null) icon.setColor(fg);
        }

        void setText(String s) {
            label.setText(s);
        }
    }

    // ------------------------------------------------------------------ segmented control
    interface SegListener {
        void onSelect(int index);
    }

    /** .seg-group / .seg-btn: surface2 pill group, active option white with dark text. */
    static final class Seg extends LinearLayout {
        private final TextView[] items;
        private int selected;
        private final SegListener listener;

        Seg(Context c, String[] labels, int selectedIndex, SegListener l) {
            super(c);
            this.listener = l;
            setOrientation(HORIZONTAL);
            int p = dp(c, 3);
            setPadding(p, p, p, p);
            setBackground(shape(SURFACE2, dp(c, 10), BORDER, dp(c, 1)));
            items = new TextView[labels.length];
            for (int i = 0; i < labels.length; i++) {
                final int idx = i;
                TextView t = text(c, labels[i], 12f, SUBTEXT, medium());
                t.setGravity(Gravity.CENTER);
                t.setSingleLine(true);
                t.setEllipsize(TextUtils.TruncateAt.END);
                t.setPadding(dp(c, 6), dp(c, 9), dp(c, 6), dp(c, 9));
                t.setMinHeight(dp(c, 36));
                t.setClickable(true);
                t.setOnClickListener(new OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        select(idx, true);
                    }
                });
                LayoutParams lp = new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
                if (i > 0) lp.leftMargin = p;
                addView(t, lp);
                items[i] = t;
            }
            select(selectedIndex, false);
        }

        void select(int idx, boolean notify) {
            selected = idx;
            Context c = getContext();
            for (int i = 0; i < items.length; i++) {
                boolean on = i == idx;
                items[i].setBackground(on ? shape(TEXT, dp(c, 7), 0, 0) : null);
                items[i].setTextColor(on ? BG : SUBTEXT);
            }
            if (notify && listener != null) listener.onSelect(idx);
        }

        int getSelected() {
            return selected;
        }
    }

    // ------------------------------------------------------------------ slider
    interface SliderListener {
        void onValue(int value);
    }

    /** .safe-range: 4dp track rgba(255,255,255,.16), white 16dp thumb; progress in --ytm-red. */
    static SeekBar slider(Context c, final int min, int max, int current, final SliderListener l) {
        SeekBar sb = new SeekBar(c);
        sb.setMax(max - min);
        sb.setProgress(Math.max(0, Math.min(max - min, current - min)));
        GradientDrawable track = shape(0x29FFFFFF, dp(c, 2), 0, 0);
        GradientDrawable fill = shape(RED, dp(c, 2), 0, 0);
        LayerDrawable layers = new LayerDrawable(new Drawable[]{track, new ClipDrawable(fill, Gravity.START, ClipDrawable.HORIZONTAL)});
        layers.setId(0, android.R.id.background);
        layers.setId(1, android.R.id.progress);
        sb.setProgressDrawable(layers);
        GradientDrawable thumb = oval(TEXT, 0x33000000, dp(c, 1));
        thumb.setSize(dp(c, 16), dp(c, 16));
        sb.setThumb(thumb);
        if (Build.VERSION.SDK_INT >= 29) {
            sb.setMinHeight(dp(c, 4));
            sb.setMaxHeight(dp(c, 4));
        }
        sb.setSplitTrack(false);
        int padV = dp(c, 14);
        sb.setPadding(dp(c, 10), padV, dp(c, 10), padV);
        sb.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 32)));
        sb.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar s, int progress, boolean fromUser) {
                if (fromUser && l != null) l.onValue(min + progress);
            }

            @Override
            public void onStartTrackingTouch(SeekBar s) {
                s.animate().scaleY(1.06f).setDuration(120).start();
            }

            @Override
            public void onStopTrackingTouch(SeekBar s) {
                s.animate().scaleY(1f).setDuration(120).start();
            }
        });
        return sb;
    }

    // ------------------------------------------------------------------ colour picker
    /** Palette for user-tinted elements: white, app red, PC-control sky, ok green, amber, violet, pink. */
    static final int[] TINTS = {0xFFFFFFFF, RED, PC_ACCENT, 0xFF2BA640, 0xFFFFB300, 0xFFA855F7, 0xFFFF4FA3};
    static final String[] TINT_NAMES = {"Белый", "Красный", "Голубой", "Зелёный", "Янтарный", "Фиолетовый", "Розовый"};

    interface ColorListener {
        void onColor(int color);
    }

    /** Row of colour swatches (28dp circles), the selected one gets a white ring. */
    static LinearLayout colorPicker(final Context c, int selected, final ColorListener l) {
        final LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(c, 2), dp(c, 6), 0, dp(c, 2));
        final View[] dots = new View[TINTS.length];
        for (int i = 0; i < TINTS.length; i++) {
            final int color = TINTS[i];
            View dot = new View(c);
            dot.setContentDescription(TINT_NAMES[i]);
            dot.setClickable(true);
            dots[i] = dot;
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(c, 28), dp(c, 28));
            if (i > 0) lp.leftMargin = dp(c, 10);
            row.addView(dot, lp);
            dot.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    paintSwatches(c, dots, color);
                    v.animate().scaleX(1.15f).scaleY(1.15f).setDuration(90).start();
                    v.postDelayed(new Runnable() {
                        @Override
                        public void run() {
                            for (View d : dots) d.animate().scaleX(1f).scaleY(1f).setDuration(120).start();
                        }
                    }, 100);
                    if (l != null) l.onColor(color);
                }
            });
        }
        paintSwatches(c, dots, selected);
        return row;
    }

    private static void paintSwatches(Context c, View[] dots, int selected) {
        for (int i = 0; i < dots.length; i++) {
            boolean on = TINTS[i] == selected;
            dots[i].setBackground(oval(TINTS[i], on ? TEXT : BORDER_STRONG, dp(c, on ? 3 : 1)));
        }
    }

    /** Label (12sp subtext) on the left and its value (mono) on the right. */
    static final class ValueRow extends LinearLayout {
        final TextView value;

        ValueRow(Context c, String label, String val) {
            super(c);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setPadding(dp(c, 2), dp(c, 8), dp(c, 2), 0);
            TextView l = text(c, label, 12.5f, SUBTEXT, medium());
            addView(l, new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            value = text(c, val, 12f, TEXT, Typeface.MONOSPACE);
            addView(value);
        }

        void set(String v) {
            value.setText(v);
        }
    }

    /** .lang-opt-card style navigation row: icon tile, title + subtitle, chevron. */
    static LinearLayout navRow(Context c, String[] iconData, String title, String subtitle, View.OnClickListener click) {
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(c, 12), dp(c, 11), dp(c, 12), dp(c, 11));
        row.setBackground(shape(SURFACE2, dp(c, 14), BORDER, dp(c, 1)));
        ImageView tile = new ImageView(c);
        tile.setImageDrawable(new PcIconDrawable(iconData, TEXT, dp(c, 18)));
        tile.setScaleType(ImageView.ScaleType.CENTER);
        tile.setBackground(shape(SURFACE3, dp(c, 8), 0, 0));
        row.addView(tile, new LinearLayout.LayoutParams(dp(c, 32), dp(c, 32)));

        LinearLayout names = new LinearLayout(c);
        names.setOrientation(LinearLayout.VERTICAL);
        names.setPadding(dp(c, 12), 0, dp(c, 8), 0);
        TextView t = text(c, title, 14f, TEXT, medium());
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        names.addView(t);
        if (subtitle != null) {
            TextView st = text(c, subtitle, 11f, SUBTEXT, null);
            st.setPadding(0, dp(c, 3), 0, 0);
            st.setSingleLine(true);
            st.setEllipsize(TextUtils.TruncateAt.END);
            names.addView(st);
        }
        row.addView(names, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        ImageView chev = new ImageView(c);
        chev.setImageDrawable(new PcIconDrawable(PcIcons.CHEVRON_RIGHT, MUTED, dp(c, 16)));
        row.addView(chev, new LinearLayout.LayoutParams(dp(c, 16), dp(c, 16)));

        row.setClickable(true);
        row.setFocusable(true);
        row.setOnClickListener(click);
        pressable(row);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(c, 8);
        row.setLayoutParams(lp);
        return row;
    }
}
