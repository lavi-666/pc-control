package com.pccontrol.remote;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.util.SparseArray;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/**
 * Canvas-drawn PC Control keyboard (replaces the system keyboard in the player).
 * Real multitouch: every finger holds its own key (press on touch, release on lift),
 * so chords like holding Ctrl with one finger and tapping C with another work.
 * Colours follow the existing PC Control player palette.
 */
public class PcKeyboardView extends View {

    private final PcKeyboardLogic logic;
    private final List<PcKeyboardLogic.Key[]> rows = new ArrayList<>();
    private final List<RectF[]> rects = new ArrayList<>();
    private final SparseArray<PcKeyboardLogic.Press> pointerPress = new SparseArray<>();
    private final SparseArray<PcKeyboardLogic.Key> pointerKey = new SparseArray<>();

    private final Paint keyPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint strokePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private float keyAlpha = 0.95f;
    private float specialAlpha = 0.95f;
    private boolean haptics = true;
    private final float density;

    // Palette = PC Control app tokens (assets/css/styles.css): surface2/surface3 keys,
    // rgba(255,255,255,.13) borders, button.active (white 18 % + white 50 % border) for
    // held/latched modifiers, --ytm-red for a locked modifier (Caps), subtext for service keys.
    private static final int C_KEY = 0xFF1D1D1D;
    private static final int C_SPECIAL = 0xFF282828;
    private static final int C_PRESSED = 0xFF4A4A4A;
    private static final int C_STROKE = 0x21FFFFFF;
    private static final int C_ACTIVE_BG = 0xFF424242;
    private static final int C_ACTIVE_STROKE = 0x80FFFFFF;
    private static final int C_SERVICE_TEXT = 0xFFAAAAAA;
    private static final int C_LOCK_BG = 0xFF3A1019;
    private static final int C_LOCK_STROKE = 0xFFFF0033;
    private static final int C_TEXT = Color.WHITE;

    public PcKeyboardView(Context context, PcKeyboardLogic logic) {
        super(context);
        this.logic = logic;
        density = context.getResources().getDisplayMetrics().density;
        strokePaint.setStyle(Paint.Style.STROKE);
        strokePaint.setStrokeWidth(Math.max(1f, density));
        textPaint.setTextAlign(Paint.Align.CENTER);
        textPaint.setTypeface(Typeface.DEFAULT_BOLD);
        setHapticFeedbackEnabled(true);
        rebuild();
    }

    public void setKeyOpacity(float keys, float special) {
        keyAlpha = Math.max(0.1f, Math.min(1f, keys));
        specialAlpha = Math.max(0.1f, Math.min(1f, special));
        invalidate();
    }

    public void setHaptics(boolean on) {
        haptics = on;
    }

    /** Re-reads layout/layer from the logic (language, layer or modifier change). */
    public void rebuild() {
        rows.clear();
        rows.addAll(logic.rows());
        layoutKeys(getWidth(), getHeight());
        invalidate();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        layoutKeys(w, h);
    }

    private void layoutKeys(int w, int h) {
        rects.clear();
        if (w <= 0 || h <= 0 || rows.isEmpty()) return;
        float gap = 3f * density;
        // Function strip is a bit lower than the main rows.
        float weightSum = 0.75f + (rows.size() - 1);
        float unitH = h / weightSum;
        float maxUnits = 0;
        for (PcKeyboardLogic.Key[] row : rows) {
            float u = 0;
            for (PcKeyboardLogic.Key k : row) u += k.width;
            maxUnits = Math.max(maxUnits, u);
        }
        float y = 0;
        for (int r = 0; r < rows.size(); r++) {
            PcKeyboardLogic.Key[] row = rows.get(r);
            float rowH = (r == 0) ? unitH * 0.75f : unitH;
            float units = 0;
            for (PcKeyboardLogic.Key k : row) units += k.width;
            // Rows share one key unit (like a real keyboard); the function strip and
            // the bottom row stretch to the full width.
            boolean stretch = (r == 0 || r == rows.size() - 1);
            float unitW = stretch ? (w / units) : (w / maxUnits);
            float x = stretch ? 0 : (w - unitW * units) / 2f;
            RectF[] rr = new RectF[row.length];
            for (int i = 0; i < row.length; i++) {
                float kw = unitW * row[i].width;
                rr[i] = new RectF(x + gap / 2, y + gap / 2, x + kw - gap / 2, y + rowH - gap / 2);
                x += kw;
            }
            rects.add(rr);
            y += rowH;
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float radius = 7f * density;
        for (int r = 0; r < rows.size() && r < rects.size(); r++) {
            PcKeyboardLogic.Key[] row = rows.get(r);
            RectF[] rr = rects.get(r);
            for (int i = 0; i < row.length; i++) {
                PcKeyboardLogic.Key k = row[i];
                RectF rect = rr[i];
                boolean isPressed = isKeyPressed(k);
                int bg = k.special ? C_SPECIAL : C_KEY;
                int stroke = C_STROKE;
                int fg = (k.special && k.kind != PcKeyboardLogic.K_CHAR) ? C_SERVICE_TEXT : C_TEXT;
                if (k.kind == PcKeyboardLogic.K_MOD) {
                    int st = logic.getModState(k.mod);
                    if (st == PcKeyboardLogic.ST_LOCKED) {
                        bg = C_LOCK_BG;
                        stroke = C_LOCK_STROKE;
                        fg = C_TEXT;
                    } else if (st != PcKeyboardLogic.ST_OFF) {
                        bg = C_ACTIVE_BG;
                        stroke = C_ACTIVE_STROKE;
                        fg = C_TEXT;
                    }
                } else if ((k.kind == PcKeyboardLogic.K_FN && logic.getLayer() == PcKeyboardLogic.LAYER_FN)) {
                    bg = C_ACTIVE_BG;
                    stroke = C_ACTIVE_STROKE;
                    fg = C_TEXT;
                }
                if (isPressed) bg = C_PRESSED;
                float alpha = (r == 0 ? specialAlpha : keyAlpha);
                keyPaint.setColor(bg);
                keyPaint.setAlpha((int) (alpha * 255));
                canvas.drawRoundRect(rect, radius, radius, keyPaint);
                strokePaint.setColor(stroke);
                strokePaint.setAlpha((int) (alpha * 255));
                canvas.drawRoundRect(rect, radius, radius, strokePaint);

                String label = logic.displayLabel(k);
                float ts = Math.min(rect.height() * 0.42f, 17f * density);
                if (label.length() > 2) ts = Math.min(ts, rect.width() / (label.length() * 0.62f));
                textPaint.setTextSize(Math.max(8f * density, ts));
                textPaint.setColor(fg);
                textPaint.setAlpha((int) (Math.min(1f, alpha + 0.05f) * 255));
                float ty = rect.centerY() - (textPaint.descent() + textPaint.ascent()) / 2f;
                canvas.drawText(label, rect.centerX(), ty, textPaint);
            }
        }
    }

    private boolean isKeyPressed(PcKeyboardLogic.Key k) {
        for (int i = 0; i < pointerKey.size(); i++) {
            if (pointerKey.valueAt(i) == k) return true;
        }
        return false;
    }

    private PcKeyboardLogic.Key keyAt(float x, float y) {
        PcKeyboardLogic.Key best = null;
        float bestDist = Float.MAX_VALUE;
        for (int r = 0; r < rows.size() && r < rects.size(); r++) {
            RectF[] rr = rects.get(r);
            for (int i = 0; i < rr.length; i++) {
                RectF rect = rr[i];
                if (y < rect.top - 4 * density || y > rect.bottom + 4 * density) continue;
                // gaps between keys belong to the nearest key
                float dx = x < rect.left ? rect.left - x : (x > rect.right ? x - rect.right : 0);
                float dy = y < rect.top ? rect.top - y : (y > rect.bottom ? y - rect.bottom : 0);
                float d = dx + dy;
                if (d < bestDist) {
                    bestDist = d;
                    best = rows.get(r)[i];
                }
            }
        }
        return bestDist <= 6 * density ? best : null;
    }

    @Override
    public boolean onTouchEvent(MotionEvent ev) {
        int action = ev.getActionMasked();
        switch (action) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN: {
                int idx = ev.getActionIndex();
                int id = ev.getPointerId(idx);
                PcKeyboardLogic.Key k = keyAt(ev.getX(idx), ev.getY(idx));
                if (k != null) {
                    pointerKey.put(id, k);
                    pointerPress.put(id, logic.press(k));
                    if (haptics) performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    invalidate();
                }
                return true;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP: {
                int idx = ev.getActionIndex();
                releasePointer(ev.getPointerId(idx));
                return true;
            }
            case MotionEvent.ACTION_CANCEL:
                releaseAllPointers();
                return true;
            default:
                return true;
        }
    }

    private void releasePointer(int id) {
        PcKeyboardLogic.Press p = pointerPress.get(id);
        pointerPress.remove(id);
        pointerKey.remove(id);
        if (p != null) logic.release(p);
        invalidate();
    }

    /** Lifts every finger-held key (hide, cancel, focus loss). */
    public void releaseAllPointers() {
        for (int i = pointerPress.size() - 1; i >= 0; i--) {
            PcKeyboardLogic.Press p = pointerPress.valueAt(i);
            if (p != null) logic.release(p);
        }
        pointerPress.clear();
        pointerKey.clear();
        invalidate();
    }

    @Override
    protected void onDetachedFromWindow() {
        releaseAllPointers();
        super.onDetachedFromWindow();
    }
}
