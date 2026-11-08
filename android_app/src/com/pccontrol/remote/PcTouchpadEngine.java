package com.pccontrol.remote;

/**
 * Touchpad gesture recognizer PC Control (pure Java, no android.* imports).
 *
 * Gesture rules adapted (re-implemented, not copied) from Moonlight's
 * RelativeTouchContext/AbsoluteTouchContext and the Windows precision touchpad:
 *   relative mode ("touchpad"):
 *     1 finger move ............ cursor move (sensitivity + optional acceleration,
 *                                sub-pixel remainder kept, no jumps when fingers change)
 *     1 finger tap ............. left click; two taps = double click (OS timing)
 *     tap, then touch+move ..... drag with the left button held (tap-and-drag)
 *     long press (no move) ..... left button held -> drag until lift
 *     2 finger tap ............. right click
 *     3 finger tap ............. middle click
 *     2 finger move ............ vertical + horizontal scroll (natural or inverted)
 *   absolute mode ("pen / direct touch" on the video):
 *     touch .................... cursor jumps to the finger
 *     tap ...................... left click at that point
 *     touch + move ............. drag with the left button held
 *     long press ............... right click
 *     2 finger move ............ scroll
 */
public final class PcTouchpadEngine {

    public interface Sink {
        void move(int dx, int dy);

        /** x, y normalised 0..1 inside the video viewport. */
        void moveAbs(float x, float y);

        void button(int button, boolean down);

        /** wheel units: 120 = one notch. */
        void scroll(int vertical, int horizontal);

        /** Haptic/visual feedback: 1 = drag started, 2 = right click by long press. */
        void feedback(int kind);
    }

    public interface Scheduler {
        void postDelayed(Runnable r, long delayMs);

        void cancel(Runnable r);
    }

    public static final int ACTION_DOWN = 0;
    public static final int ACTION_UP = 1;
    public static final int ACTION_MOVE = 2;
    public static final int ACTION_CANCEL = 3;
    public static final int ACTION_POINTER_DOWN = 5;
    public static final int ACTION_POINTER_UP = 6;

    // Thresholds (dp / ms)
    static final float TAP_SLOP_DP = 9f;
    static final long TAP_MAX_MS = 260;
    static final long LONG_PRESS_MS = 450;
    static final long ABS_LONG_PRESS_MS = 650;
    static final long TAP_DRAG_WINDOW_MS = 300;
    static final float TAP_DRAG_DISTANCE_DP = 40f;
    static final float BASE_PX_PER_DP = 1.6f;
    static final float SCROLL_DP_PER_NOTCH = 22f;

    private final Sink sink;
    private final Scheduler scheduler;

    // configuration
    private float density = 2f;          // px per dp
    private float sensitivity = 1f;
    private boolean acceleration = true;
    private float scrollSpeed = 1f;
    private boolean invertScroll = false;
    private boolean absolute = false;
    private float vpLeft, vpTop, vpWidth = 1, vpHeight = 1;

    // gesture state
    private boolean active = false;
    private int maxPointers = 0;
    private int primaryId = -1;
    private float lastX, lastY, downX, downY;
    private long downTime, lastMoveTime;
    private boolean moved = false;
    private boolean scrolling = false;
    private boolean dragging = false;
    private boolean longPressFired = false;
    private boolean tapDragCandidate = false;
    private float remX = 0f, remY = 0f;
    private float scrollRemV = 0f, scrollRemH = 0f;
    private float lastCx, lastCy;
    private long lastTapUpTime = -100000;
    private float lastTapX, lastTapY;
    private boolean buttonHeld = false;

    private final Runnable longPressRunnable = new Runnable() {
        @Override
        public void run() {
            if (!active || moved || scrolling || maxPointers != 1) return;
            longPressFired = true;
            if (absolute) {
                sink.button(PcInputProtocol.BUTTON_RIGHT, true);
                sink.button(PcInputProtocol.BUTTON_RIGHT, false);
                sink.feedback(2);
            } else {
                pressLeft();
                dragging = true;
                sink.feedback(1);
            }
        }
    };

    public PcTouchpadEngine(Sink sink, Scheduler scheduler) {
        this.sink = sink;
        this.scheduler = scheduler;
    }

    public void configure(float densityPxPerDp, float sens, boolean accel, float scrollSpd, boolean invert, boolean absMode) {
        density = Math.max(0.5f, densityPxPerDp);
        sensitivity = Math.max(0.1f, Math.min(5f, sens));
        acceleration = accel;
        scrollSpeed = Math.max(0.2f, Math.min(4f, scrollSpd));
        invertScroll = invert;
        if (absMode != absolute) {
            cancel();
            absolute = absMode;
        }
    }

    /** Video viewport in the same coordinates as the touch events (used by absolute mode). */
    public void setViewport(float left, float top, float width, float height) {
        vpLeft = left;
        vpTop = top;
        vpWidth = Math.max(1f, width);
        vpHeight = Math.max(1f, height);
    }

    public boolean isAbsolute() {
        return absolute;
    }

    public boolean isActive() {
        return active;
    }

    /**
     * Feeds one touch event. ids/xs/ys describe all pointers currently in the event
     * (like MotionEvent: for *_UP the lifting pointer is still included at actionIndex).
     */
    public void onTouch(int action, int actionIndex, int pointerCount, int[] ids, float[] xs, float[] ys, long timeMs) {
        switch (action) {
            case ACTION_DOWN:
                begin(ids[0], xs[0], ys[0], timeMs);
                break;
            case ACTION_POINTER_DOWN:
                if (!active) return;
                maxPointers = Math.max(maxPointers, pointerCount);
                scheduler.cancel(longPressRunnable);
                updateCentroid(pointerCount, xs, ys);
                break;
            case ACTION_MOVE:
                if (!active) return;
                handleMove(pointerCount, ids, xs, ys, timeMs);
                break;
            case ACTION_POINTER_UP: {
                if (!active) return;
                int liftingId = ids[actionIndex];
                if (liftingId == primaryId) {
                    // Hand over to a remaining finger without moving the cursor.
                    for (int i = 0; i < pointerCount; i++) {
                        if (i != actionIndex) {
                            primaryId = ids[i];
                            lastX = xs[i];
                            lastY = ys[i];
                            break;
                        }
                    }
                }
                updateCentroidExcluding(pointerCount, actionIndex, xs, ys);
                break;
            }
            case ACTION_UP:
                if (!active) return;
                finish(xs[0], ys[0], timeMs, false);
                break;
            case ACTION_CANCEL:
                cancel();
                break;
            default:
                break;
        }
    }

    /** Releases a held button (finger left the surface abnormally, view hidden, etc.). */
    public void cancel() {
        scheduler.cancel(longPressRunnable);
        if (buttonHeld) {
            buttonHeld = false;
            sink.button(PcInputProtocol.BUTTON_LEFT, false);
        }
        active = false;
        dragging = false;
    }

    /** Re-sends the held button after an input reconnect. */
    public void resync() {
        if (buttonHeld) sink.button(PcInputProtocol.BUTTON_LEFT, true);
    }

    // ------------------------------------------------------------------ internals
    private void begin(int id, float x, float y, long t) {
        scheduler.cancel(longPressRunnable);
        if (buttonHeld) {
            buttonHeld = false;
            sink.button(PcInputProtocol.BUTTON_LEFT, false);
        }
        active = true;
        maxPointers = 1;
        primaryId = id;
        lastX = downX = x;
        lastY = downY = y;
        lastCx = x;
        lastCy = y;
        downTime = lastMoveTime = t;
        moved = scrolling = dragging = longPressFired = false;
        remX = remY = 0f;
        scrollRemV = scrollRemH = 0f;
        float tapDist = dist(x - lastTapX, y - lastTapY) / density;
        tapDragCandidate = !absolute && (t - lastTapUpTime) <= TAP_DRAG_WINDOW_MS && tapDist <= TAP_DRAG_DISTANCE_DP;

        if (absolute) {
            boolean nearLastTap = (t - lastTapUpTime) <= 350 && dist(x - lastTapX, y - lastTapY) / density <= 30f;
            if (!nearLastTap) {
                // keep the cursor still for an easy double click, otherwise jump to the finger
                sink.moveAbs(normX(x), normY(y));
            }
            scheduler.postDelayed(longPressRunnable, ABS_LONG_PRESS_MS);
        } else {
            scheduler.postDelayed(longPressRunnable, LONG_PRESS_MS);
        }
    }

    private void handleMove(int pointerCount, int[] ids, float[] xs, float[] ys, long t) {
        int idx = indexOf(ids, pointerCount, primaryId);
        if (idx < 0) {
            primaryId = ids[0];
            lastX = xs[0];
            lastY = ys[0];
            return;
        }
        float x = xs[idx], y = ys[idx];

        if (!moved && dist(x - downX, y - downY) / density > TAP_SLOP_DP) {
            moved = true;
            scheduler.cancel(longPressRunnable);
            if (absolute && maxPointers == 1 && !longPressFired) {
                pressLeft();
                dragging = true;
            } else if (tapDragCandidate && maxPointers == 1 && !dragging) {
                pressLeft();
                dragging = true;
            }
        }

        if (pointerCount >= 2 && !dragging) {
            handleScroll(pointerCount, xs, ys);
            lastX = x;
            lastY = y;
            lastMoveTime = t;
            return;
        }

        if (absolute) {
            if (moved) sink.moveAbs(normX(x), normY(y));
        } else {
            float dxDp = (x - lastX) / density;
            float dyDp = (y - lastY) / density;
            long dt = Math.max(1, t - lastMoveTime);
            float gain = sensitivity;
            if (acceleration) {
                float speed = (float) Math.sqrt(dxDp * dxDp + dyDp * dyDp) / dt; // dp per ms
                gain *= Math.max(0.6f, Math.min(3.0f, 0.6f + 1.1f * speed));
            }
            remX += dxDp * BASE_PX_PER_DP * gain;
            remY += dyDp * BASE_PX_PER_DP * gain;
            int ix = (int) remX;
            int iy = (int) remY;
            if (ix != 0 || iy != 0) {
                remX -= ix;
                remY -= iy;
                sink.move(ix, iy);
            }
        }
        lastX = x;
        lastY = y;
        lastMoveTime = t;
    }

    private void handleScroll(int pointerCount, float[] xs, float[] ys) {
        float cx = 0, cy = 0;
        int n = Math.min(pointerCount, 2);
        for (int i = 0; i < n; i++) {
            cx += xs[i];
            cy += ys[i];
        }
        cx /= n;
        cy /= n;
        float dxDp = (cx - lastCx) / density;
        float dyDp = (cy - lastCy) / density;
        lastCx = cx;
        lastCy = cy;
        if (!scrolling) {
            if (moved) {
                scrolling = true;
                scheduler.cancel(longPressRunnable);
            } else {
                return;
            }
        }
        float unitsPerDp = PcInputProtocol.WHEEL_DELTA / SCROLL_DP_PER_NOTCH * scrollSpeed;
        float sign = invertScroll ? -1f : 1f;
        // Natural scrolling: content follows the fingers (finger up -> scroll down).
        scrollRemV += dyDp * unitsPerDp * sign;
        scrollRemH += -dxDp * unitsPerDp * sign;
        int v = (int) scrollRemV;
        int h = (int) scrollRemH;
        if (Math.abs(h) < Math.abs(v) / 2) h = 0;      // lock to the dominant axis
        else if (Math.abs(v) < Math.abs(h) / 2) v = 0;
        if (v != 0 || h != 0) {
            scrollRemV -= v;
            scrollRemH -= h;
            sink.scroll(v, h);
        }
    }

    private void finish(float x, float y, long t, boolean cancelled) {
        scheduler.cancel(longPressRunnable);
        active = false;
        if (dragging || buttonHeld) {
            dragging = false;
            if (buttonHeld) {
                buttonHeld = false;
                sink.button(PcInputProtocol.BUTTON_LEFT, false);
            }
            return;
        }
        if (cancelled || moved || scrolling || longPressFired) return;
        if (t - downTime > TAP_MAX_MS) return;
        int button;
        if (maxPointers >= 3) button = PcInputProtocol.BUTTON_MIDDLE;
        else if (maxPointers == 2) button = PcInputProtocol.BUTTON_RIGHT;
        else button = PcInputProtocol.BUTTON_LEFT;
        if (absolute && button == PcInputProtocol.BUTTON_LEFT) {
            boolean nearLastTap = (downTime - lastTapUpTime) <= 350 && dist(x - lastTapX, y - lastTapY) / density <= 30f;
            if (!nearLastTap) sink.moveAbs(normX(downX), normY(downY));
        }
        sink.button(button, true);
        sink.button(button, false);
        if (button == PcInputProtocol.BUTTON_LEFT) {
            lastTapUpTime = t;
            lastTapX = x;
            lastTapY = y;
        } else {
            lastTapUpTime = -100000;
        }
    }

    private void pressLeft() {
        if (!buttonHeld) {
            buttonHeld = true;
            sink.button(PcInputProtocol.BUTTON_LEFT, true);
        }
    }

    private void updateCentroid(int pointerCount, float[] xs, float[] ys) {
        float cx = 0, cy = 0;
        int n = Math.min(pointerCount, 2);
        for (int i = 0; i < n; i++) {
            cx += xs[i];
            cy += ys[i];
        }
        lastCx = cx / n;
        lastCy = cy / n;
    }

    private void updateCentroidExcluding(int pointerCount, int excluded, float[] xs, float[] ys) {
        float cx = 0, cy = 0;
        int n = 0;
        for (int i = 0; i < pointerCount && n < 2; i++) {
            if (i == excluded) continue;
            cx += xs[i];
            cy += ys[i];
            n++;
        }
        if (n > 0) {
            lastCx = cx / n;
            lastCy = cy / n;
        }
    }

    private float normX(float x) {
        return Math.max(0f, Math.min(1f, (x - vpLeft) / vpWidth));
    }

    private float normY(float y) {
        return Math.max(0f, Math.min(1f, (y - vpTop) / vpHeight));
    }

    private static int indexOf(int[] ids, int count, int id) {
        for (int i = 0; i < count; i++) {
            if (ids[i] == id) return i;
        }
        return -1;
    }

    private static float dist(float dx, float dy) {
        return (float) Math.sqrt(dx * dx + dy * dy);
    }
}
