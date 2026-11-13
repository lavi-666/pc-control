package com.pccontrol.remote;

/**
 * Математика «лупы» в «Управлении ПК» (чистая Java — покрыта JVM-тестами).
 *
 * Координаты — пиксели контейнера видео (вся площадь плеера, 0..vw × 0..vh).
 * base — прямоугольник картинки ПК при масштабе 1× (Fit/Fill, по центру).
 * Отображаемый прямоугольник: (ox, oy, bw*z, bh*z).
 *
 * Правила (как в RD Client / Chrome Remote Desktop):
 *  - масштаб 1×..5×, щипок увеличивает вокруг точки между пальцами;
 *  - картинка никогда не уезжает с экрана: если она шире/выше экрана — края не отходят
 *    от краёв экрана, если уже/ниже — стоит по центру (поля симметричные);
 *  - курсор ПК держится в видимой области: когда он подходит к краю ближе margin,
 *    картинка сдвигается ровно настолько, чтобы курсор остался на margin от края.
 */
public final class PcZoomMath {
    public static final float MIN_ZOOM = 1f;
    public static final float MAX_ZOOM = 5f;
    /** Двойной тап из 1× увеличивает до этого масштаба. */
    public static final float DOUBLE_TAP_ZOOM = 2.5f;
    /** Масштаб, начиная с которого картинка считается увеличенной. */
    public static final float ZOOMED_EPS = 1.01f;

    private float vw, vh;          // размер области просмотра
    private float bl, bt, bw, bh;  // картинка при 1×
    private float z = 1f, ox, oy;  // текущий масштаб и левый-верхний угол картинки

    public PcZoomMath() {}

    public PcZoomMath copy() {
        PcZoomMath m = new PcZoomMath();
        m.vw = vw; m.vh = vh; m.bl = bl; m.bt = bt; m.bw = bw; m.bh = bh;
        m.z = z; m.ox = ox; m.oy = oy;
        return m;
    }

    /**
     * Новая геометрия (поворот, Fit/Fill, изменение размера окна). Точка картинки,
     * которая была в центре экрана, остаётся в центре; при 1× — исходное положение.
     */
    public void setGeometry(float viewW, float viewH, float baseL, float baseT, float baseW, float baseH) {
        boolean had = vw > 0 && vh > 0 && bw > 0 && bh > 0;
        float cx = had ? toNormX(vw / 2f) : 0.5f;
        float cy = had ? toNormY(vh / 2f) : 0.5f;
        vw = Math.max(0f, viewW);
        vh = Math.max(0f, viewH);
        bl = baseL; bt = baseT;
        bw = Math.max(1f, baseW);
        bh = Math.max(1f, baseH);
        if (!had || z < ZOOMED_EPS) {
            reset();
        } else {
            ox = vw / 2f - cx * bw * z;
            oy = vh / 2f - cy * bh * z;
            clamp();
        }
    }

    public float zoom() { return z; }
    public float left() { return ox; }
    public float top() { return oy; }
    public float width() { return bw * z; }
    public float height() { return bh * z; }
    public float baseLeft() { return bl; }
    public float baseTop() { return bt; }
    public boolean isZoomed() { return z >= ZOOMED_EPS; }

    /** Масштаб 1×, исходное положение (как без лупы). */
    public void reset() {
        z = 1f;
        ox = bl;
        oy = bt;
    }

    /** Прямая установка состояния (кадры анимации); результат ограничивается. */
    public void set(float zoom, float left, float top) {
        z = zoom;
        ox = left;
        oy = top;
        clamp();
    }

    /** Масштаб newZoom так, что точка картинки под (fx, fy) остаётся под (fx, fy). */
    public void zoomAt(float newZoom, float fx, float fy) {
        float nz = clampZoom(newZoom);
        float k = nz / z;
        ox = fx - (fx - ox) * k;
        oy = fy - (fy - oy) * k;
        z = nz;
        clamp();
    }

    /**
     * Шаг щипка: центр пальцев переместился из (pcx, pcy) в (cx, cy), расстояние между
     * пальцами изменилось в factor раз. Масштаб вокруг старого центра + сдвиг за пальцами.
     */
    public void pinch(float pcx, float pcy, float cx, float cy, float factor) {
        if (!(factor > 0f) || Float.isInfinite(factor)) factor = 1f;
        float nz = clampZoom(z * factor);
        float k = nz / z;
        ox = cx - (pcx - ox) * k;
        oy = cy - (pcy - oy) * k;
        z = nz;
        clamp();
    }

    public void panBy(float dx, float dy) {
        ox += dx;
        oy += dy;
        clamp();
    }

    /** Двойной тап: из 1× — DOUBLE_TAP_ZOOM в точке касания, иначе — обратно 1×. */
    public void toggleAt(float fx, float fy) {
        if (isZoomed()) reset();
        else zoomAt(DOUBLE_TAP_ZOOM, fx, fy);
    }

    /** Экранная точка -> доля картинки ПК (0..1, может выходить за пределы вне картинки). */
    public float toNormX(float sx) { return (sx - ox) / (bw * z); }
    public float toNormY(float sy) { return (sy - oy) / (bh * z); }

    /** Доля картинки ПК -> экранная точка. */
    public float toScreenX(float nx) { return ox + nx * bw * z; }
    public float toScreenY(float ny) { return oy + ny * bh * z; }

    /**
     * Держит курсор ПК (nx, ny — доли картинки) не ближе marginPx к краям экрана.
     * Возвращает true, если картинку пришлось сдвинуть.
     */
    public boolean follow(float nx, float ny, float marginPx) {
        float px = ox, py = oy;
        float mx = Math.max(0f, Math.min(marginPx, vw / 2f - 1f));
        float my = Math.max(0f, Math.min(marginPx, vh / 2f - 1f));
        float sx = toScreenX(nx);
        float sy = toScreenY(ny);
        if (sx < mx) ox += mx - sx;
        else if (sx > vw - mx) ox -= sx - (vw - mx);
        if (sy < my) oy += my - sy;
        else if (sy > vh - my) oy -= sy - (vh - my);
        clamp();
        return Math.abs(ox - px) > 0.5f || Math.abs(oy - py) > 0.5f;
    }

    public static float clampZoom(float zoom) {
        if (Float.isNaN(zoom)) return MIN_ZOOM;
        return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
    }

    /** Ограничение по одной оси: картинка не уходит с экрана, меньшая — по центру. */
    public static float clampAxis(float origin, float size, float view) {
        if (size <= view) return (view - size) / 2f;
        return Math.max(view - size, Math.min(0f, origin));
    }

    private void clamp() {
        z = clampZoom(z);
        if (vw <= 0 || vh <= 0) return;
        // При ровно 1× меньшая сторона стоит в исходной позиции (центр с целыми пикселями разметки)
        ox = (z == 1f && bw <= vw) ? bl : clampAxis(ox, bw * z, vw);
        oy = (z == 1f && bh <= vh) ? bt : clampAxis(oy, bh * z, vh);
    }
}
