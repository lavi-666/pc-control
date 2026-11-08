package com.pccontrol.remote;

/**
 * Binary input protocol v1 shared with the PC server (modules/input_engine.py).
 * Frame: u8 type, u8 flags, u16 payload length (little endian), payload.
 * Pure Java (no Android classes) so it can be unit-tested on a desktop JVM.
 */
public final class PcInputProtocol {
    private PcInputProtocol() {}

    public static final int VERSION = 1;

    public static final int FRAME_HELLO = 0x01;
    public static final int FRAME_PING = 0x02;
    public static final int FRAME_END = 0x03;
    public static final int FRAME_RELEASE_ALL = 0x04;
    public static final int FRAME_MOUSE_REL = 0x10;
    public static final int FRAME_MOUSE_ABS = 0x11;
    public static final int FRAME_MOUSE_BTN = 0x12;
    public static final int FRAME_SCROLL = 0x13;
    public static final int FRAME_KEY = 0x20;
    public static final int FRAME_UNICODE = 0x21;
    public static final int FRAME_TEXT = 0x22;
    public static final int FRAME_HOTKEY = 0x23;

    public static final int BUTTON_LEFT = 1;
    public static final int BUTTON_RIGHT = 2;
    public static final int BUTTON_MIDDLE = 3;

    /** One notch of a standard mouse wheel (Windows WHEEL_DELTA). */
    public static final int WHEEL_DELTA = 120;

    // Windows virtual-key codes used by the keyboard and touchpad.
    public static final int VK_BACK = 0x08, VK_TAB = 0x09, VK_RETURN = 0x0D;
    public static final int VK_SHIFT = 0x10, VK_CONTROL = 0x11, VK_MENU = 0x12;
    public static final int VK_LSHIFT = 0xA0, VK_LCONTROL = 0xA2, VK_LMENU = 0xA4, VK_LWIN = 0x5B;
    public static final int VK_PAUSE = 0x13, VK_CAPITAL = 0x14, VK_ESCAPE = 0x1B, VK_SPACE = 0x20;
    public static final int VK_PRIOR = 0x21, VK_NEXT = 0x22, VK_END = 0x23, VK_HOME = 0x24;
    public static final int VK_LEFT = 0x25, VK_UP = 0x26, VK_RIGHT = 0x27, VK_DOWN = 0x28;
    public static final int VK_SNAPSHOT = 0x2C, VK_INSERT = 0x2D, VK_DELETE = 0x2E;
    public static final int VK_F1 = 0x70;
    public static final int VK_VOLUME_MUTE = 0xAD, VK_VOLUME_DOWN = 0xAE, VK_VOLUME_UP = 0xAF;
    public static final int VK_MEDIA_NEXT = 0xB0, VK_MEDIA_PREV = 0xB1, VK_MEDIA_PLAY_PAUSE = 0xB3;
    public static final int VK_OEM_1 = 0xBA, VK_OEM_PLUS = 0xBB, VK_OEM_COMMA = 0xBC, VK_OEM_MINUS = 0xBD;
    public static final int VK_OEM_PERIOD = 0xBE, VK_OEM_2 = 0xBF, VK_OEM_3 = 0xC0;
    public static final int VK_OEM_4 = 0xDB, VK_OEM_5 = 0xDC, VK_OEM_6 = 0xDD, VK_OEM_7 = 0xDE;

    public static boolean isExtendedVk(int vk) {
        return (vk >= VK_PRIOR && vk <= VK_DOWN) || vk == VK_INSERT || vk == VK_DELETE
                || vk == VK_LWIN || vk == 0x5C || vk == VK_SNAPSHOT;
    }

    public static byte[] frame(int type, byte[] payload) {
        int len = payload == null ? 0 : payload.length;
        byte[] out = new byte[4 + len];
        out[0] = (byte) type;
        out[1] = 0;
        out[2] = (byte) (len & 0xFF);
        out[3] = (byte) ((len >> 8) & 0xFF);
        if (len > 0) System.arraycopy(payload, 0, out, 4, len);
        return out;
    }

    public static byte[] hello() {
        return frame(FRAME_HELLO, new byte[] {(byte) VERSION, 0});
    }

    public static byte[] ping() {
        return frame(FRAME_PING, null);
    }

    public static byte[] end() {
        return frame(FRAME_END, null);
    }

    public static byte[] releaseAll() {
        return frame(FRAME_RELEASE_ALL, null);
    }

    public static byte[] mouseRel(int dx, int dy) {
        return frame(FRAME_MOUSE_REL, new byte[] {lo(dx), hi(dx), lo(dy), hi(dy)});
    }

    public static byte[] mouseAbs(int x, int y, int monitor) {
        return frame(FRAME_MOUSE_ABS, new byte[] {lo(x), hi(x), lo(y), hi(y), (byte) monitor});
    }

    public static byte[] mouseButton(int button, boolean down) {
        return frame(FRAME_MOUSE_BTN, new byte[] {(byte) button, (byte) (down ? 1 : 0)});
    }

    public static byte[] scroll(int vertical, int horizontal) {
        return frame(FRAME_SCROLL, new byte[] {lo(vertical), hi(vertical), lo(horizontal), hi(horizontal)});
    }

    public static byte[] key(int vk, boolean down, boolean extended) {
        return frame(FRAME_KEY, new byte[] {lo(vk), hi(vk), (byte) (down ? 1 : 0), (byte) (extended ? 1 : 0)});
    }

    public static byte[] unicode(int codePoint, boolean down) {
        return frame(FRAME_UNICODE, new byte[] {
                (byte) (codePoint & 0xFF), (byte) ((codePoint >> 8) & 0xFF),
                (byte) ((codePoint >> 16) & 0xFF), (byte) ((codePoint >> 24) & 0xFF),
                (byte) (down ? 1 : 0)});
    }

    public static byte[] text(String text) {
        byte[] utf8 = text.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        if (utf8.length > 4000) {
            throw new IllegalArgumentException("text too long");
        }
        return frame(FRAME_TEXT, utf8);
    }

    public static byte[] hotkey(int[] vks) {
        if (vks.length == 0 || vks.length > 8) throw new IllegalArgumentException("1..8 keys");
        byte[] p = new byte[1 + vks.length * 2];
        p[0] = (byte) vks.length;
        for (int i = 0; i < vks.length; i++) {
            p[1 + i * 2] = lo(vks[i]);
            p[2 + i * 2] = hi(vks[i]);
        }
        return frame(FRAME_HOTKEY, p);
    }

    static int clamp16(int v) {
        return Math.max(-32768, Math.min(32767, v));
    }

    private static byte lo(int v) {
        return (byte) (v & 0xFF);
    }

    private static byte hi(int v) {
        return (byte) ((v >> 8) & 0xFF);
    }
}
