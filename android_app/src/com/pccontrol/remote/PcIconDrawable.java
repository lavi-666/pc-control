package com.pccontrol.remote;

import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;

/** Draws one {@link PcIcons} icon (24x24 viewBox) scaled to the drawable bounds. */
public class PcIconDrawable extends Drawable {

    private final Path src = new Path();
    private final Path scaled = new Path();
    private final Matrix matrix = new Matrix();
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final boolean stroke;
    private final int sizePx;
    private int alpha = 255;
    private int color;

    public PcIconDrawable(String[] icon, int color, int sizePx) {
        this.stroke = "S".equals(icon[0]);
        this.sizePx = sizePx;
        this.color = color;
        for (int i = 1; i < icon.length; i++) {
            PcSvgPath.parse(icon[i], new PcSvgPath.Sink() {
                @Override public void moveTo(float x, float y) { src.moveTo(x, y); }
                @Override public void lineTo(float x, float y) { src.lineTo(x, y); }
                @Override public void cubicTo(float x1, float y1, float x2, float y2, float x, float y) {
                    src.cubicTo(x1, y1, x2, y2, x, y);
                }
                @Override public void close() { src.close(); }
            });
        }
        src.setFillType(Path.FillType.WINDING);
        if (stroke) {
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
        } else {
            paint.setStyle(Paint.Style.FILL);
        }
        applyColor();
    }

    public void setColor(int c) {
        if (c != color) {
            color = c;
            applyColor();
            invalidateSelf();
        }
    }

    public int getColor() {
        return color;
    }

    private void applyColor() {
        paint.setColor(color);
        paint.setAlpha(Math.round(((color >>> 24) & 0xFF) * (alpha / 255f)));
    }

    @Override
    protected void onBoundsChange(Rect b) {
        super.onBoundsChange(b);
        float s = Math.min(b.width(), b.height()) / 24f;
        matrix.reset();
        matrix.setScale(s, s);
        matrix.postTranslate(b.left + (b.width() - 24f * s) / 2f, b.top + (b.height() - 24f * s) / 2f);
        src.transform(matrix, scaled);
        paint.setStrokeWidth(2f * s);
    }

    @Override
    public void draw(Canvas canvas) {
        canvas.drawPath(scaled, paint);
    }

    @Override
    public int getIntrinsicWidth() {
        return sizePx;
    }

    @Override
    public int getIntrinsicHeight() {
        return sizePx;
    }

    @Override
    public void setAlpha(int a) {
        alpha = a;
        applyColor();
        invalidateSelf();
    }

    @Override
    public void setColorFilter(ColorFilter cf) {
        paint.setColorFilter(cf);
        invalidateSelf();
    }

    @Override
    public int getOpacity() {
        return PixelFormat.TRANSLUCENT;
    }
}
