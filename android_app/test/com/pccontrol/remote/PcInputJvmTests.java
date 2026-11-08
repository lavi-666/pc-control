package com.pccontrol.remote;

import java.util.ArrayList;
import java.util.List;

/**
 * Desktop-JVM tests of the Android input code that has no android.* dependencies
 * (PcTouchpadEngine, PcKeyboardLogic, PcInputProtocol, PcInputClient).
 * Run by scripts/test_android_input_logic.py; no JUnit needed.
 *
 *   java PcInputJvmTests              -> logic tests
 *   java PcInputJvmTests e2e URL TOKEN -> real PcInputClient against a running server
 */
public final class PcInputJvmTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    // ------------------------------------------------------------------ fakes
    static final class FakeScheduler implements PcTouchpadEngine.Scheduler {
        final List<Runnable> tasks = new ArrayList<>();
        final List<Long> due = new ArrayList<>();
        long now = 0;

        public void postDelayed(Runnable r, long ms) {
            tasks.add(r);
            due.add(now + ms);
        }

        public void cancel(Runnable r) {
            for (int i = tasks.size() - 1; i >= 0; i--) {
                if (tasks.get(i) == r) {
                    tasks.remove(i);
                    due.remove(i);
                }
            }
        }

        void advance(long ms) {
            now += ms;
            for (int i = 0; i < tasks.size(); ) {
                if (due.get(i) <= now) {
                    Runnable r = tasks.remove(i);
                    due.remove(i);
                    r.run();
                } else {
                    i++;
                }
            }
        }
    }

    static final class Rec implements PcTouchpadEngine.Sink, PcKeyboardLogic.Output {
        final List<String> ev = new ArrayList<>();
        final List<int[]> moveList = new ArrayList<>();
        int moveX = 0, moveY = 0, moves = 0, scrollV = 0, scrollH = 0, changes = 0, hides = 0;

        public void move(int dx, int dy) {
            moveX += dx;
            moveY += dy;
            moves++;
            moveList.add(new int[] {dx, dy});
        }

        public void moveAbs(float x, float y) {
            ev.add(String.format("abs %.2f %.2f", x, y));
        }

        public void button(int b, boolean down) {
            ev.add("btn " + b + (down ? " down" : " up"));
        }

        public void scroll(int v, int h) {
            scrollV += v;
            scrollH += h;
        }

        public void feedback(int kind) {
            ev.add("feedback " + kind);
        }

        public void key(int vk, boolean down) {
            ev.add(String.format("key %02X %s", vk, down ? "down" : "up"));
        }

        public void unicode(int cp, boolean down) {
            ev.add("uni " + new String(Character.toChars(cp)) + (down ? " down" : " up"));
        }

        public void hotkey(int[] vks) {
            StringBuilder sb = new StringBuilder("hotkey");
            for (int v : vks) sb.append(String.format(" %02X", v));
            ev.add(sb.toString());
        }

        public void onKeyboardChanged() {
            changes++;
        }

        public void onHideRequested() {
            hides++;
        }

        List<String> buttons() {
            List<String> r = new ArrayList<>();
            for (String s : ev) if (s.startsWith("btn")) r.add(s);
            return r;
        }
    }

    // ------------------------------------------------------------------ touch helpers
    static final float D = 2f; // density
    static FakeScheduler sch;
    static Rec rec;
    static PcTouchpadEngine tp;

    static void newTouchpad(boolean abs) {
        sch = new FakeScheduler();
        rec = new Rec();
        tp = new PcTouchpadEngine(rec, sch);
        tp.configure(D, 1f, false, 1f, false, abs);
        tp.setViewport(0, 0, 1000, 500);
    }

    static void t1(int action, float x, float y) {
        tp.onTouch(action, 0, 1, new int[] {0}, new float[] {x}, new float[] {y}, sch.now);
    }

    static void t2(int action, int idx, float x0, float y0, float x1, float y1) {
        tp.onTouch(action, idx, 2, new int[] {0, 1}, new float[] {x0, x1}, new float[] {y0, y1}, sch.now);
    }

    static void tap(float x, float y, long holdMs) {
        t1(PcTouchpadEngine.ACTION_DOWN, x, y);
        sch.advance(holdMs);
        t1(PcTouchpadEngine.ACTION_UP, x, y);
    }

    // ------------------------------------------------------------------ touchpad tests
    static void testTapIsLeftClick() {
        newTouchpad(false);
        tap(100, 100, 80);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up"), "tap = left click");
    }

    static void testDoubleTapIsTwoClicks() {
        newTouchpad(false);
        tap(100, 100, 70);
        sch.advance(90);
        tap(102, 101, 70);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up", "btn 1 down", "btn 1 up"), "double tap = double click");
    }

    static void testMoveIsRelativeAndNoClick() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        for (int i = 1; i <= 10; i++) {
            sch.advance(8);
            t1(PcTouchpadEngine.ACTION_MOVE, 100 + i * 10, 100 + i * 4);
        }
        t1(PcTouchpadEngine.ACTION_UP, 200, 140);
        // 100 px = 50 dp -> 80 px at sensitivity 1, accel off; 40 px = 20 dp -> 32 px
        check(Math.abs(rec.moveX - 80) <= 1 && Math.abs(rec.moveY - 32) <= 1,
                "relative move scaled 1.6 px/dp: got " + rec.moveX + "," + rec.moveY);
        eq(rec.buttons(), list(), "move does not click");
    }

    static void testSubPixelMovementIsNotLost() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        float x = 100;
        for (int i = 0; i < 100; i++) {
            x += 0.5f; // 0.25 dp per event: rounds to 0 each time if not accumulated
            sch.advance(8);
            t1(PcTouchpadEngine.ACTION_MOVE, x, 100);
        }
        // total 50 px = 25 dp -> 40 px
        check(Math.abs(rec.moveX - 40) <= 1, "sub-pixel accumulation: got " + rec.moveX);
    }

    static void testLongPressDrag() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        sch.advance(500);
        t1(PcTouchpadEngine.ACTION_MOVE, 160, 100);
        t1(PcTouchpadEngine.ACTION_UP, 160, 100);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up"), "long press -> drag holds left button until lift");
        check(rec.moveX > 0, "cursor moved while dragging");
        check(rec.ev.contains("feedback 1"), "drag start feedback");
    }

    static void testTapAndDrag() {
        newTouchpad(false);
        tap(100, 100, 60);
        sch.advance(120);
        t1(PcTouchpadEngine.ACTION_DOWN, 105, 100);
        sch.advance(30);
        t1(PcTouchpadEngine.ACTION_MOVE, 180, 120);
        sch.advance(30);
        t1(PcTouchpadEngine.ACTION_UP, 180, 120);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up", "btn 1 down", "btn 1 up"), "tap-and-drag");
        check(rec.moveX > 0, "tap-and-drag moves the cursor");
    }

    static void testTwoFingerTapIsRightClick() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        sch.advance(20);
        t2(PcTouchpadEngine.ACTION_POINTER_DOWN, 1, 100, 100, 160, 100);
        sch.advance(60);
        t2(PcTouchpadEngine.ACTION_POINTER_UP, 1, 100, 100, 160, 100);
        t1(PcTouchpadEngine.ACTION_UP, 100, 100);
        eq(rec.buttons(), list("btn 2 down", "btn 2 up"), "two finger tap = right click only");
    }

    static void testThreeFingerTapIsMiddleClick() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        tp.onTouch(PcTouchpadEngine.ACTION_POINTER_DOWN, 2, 3, new int[] {0, 1, 2},
                new float[] {100, 150, 200}, new float[] {100, 100, 100}, sch.now);
        sch.advance(80);
        tp.onTouch(PcTouchpadEngine.ACTION_POINTER_UP, 2, 3, new int[] {0, 1, 2},
                new float[] {100, 150, 200}, new float[] {100, 100, 100}, sch.now);
        t2(PcTouchpadEngine.ACTION_POINTER_UP, 1, 100, 100, 150, 100);
        t1(PcTouchpadEngine.ACTION_UP, 100, 100);
        eq(rec.buttons(), list("btn 3 down", "btn 3 up"), "three finger tap = middle click");
    }

    static void testTwoFingerScroll() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 300);
        t2(PcTouchpadEngine.ACTION_POINTER_DOWN, 1, 100, 300, 160, 300);
        for (int i = 1; i <= 20; i++) {
            sch.advance(10);
            t2(PcTouchpadEngine.ACTION_MOVE, 0, 100, 300 - i * 4.4f, 160, 300 - i * 4.4f);
        }
        t2(PcTouchpadEngine.ACTION_POINTER_UP, 1, 100, 212, 160, 212);
        t1(PcTouchpadEngine.ACTION_UP, 100, 212);
        // fingers up by 88 px = 44 dp; the first 9 dp are the tap slop -> 35 dp = ~1.6 notches (~191 units).
        // Natural scrolling: fingers up = wheel down (negative).
        check(rec.scrollV <= -180 && rec.scrollV >= -200, "two finger scroll: " + rec.scrollV);
        check(rec.moveX == 0 && rec.moveY == 0, "scroll does not move the cursor");
        eq(rec.buttons(), list(), "scroll does not click");
    }

    static void testInvertScroll() {
        newTouchpad(false);
        tp.configure(D, 1f, false, 1f, true, false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 300);
        t2(PcTouchpadEngine.ACTION_POINTER_DOWN, 1, 100, 300, 160, 300);
        for (int i = 1; i <= 10; i++) {
            sch.advance(10);
            t2(PcTouchpadEngine.ACTION_MOVE, 0, 100, 300 - i * 8, 160, 300 - i * 8);
        }
        check(rec.scrollV > 0, "inverted scroll direction: " + rec.scrollV);
    }

    static void testPrimaryFingerLiftDoesNotJump() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        t2(PcTouchpadEngine.ACTION_POINTER_DOWN, 1, 100, 100, 600, 400);
        // primary (id 0) lifts, id 1 stays at a far position
        t2(PcTouchpadEngine.ACTION_POINTER_UP, 0, 100, 100, 600, 400);
        tp.onTouch(PcTouchpadEngine.ACTION_MOVE, 0, 1, new int[] {1}, new float[] {602}, new float[] {400}, sch.now + 10);
        check(Math.abs(rec.moveX) <= 3 && Math.abs(rec.moveY) <= 3, "no jump on finger hand-over: " + rec.moveX + "," + rec.moveY);
    }

    static void testCancelReleasesDrag() {
        newTouchpad(false);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        sch.advance(500);
        t1(PcTouchpadEngine.ACTION_CANCEL, 100, 100);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up"), "cancel releases held button");
    }

    static void testAccelerationFasterMovesFurther() {
        newTouchpad(false);
        tp.configure(D, 1f, true, 1f, false, false);
        t1(PcTouchpadEngine.ACTION_DOWN, 0, 0);
        for (int i = 1; i <= 10; i++) { sch.advance(20); t1(PcTouchpadEngine.ACTION_MOVE, i * 4, 0); }
        int slow = rec.moveX;
        t1(PcTouchpadEngine.ACTION_UP, 40, 0);
        newTouchpad(false);
        tp.configure(D, 1f, true, 1f, false, false);
        t1(PcTouchpadEngine.ACTION_DOWN, 0, 0);
        for (int i = 1; i <= 2; i++) { sch.advance(8); t1(PcTouchpadEngine.ACTION_MOVE, i * 20, 0); }
        int fast = rec.moveX;
        check(fast > slow, "acceleration: fast flick (" + fast + ") > slow move (" + slow + ") for same distance");
    }

    static void testAbsoluteTapClicksAtPoint() {
        newTouchpad(true);
        tap(250, 125, 60);
        check(rec.ev.get(0).equals("abs 0.25 0.25"), "absolute: cursor jumps to finger: " + rec.ev);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up"), "absolute tap = click");
    }

    static void testAbsoluteDragAndLongPressRightClick() {
        newTouchpad(true);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        sch.advance(20);
        t1(PcTouchpadEngine.ACTION_MOVE, 300, 200);
        t1(PcTouchpadEngine.ACTION_UP, 300, 200);
        eq(rec.buttons(), list("btn 1 down", "btn 1 up"), "absolute drag holds left button");
        check(rec.ev.contains("abs 0.30 0.40"), "absolute drag follows finger");
        newTouchpad(true);
        t1(PcTouchpadEngine.ACTION_DOWN, 100, 100);
        sch.advance(700);
        t1(PcTouchpadEngine.ACTION_UP, 100, 100);
        eq(rec.buttons(), list("btn 2 down", "btn 2 up"), "absolute long press = right click");
    }

    // ------------------------------------------------------------------ keyboard tests
    static PcKeyboardLogic kb;
    static Rec krec;

    static void newKeyboard() {
        krec = new Rec();
        kb = new PcKeyboardLogic(krec);
    }

    static PcKeyboardLogic.Key find(String label) {
        for (PcKeyboardLogic.Key[] row : kb.rows()) {
            for (PcKeyboardLogic.Key k : row) {
                if (k.label.equals(label)) return k;
            }
        }
        throw new AssertionError("no key " + label);
    }

    static void tapKey(String label) {
        kb.release(kb.press(find(label)));
    }

    static void testTypingUnicodeEnRuUk() {
        newKeyboard();
        tapKey("h");
        tapKey("i");
        kb.setLang(PcKeyboardLogic.LANG_RU);
        tapKey("ж");
        tapKey("ё");
        kb.setLang(PcKeyboardLogic.LANG_UK);
        tapKey("ї");
        tapKey("ґ");
        tapKey("є");
        eq(krec.ev, list("uni h down", "uni h up", "uni i down", "uni i up", "uni ж down", "uni ж up",
                "uni ё down", "uni ё up", "uni ї down", "uni ї up", "uni ґ down", "uni ґ up", "uni є down", "uni є up"),
                "unicode typing EN/RU/UK with press+release");
    }

    static void testShiftOneShotAndCaps() {
        newKeyboard();
        tapKey("⇧");
        tapKey("a");
        tapKey("b");
        eq(krec.ev, list("key A0 down", "uni A down", "uni A up", "key A0 up", "uni b down", "uni b up"),
                "shift tap = one-shot uppercase");
        newKeyboard();
        tapKey("⇧");
        tapKey("⇧");          // lock = caps
        tapKey("a");
        tapKey("1");
        tapKey("⇧");          // off
        tapKey("a");
        eq(krec.ev, list("key A0 down", "key A0 up", "uni A down", "uni A up", "uni 1 down", "uni 1 up", "uni a down", "uni a up"),
                "shift double tap = caps lock (letters only), third tap off");
        newKeyboard();
        tapKey("⇧");
        tapKey("2");
        eq(krec.ev.get(1), "uni @ down", "shift + 2 = @ on EN");
        newKeyboard();
        kb.setLang(PcKeyboardLogic.LANG_RU);
        tapKey("⇧");
        tapKey("3");
        eq(krec.ev.get(1), "uni № down", "shift + 3 = № on RU");
    }

    static void testCtrlCOnAnyLayoutUsesPhysicalKey() {
        newKeyboard();
        kb.setLang(PcKeyboardLogic.LANG_RU);
        tapKey("Ctrl");
        tapKey("с");    // Cyrillic es, physical C
        tapKey("в");    // ctrl already released (one-shot) -> plain Unicode
        eq(krec.ev, list("key A2 down", "key 43 down", "key 43 up", "key A2 up", "uni в down", "uni в up"),
                "Ctrl one-shot + RU 'с' = Ctrl+C by physical key");
    }

    static void testHeldModifierChord() {
        newKeyboard();
        PcKeyboardLogic.Press ctrl = kb.press(find("Ctrl"));
        PcKeyboardLogic.Press shift = kb.press(find("⇧"));
        tapKey("t");
        kb.release(shift);
        kb.release(ctrl);
        eq(krec.ev, list("key A2 down", "key A0 down", "key 54 down", "key 54 up", "key A0 up", "key A2 up"),
                "hold Ctrl + hold Shift + T = Ctrl+Shift+T, released with the fingers");
        check(kb.getModState(PcKeyboardLogic.MOD_CTRL) == PcKeyboardLogic.ST_OFF, "chord does not latch ctrl");
    }

    static void testLockedAltStaysUntilTapped() {
        newKeyboard();
        tapKey("Alt");
        tapKey("Alt");      // locked
        tapKey("Tab");
        tapKey("Tab");
        tapKey("Alt");      // unlock
        eq(krec.ev, list("key A4 down", "key 09 down", "key 09 up", "key 09 down", "key 09 up", "key A4 up"),
                "locked Alt + Tab Tab (window switcher), released on third tap");
    }

    static void testWinAloneOpensStart() {
        newKeyboard();
        tapKey("Win");
        tapKey("Win");
        tapKey("Win");
        eq(krec.ev, list("key 5B down", "key 5B up"), "Win tap/lock/off sends a lone Win press");
    }

    static void testHoldReleasesOnLift() {
        newKeyboard();
        PcKeyboardLogic.Press bs = kb.press(find("⌫"));
        eq(krec.ev, list("key 08 down"), "backspace down on touch (server autorepeats)");
        kb.release(bs);
        eq(krec.ev, list("key 08 down", "key 08 up"), "backspace up on lift");
    }

    static void testReleaseAllNoStuckKeys() {
        newKeyboard();
        kb.press(find("Ctrl"));
        kb.press(find("x"));
        kb.press(find("⌫"));
        tapKey("Alt");
        kb.releaseAll();
        int downs = 0, ups = 0;
        for (String e : krec.ev) {
            if (e.endsWith("down")) downs++;
            if (e.endsWith("up")) ups++;
        }
        check(downs == ups, "releaseAll balances every down with an up: " + krec.ev);
    }

    static void testFnLayerHotkeysAndFKeys() {
        newKeyboard();
        tapKey("Fn");
        tapKey("F5");
        tapKey("Ctrl+V");
        tapKey("Alt+Tab");
        eq(krec.ev, list("key 74 down", "key 74 up", "hotkey A2 56", "hotkey A4 09"), "Fn layer F5 and hotkeys");
    }

    static void testGameKeysMode() {
        newKeyboard();
        kb.setGameKeys(true);
        tapKey("w");
        eq(krec.ev, list("key 57 down", "key 57 up"), "game keys mode sends physical VK");
    }

    static void testSymbolsLayer() {
        newKeyboard();
        tapKey("123");
        tapKey("€");
        tapKey("\\");
        tapKey("ABC");
        tapKey("q");
        eq(krec.ev, list("uni € down", "uni € up", "uni \\ down", "uni \\ up", "uni q down", "uni q up"), "symbols layer");
    }

    static void testHideKey() {
        newKeyboard();
        tapKey("⌄");
        check(krec.hides == 1, "hide key requests hide on release");
    }

    static void testProtocolEncoding() {
        byte[] f = PcInputProtocol.mouseRel(-2, 300);
        eq(hex(f), "10 00 04 00 FE FF 2C 01", "mouse rel frame");
        eq(hex(PcInputProtocol.key(0x26, true, true)), "20 00 04 00 26 00 01 01", "key frame");
        eq(hex(PcInputProtocol.unicode(0x1F600, false)), "21 00 05 00 00 F6 01 00 00", "unicode frame");
        eq(hex(PcInputProtocol.hotkey(new int[] {0xA2, 0x43})), "23 00 05 00 02 A2 00 43 00", "hotkey frame");
        eq(PcInputClient.jsonString("a\"b\\c\n"), "\"a\\\"b\\\\c\\u000a\"", "json escaping (backslash key bug)");
    }

    // ------------------------------------------------------------------ E2E with the real server
    static void e2e(String url, String token) throws Exception {
        PcInputClient c = new PcInputClient();
        final int[] sessions = {0};
        final List<Integer> states = new ArrayList<>();
        c.setListener(new PcInputClient.Listener() {
            public void onInputStateChanged(int state, String detail) {
                synchronized (states) { states.add(state); }
            }

            public void onInputSessionStarted() {
                synchronized (sessions) { sessions[0]++; }
            }
        });
        c.configure(url, token);
        c.start();
        long deadline = System.currentTimeMillis() + 5000;
        while (c.getState() != PcInputClient.STATE_CONNECTED && System.currentTimeMillis() < deadline) Thread.sleep(5);
        check(c.getState() == PcInputClient.STATE_CONNECTED, "client connected, state=" + c.getState() + " " + c.getStateDetail());
        // 200 tiny moves in a burst: must be coalesced into far fewer frames, same total
        for (int i = 0; i < 200; i++) c.mouseMove(1, -1);
        c.mouseButton(PcInputProtocol.BUTTON_LEFT, true);
        c.mouseButton(PcInputProtocol.BUTTON_LEFT, false);
        c.scroll(-60, 0);
        c.scroll(-60, 0);
        c.key(PcInputProtocol.VK_LCONTROL, true);
        c.key('C', true);
        c.key('C', false);
        c.key(PcInputProtocol.VK_LCONTROL, false);
        c.unicode(0x0416, true);
        c.unicode(0x0416, false);
        c.text("Привіт, 世界 😀");
        c.hotkey(new int[] {PcInputProtocol.VK_LMENU, PcInputProtocol.VK_TAB});
        c.mouseAbs(0.5f, 0.25f, 1);
        c.key(PcInputProtocol.VK_BACK, true);   // held across the heartbeat interval
        Thread.sleep(1600);
        c.key(PcInputProtocol.VK_BACK, false);
        Thread.sleep(150);
        c.stop();
        Thread.sleep(300);
        System.out.println("E2E_FRAMES_SENT=" + c.framesSent + " CHUNKS=" + c.chunksSent + " SESSIONS=" + sessions[0]);
    }

    /** Connection drop in the middle of a held key: reconnect + resync (like the UI does). */
    static void reconnect(String url, String token) throws Exception {
        final PcInputClient c = new PcInputClient();
        final boolean[] held = {false};
        final int[] sessions = {0};
        c.setListener(new PcInputClient.Listener() {
            public void onInputStateChanged(int state, String detail) {}

            public void onInputSessionStarted() {
                synchronized (sessions) { sessions[0]++; }
                if (held[0]) c.key('A', true); // UI resync of keys still under the finger
            }
        });
        c.configure(url, token);
        c.start();
        long deadline = System.currentTimeMillis() + 5000;
        while (c.getState() != PcInputClient.STATE_CONNECTED && System.currentTimeMillis() < deadline) Thread.sleep(5);
        held[0] = true;
        c.key('A', true);
        System.out.println("READY_HELD");
        System.out.flush();
        deadline = System.currentTimeMillis() + 10000;
        while (System.currentTimeMillis() < deadline) {
            synchronized (sessions) { if (sessions[0] >= 2) break; }
            Thread.sleep(10);
        }
        Thread.sleep(300);
        held[0] = false;
        c.key('A', false);
        Thread.sleep(200);
        c.stop();
        Thread.sleep(300);
        synchronized (sessions) { check(sessions[0] == 2, "reconnected once, sessions=" + sessions[0]); }
        System.out.println("RECONNECT_SESSIONS=" + sessions[0]);
    }

    // ------------------------------------------------------------------ tiny assert lib
    static List<String> list(String... s) {
        List<String> l = new ArrayList<>();
        for (String x : s) l.add(x);
        return l;
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < b.length; i++) {
            if (i > 0) sb.append(' ');
            sb.append(String.format("%02X", b[i] & 0xFF));
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ smoothness / icons
    /**
     * Regression (jerky cursor): a steady finger with millisecond-jittered event timestamps
     * (vsync batching, whole-ms getEventTime) must give an even cursor step when pointer
     * acceleration is on. Before the fix the raw per-event speed drove the gain directly.
     */
    static double accelStepDeviation(long seed) {
        sch = new FakeScheduler();
        rec = new Rec();
        tp = new PcTouchpadEngine(rec, sch);
        tp.configure(D, 1f, true, 1f, false, false);
        final double speedDpPerMs = 1.5;
        final double frameMs = 1000.0 / 120.0;
        long rnd = seed;
        tp.onTouch(PcTouchpadEngine.ACTION_DOWN, 0, 1, new int[] {0}, new float[] {100}, new float[] {300}, 1000);
        int n = 120;
        for (int i = 1; i <= n; i++) {
            double trueT = 1000 + i * frameMs;
            rnd = rnd * 6364136223846793005L + 1442695040888963407L;
            double jitter = ((rnd >>> 33) % 4001) / 1000.0 - 2.0; // +-2 ms
            long evT = (long) Math.floor(trueT + jitter);
            float x = (float) (100 + speedDpPerMs * D * (trueT - 1000));
            tp.onTouch(PcTouchpadEngine.ACTION_MOVE, 0, 1, new int[] {0}, new float[] {x}, new float[] {300}, evT);
        }
        tp.onTouch(PcTouchpadEngine.ACTION_UP, 0, 1, new int[] {0}, new float[] {0}, new float[] {300}, 1000 + (long) (n * frameMs) + 5);
        // steady state: skip the first 15 events, compare per-event steps with their mean
        List<int[]> m = rec.moveList;
        double sum = 0, sq = 0;
        int cnt = 0;
        for (int i = 15; i < m.size(); i++) {
            sum += m.get(i)[0];
            cnt++;
        }
        double mean = sum / cnt;
        for (int i = 15; i < m.size(); i++) {
            double d = m.get(i)[0] - mean;
            sq += d * d;
        }
        return Math.sqrt(sq / cnt) / mean;
    }

    static void testAccelerationIsSmoothUnderTimestampJitter() {
        double worst = 0;
        for (long seed = 1; seed <= 5; seed++) worst = Math.max(worst, accelStepDeviation(seed));
        System.out.println(String.format("  accel step deviation (rms/mean, worst of 5): %.3f", worst));
        check(worst < 0.06, "cursor step uneven under timestamp jitter: rms/mean=" + worst);
    }

    static final class BoundsSink implements PcSvgPath.Sink {
        float minX = Float.MAX_VALUE, minY = Float.MAX_VALUE, maxX = -Float.MAX_VALUE, maxY = -Float.MAX_VALUE;
        int segments = 0;
        float lastX, lastY;

        void add(float x, float y) {
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
        }

        public void moveTo(float x, float y) { add(x, y); lastX = x; lastY = y; }
        public void lineTo(float x, float y) { add(x, y); segments++; lastX = x; lastY = y; }
        public void cubicTo(float x1, float y1, float x2, float y2, float x, float y) {
            add(x1, y1);
            add(x2, y2);
            add(x, y);
            segments++;
            lastX = x;
            lastY = y;
        }
        public void close() { segments++; }
    }

    static void testIconsParseAndFitViewBox() {
        String[][] all = PcIcons.all();
        int ok = 0;
        for (String[] icon : all) {
            check("F".equals(icon[0]) || "S".equals(icon[0]), "icon style marker");
            BoundsSink b = new BoundsSink();
            try {
                for (int i = 1; i < icon.length; i++) PcSvgPath.parse(icon[i], b);
            } catch (RuntimeException e) {
                failures.add("icon parse failed: " + e);
                continue;
            }
            if (b.segments > 0 && b.minX >= -0.6f && b.minY >= -0.6f && b.maxX <= 24.6f && b.maxY <= 24.6f) ok++;
            else failures.add("icon outside 24x24 viewBox: " + b.minX + "," + b.minY + " .. " + b.maxX + "," + b.maxY + " " + icon[1].substring(0, 20));
        }
        check(ok == all.length, "all " + all.length + " icons parse and fit the viewBox (" + ok + ")");
    }

    static void testSvgArcsAndCompactNumbers() {
        // circle r=3 around (12,12) written with two arcs
        BoundsSink c = new BoundsSink();
        PcSvgPath.parse("M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0z", c);
        check(Math.abs(c.minX - 9) < 0.05 && Math.abs(c.maxX - 15) < 0.05
                && Math.abs(c.minY - 9) < 1.4 && Math.abs(c.maxY - 15) < 1.4, "arc circle bounds "
                + c.minX + "," + c.minY + " " + c.maxX + "," + c.maxY);
        // compact arc flags + numbers without separators ("a.998.998 0 0 0-.98-.85", "001")
        BoundsSink m = new BoundsSink();
        PcSvgPath.parse("M5 5a.998.998 0 0 0-.98-.85M1 1a1 1 0 001 1", m);
        check(Math.abs(m.lastX - 2) < 1e-3 && Math.abs(m.lastY - 2) < 1e-3, "compact arc flags end point " + m.lastX + "," + m.lastY);
        BoundsSink r = new BoundsSink();
        PcSvgPath.parse("M1-.5.5.5l1e1 0h-2v.25z", r);
        // M1 -0.5, implicit L .5 .5, l 10 0 -> 10.5, h -2 -> 8.5, v .25 -> 0.75
        check(Math.abs(r.lastX - 8.5) < 1e-4 && Math.abs(r.lastY - 0.75) < 1e-4, "compact numbers " + r.lastX + "," + r.lastY);
        boolean threw = false;
        try {
            PcSvgPath.parse("M1 1 a1 1 0 2 1 2 2", new BoundsSink());
        } catch (IllegalArgumentException e) {
            threw = true;
        }
        check(threw, "invalid arc flag rejected");
    }

    // ---- Громкость демонстрации 0–200 % (PcAudioGain) --------------------------------
    static byte[] pcm(short... s) {
        byte[] b = new byte[s.length * 2];
        for (int i = 0; i < s.length; i++) { b[2 * i] = (byte) s[i]; b[2 * i + 1] = (byte) (s[i] >> 8); }
        return b;
    }

    static short sampleAt(byte[] b, int i) {
        return (short) (((b[2 * i + 1]) << 8) | (b[2 * i] & 0xFF));
    }

    static void testAudioGainAmplifiesUpTo200Percent() {
        check(PcAudioGain.percentToGain(200, false) == 2f, "200% -> gain 2.0");
        check(PcAudioGain.percentToGain(500, false) == 2f, "gain clamped to 200%");
        check(PcAudioGain.percentToGain(150, true) == 0f, "muted -> 0");

        // Тихий сигнал при 200 % — реально вдвое громче (а не просто цифра на ползунке)
        PcAudioGain g = new PcAudioGain();
        byte[] b = pcm((short) 1000, (short) -1000, (short) 4000, (short) -4000);
        g.apply(b, b.length, 2f);
        check(Math.abs(sampleAt(b, 0) - 2000) <= 1 && Math.abs(sampleAt(b, 1) + 2000) <= 1, "quiet signal doubled at 200%");
        check(Math.abs(sampleAt(b, 2) - 8000) <= 1, "4000 -> 8000 at 200%");

        // До 100 % — только линейное ослабление, без искажений
        PcAudioGain h = new PcAudioGain();
        byte[] c = pcm((short) 30000, (short) -30000, (short) 12000);
        h.apply(c, c.length, 0.5f);
        check(Math.abs(sampleAt(c, 0) - 15000) <= 1 && Math.abs(sampleAt(c, 2) - 6000) <= 1, "50% is linear");
        PcAudioGain u = new PcAudioGain();
        byte[] d = pcm((short) 32767, (short) -32768, (short) 123);
        u.apply(d, d.length, 1f);
        check(sampleAt(d, 0) == 32767 && sampleAt(d, 1) == -32768 && sampleAt(d, 2) == 123, "100% leaves samples untouched");
    }

    static void testAudioGainSoftLimitNoHardClipping() {
        // Громкий синус при 200 %: без жёсткого обрезания (плато на 32767) и без переполнения
        int n = 4800;
        short[] s = new short[n];
        for (int i = 0; i < n; i++) s[i] = (short) Math.round(Math.sin(2 * Math.PI * 440 * i / 48000.0) * 30000);
        byte[] b = pcm(s);
        PcAudioGain g = new PcAudioGain();
        g.apply(b, b.length, 2f);
        int atRail = 0, maxAbs = 0;
        for (int i = 0; i < n; i++) {
            int v = sampleAt(b, i);
            maxAbs = Math.max(maxAbs, Math.abs(v));
            if (Math.abs(v) >= 32700) atRail++;
        }
        check(atRail == 0, "no samples hard-clipped at the rail (got " + atRail + ")");
        check(maxAbs > 30000 && maxAbs <= Math.round(PcAudioGain.CEIL * 32767) + 1, "loud signal stays loud, under ceiling (" + maxAbs + ")");

        // Форма волны сохраняется (лимитер меняет усиление, а не форму): после атаки
        // соседние полупериоды одинаковы по форме — корреляция с исходным синусом ≈ 1
        double dot = 0, ea = 0, eb = 0;
        for (int i = n / 2; i < n; i++) {
            double x = s[i], y = sampleAt(b, i);
            dot += x * y; ea += x * x; eb += y * y;
        }
        double corr = dot / Math.sqrt(ea * eb);
        check(corr > 0.999, "waveform preserved, no distortion (corr " + corr + ")");

        // Тихий фрагмент после громкого: лимитер отпускает, усиление снова ×2
        short[] q = new short[96000]; // 1 с стерео при 48 кГц
        java.util.Arrays.fill(q, (short) 1000);
        byte[] qb = pcm(q);
        g.apply(qb, qb.length, 2f);
        check(Math.abs(sampleAt(qb, 95999) - 2000) <= 5, "limiter releases, quiet part doubled again (" + sampleAt(qb, 95999) + ")");
    }

    static void testAudioGainRampHasNoClick() {
        // Резкий переход 100 % -> 200 % растягивается на буфер: соседние сэмплы без скачка
        PcAudioGain g = new PcAudioGain();
        short[] s = new short[960];
        java.util.Arrays.fill(s, (short) 8000);
        byte[] b = pcm(s);
        g.apply(b, b.length, 1f);
        byte[] b2 = pcm(s);
        g.apply(b2, b2.length, 2f);
        int maxStep = 0;
        int prev = sampleAt(b, 959);
        for (int i = 0; i < 960; i++) {
            int v = sampleAt(b2, i);
            maxStep = Math.max(maxStep, Math.abs(v - prev));
            prev = v;
        }
        check(maxStep < 50, "gain change is ramped (max step " + maxStep + ")");
        check(Math.abs(sampleAt(b2, 959) - 16000) < 40, "ramp reaches target gain");
    }

    static void eq(Object got, Object want, String name) {
        if (got.equals(want)) passed++;
        else failures.add(name + "\n     want: " + want + "\n     got:  " + got);
    }

    static void check(boolean ok, String name) {
        if (ok) passed++;
        else failures.add(name);
    }

    public static void main(String[] args) throws Exception {
        if (args.length >= 3 && args[0].equals("e2e")) {
            e2e(args[1], args[2]);
        } else if (args.length >= 3 && args[0].equals("reconnect")) {
            reconnect(args[1], args[2]);
        } else {
            testTapIsLeftClick();
            testDoubleTapIsTwoClicks();
            testMoveIsRelativeAndNoClick();
            testSubPixelMovementIsNotLost();
            testLongPressDrag();
            testTapAndDrag();
            testTwoFingerTapIsRightClick();
            testThreeFingerTapIsMiddleClick();
            testTwoFingerScroll();
            testInvertScroll();
            testPrimaryFingerLiftDoesNotJump();
            testCancelReleasesDrag();
            testAccelerationFasterMovesFurther();
            testAbsoluteTapClicksAtPoint();
            testAbsoluteDragAndLongPressRightClick();
            testTypingUnicodeEnRuUk();
            testShiftOneShotAndCaps();
            testCtrlCOnAnyLayoutUsesPhysicalKey();
            testHeldModifierChord();
            testLockedAltStaysUntilTapped();
            testWinAloneOpensStart();
            testHoldReleasesOnLift();
            testReleaseAllNoStuckKeys();
            testFnLayerHotkeysAndFKeys();
            testGameKeysMode();
            testSymbolsLayer();
            testHideKey();
            testProtocolEncoding();
            testAccelerationIsSmoothUnderTimestampJitter();
            testIconsParseAndFitViewBox();
            testSvgArcsAndCompactNumbers();
            testAudioGainAmplifiesUpTo200Percent();
            testAudioGainSoftLimitNoHardClipping();
            testAudioGainRampHasNoClick();
        }
        System.out.println("JVM_TESTS_PASSED=" + passed + " FAILED=" + failures.size());
        for (String f : failures) System.out.println("  FAIL: " + f);
        System.exit(failures.isEmpty() ? 0 : 1);
    }
}
