package com.pccontrol.remote;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RadialGradient;
import android.graphics.Rect;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.text.InputType;
import android.text.TextUtils;
import android.text.method.PasswordTransformationMethod;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * UI kit of the native app: the components of web/css/styles.css rebuilt with framework views
 * (cards, buttons and their variants, touch-safe sliders, segmented groups, fields with
 * show/copy buttons, grids, modals). px of the web UI = dp, font px = sp.
 */
final class PcViews {
    private PcViews() {}

    // ---- :root tokens ----
    static final int BG = 0xFF030303;
    static final int SURFACE = 0xFF121212;
    static final int SURFACE2 = 0xFF1D1D1D;
    static final int SURFACE3 = 0xFF282828;
    static final int BORDER = 0x12FFFFFF;          // rgba(255,255,255,.07)
    static final int BORDER_STRONG = 0x21FFFFFF;   // rgba(255,255,255,.13)
    static final int TEXT = 0xFFFFFFFF;
    static final int SUBTEXT = 0xFFAAAAAA;
    static final int MUTED = 0xFF717171;
    static final int RED = 0xFFFF0033;
    static final int DANGER = 0xFFFF453A;
    static final int DANGER_BG = 0x21FF453A;
    static final int OK = 0xFF2BA640;
    static final int PINK = 0xFFFF4E6B;            // active queue item
    static final int PRESET_RED = 0xFFFF3355;
    static final int BLUE = 0xFF60A5FA;
    static final int GREEN = 0xFF22C55E;
    static final int GREEN_TEXT = 0xFF4ADE80;

    static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    private static Typeface medium, mono;

    /** font-weight → Roboto face (500 = medium, 600+ = bold, as Chrome renders Roboto). */
    static Typeface face(int weight) {
        if (weight >= 600) return Typeface.DEFAULT_BOLD;
        if (weight >= 500) {
            if (medium == null) medium = Typeface.create("sans-serif-medium", Typeface.NORMAL);
            return medium;
        }
        return Typeface.DEFAULT;
    }

    static Typeface mono() {
        if (mono == null) mono = Typeface.MONOSPACE;
        return mono;
    }

    static TextView text(Context c, CharSequence s, float sp, int color, int weight) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setTypeface(face(weight));
        t.setIncludeFontPadding(false);
        t.setLineSpacing(0, 1.15f);
        return t;
    }

    static TextView monoText(Context c, CharSequence s, float sp, int color) {
        TextView t = text(c, s, sp, color, 400);
        t.setTypeface(mono());
        return t;
    }

    static TextView single(TextView t) {
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        return t;
    }

    static GradientDrawable rect(Context c, int fill, float radiusDp, int stroke, float strokeDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, radiusDp));
        if (strokeDp > 0) g.setStroke(Math.max(1, dp(c, strokeDp)), stroke);
        return g;
    }

    static GradientDrawable pill(Context c, int fill, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, 999));
        if (stroke != 0) g.setStroke(Math.max(1, dp(c, 1)), stroke);
        return g;
    }

    static GradientDrawable oval(int fill) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(fill);
        return g;
    }

    /** linear-gradient(…) with optional stops (API 29+ honours them; older use even spacing). */
    static GradientDrawable gradient(Context c, GradientDrawable.Orientation o, int[] colors, float[] stops,
                                     float radiusDp, int stroke, float strokeDp) {
        GradientDrawable g = new GradientDrawable(o, colors);
        if (stops != null && Build.VERSION.SDK_INT >= 29) g.setColors(colors, stops);
        g.setCornerRadius(dp(c, radiusDp));
        if (strokeDp > 0) g.setStroke(Math.max(1, dp(c, strokeDp)), stroke);
        return g;
    }

    /** button:active{transform:scale(.97)} without consuming the touch. */
    static void pressable(View v, final float scale) {
        v.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View view, MotionEvent ev) {
                switch (ev.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        view.animate().scaleX(scale).scaleY(scale).setDuration(100)
                                .setInterpolator(new DecelerateInterpolator()).start();
                        break;
                    case MotionEvent.ACTION_UP:
                    case MotionEvent.ACTION_CANCEL:
                        view.animate().scaleX(1f).scaleY(1f).setDuration(140)
                                .setInterpolator(new DecelerateInterpolator()).start();
                        break;
                    default:
                        break;
                }
                return false;
            }
        });
    }

    static void pressable(View v) {
        pressable(v, 0.97f);
    }

    static LinearLayout.LayoutParams lp(int w, int h) {
        return new LinearLayout.LayoutParams(w, h);
    }

    static LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    static LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    static LinearLayout.LayoutParams weight(float w) {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, w);
    }

    static LinearLayout.LayoutParams top(LinearLayout.LayoutParams p, Context c, float topDp) {
        p.topMargin = dp(c, topDp);
        return p;
    }

    static LinearLayout col(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        return l;
    }

    static View space(Context c) {
        return new View(c);
    }

    static ImageView icon(Context c, String[] data, int color, float sizeDp) {
        ImageView iv = new ImageView(c);
        iv.setImageDrawable(new PcIconDrawable(data, color, dp(c, sizeDp)));
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        iv.setLayoutParams(lp(dp(c, sizeDp), dp(c, sizeDp)));
        return iv;
    }

    static void setIcon(ImageView iv, String[] data, int color) {
        Drawable d = iv.getDrawable();
        int size = d != null ? d.getIntrinsicWidth() : 0;
        iv.setImageDrawable(new PcIconDrawable(data, color, size));
    }

    static void tintIcon(ImageView iv, int color) {
        Drawable d = iv.getDrawable();
        if (d instanceof PcIconDrawable) ((PcIconDrawable) d).setColor(color);
    }

    /** body background: radial red glow at 50% -10% (55% radius) over #030303. */
    static final class BodyBackground extends Drawable {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        @Override
        protected void onBoundsChange(Rect b) {
            float cx = b.width() / 2f, cy = -0.1f * b.height();
            // farthest-corner radius of the CSS circle, 55% stop
            float far = (float) Math.hypot(Math.max(cx, b.width() - cx), b.height() - cy);
            float r = Math.max(1f, far * 0.55f);
            paint.setShader(new RadialGradient(cx, cy, r, 0x14FF0033, 0x00030303, Shader.TileMode.CLAMP));
        }

        @Override
        public void draw(Canvas canvas) {
            canvas.drawColor(BG);
            canvas.drawRect(getBounds(), paint);
        }

        @Override public void setAlpha(int alpha) {}
        @Override public void setColorFilter(ColorFilter cf) {}
        @Override public int getOpacity() { return PixelFormat.OPAQUE; }
    }

    // ------------------------------------------------------------------ cards
    /** .card: surface, 1px border, radius 18, padding 16. */
    static LinearLayout card(Context c) {
        LinearLayout l = col(c);
        l.setBackground(rect(c, SURFACE, 18, BORDER, 1));
        int p = dp(c, 16);
        l.setPadding(p, p, p, p);
        return l;
    }

    /** .card-title. */
    static TextView cardTitle(Context c, String s) {
        TextView t = text(c, s.toUpperCase(), 11.5f, MUTED, 600);
        t.setLetterSpacing(0.06f);
        LinearLayout.LayoutParams p = matchWrap();
        p.leftMargin = dp(c, 2);
        p.bottomMargin = dp(c, 12);
        t.setLayoutParams(p);
        return t;
    }

    /** border-top separator used by drawers / panels. */
    static View hr(Context c) {
        View v = new View(c);
        v.setBackgroundColor(BORDER);
        v.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(c, 1))));
        return v;
    }

    // ------------------------------------------------------------------ buttons
    static final int B_DEFAULT = 0, B_PILL = 1, B_ACTIVE = 2, B_DANGER = 3, B_RED = 4, B_PC = 5, B_PC_ACTIVE = 6,
            B_BG = 7, B_BG_ACTIVE = 8, B_WOL = 9, B_SEC = 10, B_PRESETS = 11, B_GHOST = 12, B_RUNNING = 13,
            B_CANCELLING = 14, B_RED_DARK = 15;

    /** `button` of styles.css: icon + label (+ optional leading dot), centred, radius 12. */
    static final class Btn extends LinearLayout {
        final TextView label;
        ImageView iconView;
        View dot;
        private int style = -1;
        private float radiusDp = 12;
        private ValueAnimator dotPulse;

        Btn(Context c, String[] icon, CharSequence text) {
            this(c, icon, text, 17);
        }

        Btn(Context c, String[] icon, CharSequence text, float iconDp) {
            super(c);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER);
            setPadding(dp(c, 14), dp(c, 11), dp(c, 14), dp(c, 11));
            setMinimumHeight(dp(c, 42));
            if (icon != null) {
                iconView = PcViews.icon(c, icon, TEXT, iconDp);
                addView(iconView);
            }
            label = text(c, text, 13.5f, TEXT, 500);
            label.setGravity(Gravity.CENTER);
            single(label);
            LayoutParams p = wrap();
            if (icon != null) p.leftMargin = dp(c, 8);
            if (text == null || text.length() == 0) label.setVisibility(GONE);
            addView(label, p);
            setClickable(true);
            setFocusable(true);
            pressable(this);
            setStyle(B_DEFAULT);
        }

        Btn radius(float r) {
            radiusDp = r;
            int s = style;
            style = -1;
            setStyle(s);
            return this;
        }

        Btn pad(float h, float v) {
            Context c = getContext();
            setPadding(dp(c, h), dp(c, v), dp(c, h), dp(c, v));
            setMinimumHeight(0);
            return this;
        }

        Btn size(float sp) {
            label.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
            return this;
        }

        Btn start() {
            setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
            return this;
        }

        /** .bg-mode-indicator (9px dot before the icon). */
        Btn withDot() {
            Context c = getContext();
            dot = new View(c);
            dot.setBackground(oval(0xFF666666));
            LayoutParams p = lp(dp(c, 9), dp(c, 9));
            p.rightMargin = dp(c, 8);
            addView(dot, 0, p);
            return this;
        }

        void setText(CharSequence s) {
            label.setText(s);
            label.setVisibility(s == null || s.length() == 0 ? GONE : VISIBLE);
        }

        void setIcon(String[] data) {
            if (iconView != null) PcViews.setIcon(iconView, data, label.getCurrentTextColor());
        }

        int style() {
            return style;
        }

        void setStyle(int st) {
            if (st == style) return;
            style = st;
            Context c = getContext();
            int fg = TEXT;
            int weight = 500;
            float r = radiusDp;
            switch (st) {
                case B_PILL:
                    setBackground(rect(c, TEXT, r, 0, 0));
                    fg = BG;
                    weight = 600;
                    break;
                case B_ACTIVE:
                    setBackground(rect(c, 0x2EFFFFFF, r, 0x80FFFFFF, 1));
                    break;
                case B_DANGER:
                    setBackground(rect(c, DANGER_BG, r, 0x2EFF453A, 1));
                    fg = DANGER;
                    break;
                case B_RED:
                    setBackground(rect(c, RED, r, 0, 0));
                    weight = 600;
                    break;
                case B_RED_DARK:
                    setBackground(rect(c, 0xFFDC2626, r, 0xFFEF4444, 1));
                    weight = 600;
                    break;
                case B_PC:
                    setBackground(gradient(c, GradientDrawable.Orientation.TL_BR,
                            new int[]{0x1438BDF8, SURFACE2}, null, r, 0x3D38BDF8, 1));
                    break;
                case B_PC_ACTIVE:
                    setBackground(rect(c, 0x2E38BDF8, r, 0xFF38BDF8, 1));
                    break;
                case B_BG:
                    setBackground(rect(c, SURFACE2, r, 0x24FFFFFF, 1));
                    break;
                case B_BG_ACTIVE:
                    setBackground(gradient(c, GradientDrawable.Orientation.TL_BR,
                            new int[]{0x2E00E676, 0x0F00E676}, null, r, 0xFF00E676, 1));
                    fg = 0xFF00E676;
                    weight = 600;
                    break;
                case B_WOL:
                    setBackground(gradient(c, GradientDrawable.Orientation.TL_BR,
                            new int[]{0x2E22C55E, 0x1410B981}, null, 14, 0x7322C55E, 1));
                    fg = GREEN_TEXT;
                    weight = 600;
                    break;
                case B_SEC:
                    setBackground(rect(c, SURFACE2, r, BORDER, 1));
                    weight = 600;
                    break;
                case B_PRESETS:
                    setBackground(rect(c, 0x14FF0033, r, 0x59FF0033, 1));
                    break;
                case B_GHOST:
                    setBackground(null);
                    break;
                case B_RUNNING:
                    setBackground(rect(c, 0xFF15803D, r, 0xFF22C55E, 1));
                    weight = 600;
                    break;
                case B_CANCELLING:
                    setBackground(rect(c, 0xFFB91C1C, r, 0xFFEF4444, 1));
                    weight = 600;
                    break;
                default:
                    setBackground(rect(c, SURFACE2, r, 0x00000000, 1));
                    break;
            }
            label.setTextColor(fg);
            label.setTypeface(face(weight));
            if (iconView != null) tintIcon(iconView, fg);
            if (dot != null) {
                boolean on = st == B_BG_ACTIVE;
                dot.setBackground(oval(on ? 0xFF00E676 : 0xFF666666));
                if (on) startPulse();
                else stopPulse();
            }
        }

        /** @keyframes bgPulse: opacity 1→.4, scale 1→1.35, 2s. */
        private void startPulse() {
            if (dotPulse != null) return;
            dotPulse = ValueAnimator.ofFloat(0f, 1f);
            dotPulse.setDuration(2000);
            dotPulse.setRepeatCount(ValueAnimator.INFINITE);
            dotPulse.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator a) {
                    float f = (float) a.getAnimatedValue();
                    float k = (float) (0.5 - 0.5 * Math.cos(f * 2 * Math.PI)); // 0→1→0
                    dot.setAlpha(1f - 0.6f * k);
                    dot.setScaleX(1f + 0.35f * k);
                    dot.setScaleY(1f + 0.35f * k);
                }
            });
            dotPulse.start();
        }

        private void stopPulse() {
            if (dotPulse != null) {
                dotPulse.cancel();
                dotPulse = null;
            }
            if (dot != null) {
                dot.setAlpha(1f);
                dot.setScaleX(1f);
                dot.setScaleY(1f);
            }
        }

        @Override
        protected void onDetachedFromWindow() {
            super.onDetachedFromWindow();
            stopPulse();
        }

        @Override
        protected void onAttachedToWindow() {
            super.onAttachedToWindow();
            if (style == B_BG_ACTIVE && dot != null) startPulse();
        }
    }

    /** Round transparent icon button (.ytm-icon-btn 40px / .ytm-vol-btn 32px). */
    static final class RoundIcon extends FrameLayout {
        final ImageView iv;
        private final View markDot;
        private boolean modeActive;

        RoundIcon(Context c, String[] data, float sizeDp, float iconDp, int color) {
            super(c);
            iv = icon(c, data, color, iconDp);
            LayoutParams p = new LayoutParams(dp(c, iconDp), dp(c, iconDp), Gravity.CENTER);
            addView(iv, p);
            markDot = new View(c);
            markDot.setBackground(oval(RED));
            markDot.setVisibility(GONE);
            LayoutParams dp = new LayoutParams(PcViews.dp(c, 4), PcViews.dp(c, 4), Gravity.CENTER_HORIZONTAL | Gravity.BOTTOM);
            dp.bottomMargin = PcViews.dp(c, 5);
            addView(markDot, dp);
            setLayoutParams(new LinearLayout.LayoutParams(PcViews.dp(c, sizeDp), PcViews.dp(c, sizeDp)));
            setClickable(true);
            setFocusable(true);
            pressable(this, 0.9f);
        }

        void setIcon(String[] data, int color) {
            PcViews.setIcon(iv, data, color);
        }

        void setColor(int color) {
            tintIcon(iv, color);
        }

        /** .ytm-icon-btn.mode-active: white 12% disc + red dot. */
        void setModeActive(boolean on) {
            modeActive = on;
            setBackground(on ? oval(0x1FFFFFFF) : null);
            markDot.setVisibility(on ? VISIBLE : GONE);
        }

        /** Same disc without the dot (history button active). */
        void setHighlighted(boolean on) {
            setBackground(on ? oval(0x1FFFFFFF) : null);
            if (!modeActive) markDot.setVisibility(on ? VISIBLE : GONE);
        }
    }

    // ------------------------------------------------------------------ grid / flow
    /** CSS grid: fixed column count, or auto-fill with a minimum column width; children stretch. */
    static class Grid extends ViewGroup {
        private final int fixedCols;
        private final int minColPx;
        private final int gap;

        Grid(Context c, int fixedCols, float minColDp, float gapDp) {
            super(c);
            this.fixedCols = fixedCols;
            this.minColPx = dp(c, minColDp);
            this.gap = dp(c, gapDp);
        }

        private int cols(int width) {
            if (fixedCols > 0) return fixedCols;
            return Math.max(1, (width + gap) / (minColPx + gap));
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            int width = MeasureSpec.getSize(wSpec);
            int inner = width - getPaddingLeft() - getPaddingRight();
            int n = cols(inner);
            int colW = Math.max(0, (inner - gap * (n - 1)) / n);
            int count = 0, rowH = 0, total = 0;
            int visible = 0;
            for (int i = 0; i < getChildCount(); i++) if (getChildAt(i).getVisibility() != GONE) visible++;
            int idx = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                if (ch.getVisibility() == GONE) continue;
                ch.measure(MeasureSpec.makeMeasureSpec(colW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED));
                rowH = Math.max(rowH, ch.getMeasuredHeight());
                count++;
                idx++;
                if (count == n || idx == visible) {
                    total += rowH + (total > 0 ? gap : 0);
                    rowH = 0;
                    count = 0;
                }
            }
            // second pass: stretch to the row height
            count = 0;
            rowH = 0;
            int rowStart = 0;
            idx = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                if (ch.getVisibility() == GONE) continue;
                if (count == 0) rowStart = i;
                rowH = Math.max(rowH, ch.getMeasuredHeight());
                count++;
                idx++;
                if (count == n || idx == visible) {
                    for (int j = rowStart; j <= i; j++) {
                        View s = getChildAt(j);
                        if (s.getVisibility() == GONE) continue;
                        if (s.getMeasuredHeight() != rowH) {
                            s.measure(MeasureSpec.makeMeasureSpec(colW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(rowH, MeasureSpec.EXACTLY));
                        }
                    }
                    count = 0;
                    rowH = 0;
                }
            }
            setMeasuredDimension(width, total + getPaddingTop() + getPaddingBottom());
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            int inner = r - l - getPaddingLeft() - getPaddingRight();
            int n = cols(inner);
            int colW = Math.max(0, (inner - gap * (n - 1)) / n);
            int x, y = getPaddingTop(), col = 0, rowH = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                if (ch.getVisibility() == GONE) continue;
                x = getPaddingLeft() + col * (colW + gap);
                ch.layout(x, y, x + ch.getMeasuredWidth(), y + ch.getMeasuredHeight());
                rowH = Math.max(rowH, ch.getMeasuredHeight());
                col++;
                if (col == n) {
                    col = 0;
                    y += rowH + gap;
                    rowH = 0;
                }
            }
        }
    }

    /** flex-wrap row (justify end or start). */
    static class Flow extends ViewGroup {
        private final int gap;
        private final boolean alignEnd;

        Flow(Context c, float gapDp, boolean alignEnd) {
            super(c);
            this.gap = dp(c, gapDp);
            this.alignEnd = alignEnd;
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            int maxW = MeasureSpec.getMode(wSpec) == MeasureSpec.UNSPECIFIED ? Integer.MAX_VALUE : MeasureSpec.getSize(wSpec);
            int avail = maxW - getPaddingLeft() - getPaddingRight();
            int lineW = 0, lineH = 0, usedW = 0, totalH = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                if (ch.getVisibility() == GONE) continue;
                ch.measure(MeasureSpec.makeMeasureSpec(Math.max(0, avail), MeasureSpec.AT_MOST), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED));
                int w = ch.getMeasuredWidth();
                if (lineW > 0 && lineW + gap + w > avail) {
                    usedW = Math.max(usedW, lineW);
                    totalH += lineH + gap;
                    lineW = 0;
                    lineH = 0;
                }
                lineW += (lineW > 0 ? gap : 0) + w;
                lineH = Math.max(lineH, ch.getMeasuredHeight());
            }
            usedW = Math.max(usedW, lineW);
            totalH += lineH;
            int w = MeasureSpec.getMode(wSpec) == MeasureSpec.EXACTLY ? MeasureSpec.getSize(wSpec)
                    : Math.min(maxW, usedW + getPaddingLeft() + getPaddingRight());
            setMeasuredDimension(w, totalH + getPaddingTop() + getPaddingBottom());
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            int avail = r - l - getPaddingLeft() - getPaddingRight();
            int y = getPaddingTop();
            int i = 0;
            int n = getChildCount();
            while (i < n) {
                // collect one line
                int lineW = 0, lineH = 0, start = i;
                while (i < n) {
                    View ch = getChildAt(i);
                    if (ch.getVisibility() == GONE) { i++; continue; }
                    int w = ch.getMeasuredWidth();
                    if (lineW > 0 && lineW + gap + w > avail) break;
                    lineW += (lineW > 0 ? gap : 0) + w;
                    lineH = Math.max(lineH, ch.getMeasuredHeight());
                    i++;
                }
                int x = getPaddingLeft() + (alignEnd ? Math.max(0, avail - lineW) : 0);
                for (int j = start; j < i; j++) {
                    View ch = getChildAt(j);
                    if (ch.getVisibility() == GONE) continue;
                    int cy = y + (lineH - ch.getMeasuredHeight()) / 2;
                    ch.layout(x, cy, x + ch.getMeasuredWidth(), cy + ch.getMeasuredHeight());
                    x += ch.getMeasuredWidth() + gap;
                }
                y += lineH + gap;
                if (start == i) i++; // safety
            }
        }
    }

    // ------------------------------------------------------------------ segmented group
    interface IntListener {
        void on(int value);
    }

    /** .seg-group / .seg-btn (wrapping, right-aligned). */
    static final class Seg extends FrameLayout {
        private final Flow flow;
        private int[] values = new int[0];
        private int selected = Integer.MIN_VALUE;
        private IntListener listener;

        Seg(Context c) {
            super(c);
            setBackground(rect(c, SURFACE2, 10, BORDER, 1));
            int p = dp(c, 3);
            setPadding(p, p, p, p);
            flow = new Flow(c, 3, true);
            addView(flow, new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        void setListener(IntListener l) {
            listener = l;
        }

        void setItems(String[] labels, int[] vals) {
            values = vals;
            flow.removeAllViews();
            Context c = getContext();
            for (int i = 0; i < labels.length; i++) {
                final int v = vals[i];
                TextView t = text(c, labels[i], 12f, SUBTEXT, 600);
                t.setPadding(dp(c, 10), dp(c, 5), dp(c, 10), dp(c, 5));
                t.setGravity(Gravity.CENTER);
                t.setMinHeight(dp(c, 26));
                t.setClickable(true);
                t.setOnClickListener(new OnClickListener() {
                    @Override
                    public void onClick(View view) {
                        select(v);
                        if (listener != null) listener.on(v);
                    }
                });
                pressable(t);
                flow.addView(t);
            }
            int s = selected;
            selected = Integer.MIN_VALUE;
            select(s);
        }

        void select(int value) {
            selected = value;
            Context c = getContext();
            for (int i = 0; i < flow.getChildCount() && i < values.length; i++) {
                TextView t = (TextView) flow.getChildAt(i);
                boolean on = values[i] == value;
                t.setBackground(on ? rect(c, TEXT, 7, 0, 0) : null);
                t.setTextColor(on ? BG : SUBTEXT);
            }
        }
    }

    // ------------------------------------------------------------------ touch-safe slider
    interface SliderListener {
        void onInput(float v);

        void onCommit(float v);
    }

    /**
     * .slider-zone + .safe-range: a vertical swipe scrolls the page (never moves the slider);
     * a horizontal drag, a 180 ms hold or a precise tap set the value (web attachSafeSlider).
     */
    static final class Slider extends View {
        private float min = 0, max = 100, step = 1, value = 0;
        private int fill = TEXT;
        private boolean redThumb;
        private SliderListener listener;
        private final Paint track = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint fillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint thumb = new Paint(Paint.ANTI_ALIAS_FLAG);
        private static final int ST_NONE = 0, ST_PENDING = 1, ST_SCROLL = 2, ST_DRAG = 3;
        private int state = ST_NONE;
        private float startX, startY, lastX, lastY;
        private long startTime;
        private float thumbScale = 1f;
        private ValueAnimator scaleAnim;
        private final int slop;
        private final Runnable hold = new Runnable() {
            @Override
            public void run() {
                if (state == ST_PENDING) {
                    beginDrag();
                    setFromX(startX, false);
                }
            }
        };

        Slider(Context c) {
            super(c);
            track.setColor(0x29FFFFFF);
            fillPaint.setColor(fill);
            thumb.setColor(TEXT);
            slop = dp(c, 8);
            setLayerType(LAYER_TYPE_SOFTWARE, null); // thumb shadow / glow
            setLayoutParams(new LinearLayout.LayoutParams(0, dp(c, 30), 1f));
            updateThumbShadow(false);
        }

        void configure(float min, float max, float step, int fillColor, boolean redThumb) {
            this.min = min;
            this.max = max;
            this.step = step;
            this.fill = fillColor;
            this.redThumb = redThumb;
            fillPaint.setColor(fillColor);
            thumb.setColor(redThumb ? RED : TEXT);
            updateThumbShadow(false);
            invalidate();
        }

        void setRange(float min, float max) {
            this.min = min;
            this.max = Math.max(min + 0.0001f, max);
            invalidate();
        }

        void setListener(SliderListener l) {
            listener = l;
        }

        void setValue(float v) {
            value = Math.max(min, Math.min(max, v));
            invalidate();
        }

        float getValue() {
            return value;
        }

        boolean isDragging() {
            return state == ST_DRAG;
        }

        private void updateThumbShadow(boolean dragging) {
            Context c = getContext();
            if (redThumb) thumb.setShadowLayer(dp(c, dragging ? 7 : 4), 0, 0, dragging ? 0xE6FF0033 : 0x99FF0033);
            else if (dragging) thumb.setShadowLayer(dp(c, 6), 0, 0, 0xA6FFFFFF);
            else thumb.setShadowLayer(dp(c, 3), 0, dp(c, 1), 0x8C000000);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            Context c = getContext();
            float r = dp(c, 7.5f);
            float pad = dp(c, 8);
            float left = pad, right = getWidth() - pad;
            float cy = getHeight() / 2f;
            float h = dp(c, 2);
            canvas.drawRoundRect(left, cy - h, right, cy + h, h, h, track);
            float frac = max > min ? (value - min) / (max - min) : 0;
            float x = left + (right - left) * Math.max(0, Math.min(1, frac));
            if (x > left) canvas.drawRoundRect(left, cy - h, x, cy + h, h, h, fillPaint);
            canvas.drawCircle(x, cy, r * thumbScale, thumb);
        }

        private float valueAt(float px) {
            Context c = getContext();
            float pad = dp(c, 8);
            float w = getWidth() - 2 * pad;
            if (w <= 0) return value;
            float ratio = Math.max(0, Math.min(1, (px - pad) / w));
            float raw = min + ratio * (max - min);
            if (step > 0) raw = Math.round((raw - min) / step) * step + min;
            return Math.max(min, Math.min(max, raw));
        }

        private void setFromX(float px, boolean commit) {
            value = valueAt(px);
            invalidate();
            if (listener != null) {
                listener.onInput(value);
                if (commit) listener.onCommit(value);
            }
        }

        private void animScale(float to) {
            if (scaleAnim != null) scaleAnim.cancel();
            scaleAnim = ValueAnimator.ofFloat(thumbScale, to);
            scaleAnim.setDuration(120);
            scaleAnim.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator a) {
                    thumbScale = (float) a.getAnimatedValue();
                    invalidate();
                }
            });
            scaleAnim.start();
        }

        private void beginDrag() {
            state = ST_DRAG;
            if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
            updateThumbShadow(true);
            animScale(1.4f);
        }

        private void endDrag() {
            updateThumbShadow(false);
            animScale(1f);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (!isEnabled()) return false;
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    startX = lastX = e.getX();
                    startY = lastY = e.getY();
                    startTime = System.currentTimeMillis();
                    state = ST_PENDING;
                    removeCallbacks(hold);
                    postDelayed(hold, 180);
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    if (state == ST_SCROLL || state == ST_NONE) return false;
                    lastX = e.getX();
                    lastY = e.getY();
                    float dx = Math.abs(lastX - startX), dy = Math.abs(lastY - startY);
                    if (state == ST_PENDING) {
                        if (dy >= slop || (dy >= slop * 0.6f && dy > dx * 0.8f)) {
                            removeCallbacks(hold);
                            state = ST_SCROLL;
                            return false;
                        }
                        if (dx >= slop && dy <= slop * 0.75f && dx > dy * 1.3f) {
                            removeCallbacks(hold);
                            beginDrag();
                            setFromX(lastX, false);
                            return true;
                        }
                        if (dx > slop / 2f || dy > slop / 2f) removeCallbacks(hold);
                        return true;
                    }
                    setFromX(lastX, false);
                    return true;
                }
                case MotionEvent.ACTION_UP: {
                    removeCallbacks(hold);
                    if (state == ST_PENDING) {
                        float dist = (float) Math.hypot(lastX - startX, lastY - startY);
                        if (dist <= slop && System.currentTimeMillis() - startTime < 600) setFromX(startX, true);
                    } else if (state == ST_DRAG) {
                        endDrag();
                        if (listener != null) listener.onCommit(value);
                    }
                    state = ST_NONE;
                    return true;
                }
                case MotionEvent.ACTION_CANCEL:
                    removeCallbacks(hold);
                    if (state == ST_DRAG) {
                        endDrag();
                        if (listener != null) listener.onCommit(value);
                    }
                    state = ST_NONE;
                    return true;
                default:
                    return true;
            }
        }
    }

    /** Volume row: round mute button · slider · mono value (.ytm-vol-row / .sys-vol-row). */
    static final class VolRow extends LinearLayout {
        final RoundIcon muteBtn;
        final Slider slider;
        final TextView value;

        VolRow(Context c, boolean playerStyle, String[] icon) {
            super(c);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            if (playerStyle) {
                setBackground(rect(c, 0x0AFFFFFF, 12, 0, 0));
                setPadding(dp(c, 6), dp(c, 4), dp(c, 12), dp(c, 4));
            } else {
                setBackground(rect(c, SURFACE2, 12, 0, 0));
                setPadding(dp(c, 6), dp(c, 5), dp(c, 12), dp(c, 5));
            }
            muteBtn = new RoundIcon(c, icon, 32, 17, SUBTEXT);
            addView(muteBtn);
            slider = new Slider(c);
            LayoutParams sp = new LayoutParams(0, dp(c, 30), 1f);
            sp.leftMargin = dp(c, 10);
            sp.rightMargin = dp(c, 10);
            addView(slider, sp);
            value = monoText(c, "—", 11.5f, SUBTEXT);
            value.setGravity(Gravity.END);
            value.setMinWidth(dp(c, 34));
            addView(value);
        }
    }

    // ------------------------------------------------------------------ fields
    /** .conn-field: surface2, 1px border, radius 11, 10/12 padding, mono 13px. */
    static EditText field(Context c, String hint, boolean monoFont, float sp) {
        EditText e = new EditText(c);
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        e.setTextColor(TEXT);
        e.setHintTextColor(0xFF757575);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setTypeface(monoFont ? mono() : face(400));
        e.setPadding(dp(c, 12), dp(c, 10), dp(c, 12), dp(c, 10));
        e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        e.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        final GradientDrawable normal = rect(c, SURFACE2, 11, BORDER, 1);
        final GradientDrawable focused = rect(c, SURFACE2, 11, 0x47FFFFFF, 1);
        e.setBackground(normal);
        e.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View v, boolean has) {
                v.setBackground(has ? focused : normal);
            }
        });
        if (Build.VERSION.SDK_INT >= 29) e.setTextCursorDrawable(rect(c, RED, 1, 0, 0));
        e.setLayoutParams(matchWrap());
        return e;
    }

    static void setMasked(EditText e, boolean masked) {
        int sel = e.getSelectionEnd();
        e.setTransformationMethod(masked ? PasswordTransformationMethod.getInstance() : null);
        if (sel >= 0 && sel <= e.length()) e.setSelection(sel);
    }

    /** .conn-sec-btn eye / copy button with the cross-fading icon pair. */
    static final class SecBtn extends FrameLayout {
        final ImageView a, b;
        private final boolean compact;
        private final int onColor, onBg, onBorder;
        private boolean on;

        SecBtn(Context c, boolean eye, boolean compact) {
            super(c);
            this.compact = compact;
            a = icon(c, eye ? PcAppIcons.EYE_OFF : PcAppIcons.COPY, SUBTEXT, 15);
            b = icon(c, eye ? PcAppIcons.EYE : PcAppIcons.CHECK, eye ? BLUE : GREEN, 15);
            onColor = eye ? BLUE : GREEN;
            onBg = eye ? 0x1F60A5FA : 0x2922C55E;
            onBorder = eye ? 0x7360A5FA : 0x8C22C55E;
            addView(a, new LayoutParams(dp(c, 15), dp(c, 15), Gravity.CENTER));
            addView(b, new LayoutParams(dp(c, 15), dp(c, 15), Gravity.CENTER));
            int s = dp(c, compact ? 28 : 36);
            setLayoutParams(new LinearLayout.LayoutParams(s, s));
            setClickable(true);
            setFocusable(true);
            pressable(this, 0.9f);
            apply(false, false);
            // QA P-14: TalkBack read "button" without saying what it does
            if (c instanceof MainActivity) setContentDescription(((MainActivity) c).t(eye ? "tip_show_hide" : "tip_copy"));
        }

        boolean isOn() {
            return on;
        }

        void setOn(boolean v, boolean animate) {
            apply(v, animate);
        }

        private void apply(boolean v, boolean animate) {
            on = v;
            Context c = getContext();
            setBackground(v ? rect(c, onBg, compact ? 8 : 10, onBorder, 1)
                    : rect(c, compact ? 0x0FFFFFFF : SURFACE2, compact ? 8 : 10, BORDER, 1));
            tintIcon(a, SUBTEXT);
            tintIcon(b, onColor);
            float rot = 25f;
            if (animate) {
                a.animate().alpha(v ? 0f : 1f).scaleX(v ? 0.5f : 1f).scaleY(v ? 0.5f : 1f).rotation(v ? rot : 0f).setDuration(240).start();
                b.animate().alpha(v ? 1f : 0f).scaleX(v ? 1f : 0.5f).scaleY(v ? 1f : 0.5f).rotation(v ? 0f : -rot).setDuration(240).start();
            } else {
                a.setAlpha(v ? 0f : 1f);
                a.setScaleX(v ? 0.5f : 1f);
                a.setScaleY(v ? 0.5f : 1f);
                b.setAlpha(v ? 1f : 0f);
                b.setScaleX(v ? 1f : 0.5f);
                b.setScaleY(v ? 1f : 0.5f);
            }
        }

        /** copy feedback: green check for 1.6 s. */
        void flashCopied() {
            apply(true, true);
            removeCallbacks(reset);
            postDelayed(reset, 1600);
        }

        private final Runnable reset = new Runnable() {
            @Override
            public void run() {
                apply(false, true);
            }
        };
    }

    // ------------------------------------------------------------------ scroll container
    /** overflow-y:auto box with max-height that hands the gesture back to the page at its ends. */
    static final class MaxScroll extends ScrollView {
        private int maxH;
        private float downY;

        MaxScroll(Context c, float maxDp) {
            super(c);
            maxH = maxDp > 0 ? dp(c, maxDp) : 0;
            setVerticalScrollBarEnabled(true);
            setOverScrollMode(OVER_SCROLL_NEVER);
            setFillViewport(false);
        }

        void setMaxHeightDp(float v) {
            maxH = dp(getContext(), v);
            requestLayout();
        }

        @Override
        protected void onMeasure(int wSpec, int hSpec) {
            if (maxH > 0) hSpec = MeasureSpec.makeMeasureSpec(maxH, MeasureSpec.AT_MOST);
            super.onMeasure(wSpec, hSpec);
        }

        @Override
        public boolean onInterceptTouchEvent(MotionEvent ev) {
            if (ev.getActionMasked() == MotionEvent.ACTION_DOWN) {
                downY = ev.getY();
                if (getParent() != null && (canScrollVertically(1) || canScrollVertically(-1))) {
                    getParent().requestDisallowInterceptTouchEvent(true);
                }
            }
            return super.onInterceptTouchEvent(ev);
        }

        @Override
        public boolean onTouchEvent(MotionEvent ev) {
            if (ev.getActionMasked() == MotionEvent.ACTION_MOVE && getParent() != null) {
                float dy = ev.getY() - downY;
                int slop = ViewConfiguration.get(getContext()).getScaledTouchSlop();
                if (Math.abs(dy) > slop) {
                    boolean can = dy < 0 ? canScrollVertically(1) : canScrollVertically(-1);
                    if (!can) getParent().requestDisallowInterceptTouchEvent(false);
                }
            }
            return super.onTouchEvent(ev);
        }
    }

    // ------------------------------------------------------------------ side toast
    /**
     * Компактное уведомление: выезжает справа у верхнего края, само скрывается через ~2.5 с
     * (касание — сразу). Карточка приложения: surface, рамка, радиус 12, значок в кружке как у
     * кнопки «Скопировано» (зелёная галочка) или в стиле ошибок (danger). Добавляется последним
     * ребёнком корневого FrameLayout с высоким Z — поверх страницы, окон и демонстрации экрана.
     * Один экземпляр на хост: новое сообщение заменяет текущее.
     */
    static final class SideToast extends LinearLayout {
        private static final long SHOW_MS = 2500;
        private final ImageView iconView;
        private final FrameLayout iconWrap;
        private final TextView label;
        private final Runnable hideRunnable = new Runnable() {
            @Override
            public void run() {
                hide();
            }
        };
        private boolean hiding;

        private SideToast(Context c) {
            super(c);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setPadding(dp(c, 10), dp(c, 9), dp(c, 14), dp(c, 9));
            setElevation(dp(c, 10));
            setTranslationZ(dp(c, 24));
            iconWrap = new FrameLayout(c);
            iconView = icon(c, PcAppIcons.CHECK, GREEN, 14);
            iconWrap.addView(iconView, new FrameLayout.LayoutParams(dp(c, 14), dp(c, 14), Gravity.CENTER));
            addView(iconWrap, lp(dp(c, 24), dp(c, 24)));
            label = text(c, "", 12.5f, TEXT, 500);
            label.setMaxLines(4); // QA P2-3: long hints were cut («…прозрачн…»)
            label.setEllipsize(TextUtils.TruncateAt.END);
            LayoutParams tp = wrap();
            tp.leftMargin = dp(c, 10);
            addView(label, tp);
            // QA P-7: the toast lies over the stream's controls (zoom, touchpad) — it must not eat taps.
            // Not clickable: touches go through to whatever is underneath; it hides by itself.
            setClickable(false);
            setFocusable(false);
        }

        @Override
        public boolean onTouchEvent(android.view.MotionEvent ev) {
            return false;
        }

        /** Показать сообщение в host (корневой FrameLayout активности). */
        static void show(FrameLayout host, CharSequence text, boolean error) {
            if (host == null || text == null) return;
            Context c = host.getContext();
            SideToast t = null;
            for (int i = 0; i < host.getChildCount(); i++) {
                if (host.getChildAt(i) instanceof SideToast) t = (SideToast) host.getChildAt(i);
            }
            if (t == null || t.hiding) {
                if (t != null) host.removeView(t);
                t = new SideToast(c);
                FrameLayout.LayoutParams p = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.END);
                host.addView(t, p);
                t.setTranslationX(dp(c, 420));
                t.setAlpha(0f);
            } else {
                t.bringToFront();
            }
            t.bind(host, text, error);
            t.animate().cancel();
            t.animate().translationX(0f).alpha(1f).setDuration(260)
                    .setInterpolator(new DecelerateInterpolator(1.6f)).setListener(null).start();
            t.removeCallbacks(t.hideRunnable);
            t.postDelayed(t.hideRunnable, Math.min(7000, SHOW_MS + 35L * Math.max(0, text.length() - 40))); // time to read
        }

        private void bind(FrameLayout host, CharSequence text, boolean error) {
            Context c = getContext();
            label.setText(text);
            if (error) {
                // danger-стиль приложения (button.danger-soft), непрозрачный — читается и поверх видео
                setBackground(rect(c, 0xFF301817, 12, 0x59FF453A, 1));
                label.setTextColor(DANGER);
                iconWrap.setBackground(oval(DANGER_BG));
                PcViews.setIcon(iconView, PcAppIcons.CLOSE, DANGER);
            } else {
                setBackground(rect(c, SURFACE, 12, BORDER_STRONG, 1));
                label.setTextColor(TEXT);
                iconWrap.setBackground(oval(0x2922C55E));
                PcViews.setIcon(iconView, PcAppIcons.CHECK, GREEN);
            }
            // отступы: 12 dp от края + вырез камеры, если корень начинается под ним (полный экран)
            int top = dp(c, 12), right = dp(c, 12);
            if (Build.VERSION.SDK_INT >= 28) {
                try {
                    android.view.WindowInsets wi = host.getRootWindowInsets();
                    android.view.DisplayCutout dc = wi != null ? wi.getDisplayCutout() : null;
                    if (dc != null) {
                        int[] loc = new int[2];
                        host.getLocationOnScreen(loc);
                        top += Math.max(0, dc.getSafeInsetTop() - loc[1]);
                        right += dc.getSafeInsetRight();
                    }
                } catch (Exception ignored) {
                }
            }
            FrameLayout.LayoutParams p = (FrameLayout.LayoutParams) getLayoutParams();
            p.topMargin = top;
            p.rightMargin = right;
            setLayoutParams(p);
            int hostW = host.getWidth() > 0 ? host.getWidth() : c.getResources().getDisplayMetrics().widthPixels;
            label.setMaxWidth(Math.max(dp(c, 120), Math.min(dp(c, 300), hostW - dp(c, 96))));
        }

        private void hide() {
            if (hiding) return;
            hiding = true;
            removeCallbacks(hideRunnable);
            final ViewGroup parent = (ViewGroup) getParent();
            int off = getWidth() + dp(getContext(), 24);
            animate().cancel();
            animate().translationX(off).alpha(0f).setDuration(220)
                    .setInterpolator(new DecelerateInterpolator())
                    .setListener(new android.animation.AnimatorListenerAdapter() {
                        @Override
                        public void onAnimationEnd(android.animation.Animator a) {
                            if (parent != null) parent.removeView(SideToast.this);
                        }
                    }).start();
        }
    }

    /** Animated expand / collapse of a view's height (prelaunch body, drawers). */
    static void animateHeight(final View v, final boolean open, int durationMs) {
        v.animate().cancel();
        if (open) {
            v.setVisibility(View.VISIBLE);
            ViewGroup.LayoutParams p = v.getLayoutParams();
            int w = v.getWidth() > 0 ? v.getWidth() : ((View) v.getParent()).getWidth();
            v.measure(View.MeasureSpec.makeMeasureSpec(Math.max(1, w), View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
            final int target = v.getMeasuredHeight();
            p.height = 0;
            v.setLayoutParams(p);
            v.setAlpha(0f);
            ValueAnimator a = ValueAnimator.ofInt(0, target);
            a.setDuration(durationMs);
            a.setInterpolator(new DecelerateInterpolator(1.6f));
            a.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator an) {
                    ViewGroup.LayoutParams lp = v.getLayoutParams();
                    lp.height = (int) an.getAnimatedValue();
                    if (an.getAnimatedFraction() >= 1f) lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;
                    v.setLayoutParams(lp);
                    v.setAlpha(Math.min(1f, an.getAnimatedFraction() * 1.3f));
                }
            });
            a.start();
        } else {
            final int from = v.getHeight();
            ValueAnimator a = ValueAnimator.ofInt(from, 0);
            a.setDuration(durationMs);
            a.setInterpolator(new DecelerateInterpolator(1.6f));
            a.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator an) {
                    ViewGroup.LayoutParams lp = v.getLayoutParams();
                    lp.height = (int) an.getAnimatedValue();
                    v.setLayoutParams(lp);
                    v.setAlpha(1f - an.getAnimatedFraction());
                    if (an.getAnimatedFraction() >= 1f) {
                        v.setVisibility(View.GONE);
                        lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;
                        v.setLayoutParams(lp);
                        v.setAlpha(1f);
                    }
                }
            });
            a.start();
        }
    }

    /** fadeIn: opacity 0→1, translateY 4px→0 (settings panes). */
    static void fadeIn(View v) {
        v.setAlpha(0f);
        v.setTranslationY(dp(v.getContext(), 4));
        v.animate().alpha(1f).translationY(0).setDuration(200).start();
    }

    static int alpha(int color, float a) {
        return (Math.round(a * 255) << 24) | (color & 0x00FFFFFF);
    }

    static int parse(String hex) {
        return Color.parseColor(hex);
    }
}
