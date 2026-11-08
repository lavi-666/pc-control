package com.pccontrol.remote;

import java.util.ArrayList;
import java.util.List;

/**
 * Key model and modifier logic of the PC Control on-screen keyboard (pure Java).
 *
 * Every character key carries the Windows virtual key of its physical position
 * (RU "с" = VK_C, UK "ї" = VK_OEM_6 ...), the same idea KDE Connect implements with
 * VkKeyScanEx, but resolved on the phone so it does not depend on the PC layout:
 *   - plain typing sends Unicode (independent of the PC input language),
 *   - with Ctrl/Alt/Win active (or in "game keys" mode) the physical VK is sent,
 *     so Ctrl+C / Ctrl+С, Alt+F4, Win+D work on any PC layout.
 *
 * Modifiers (Shift, Ctrl, Alt, Win):
 *   hold + press other key ... real chord, modifier released with the finger
 *   tap ...................... one-shot: applies to the next key, then released
 *   second tap ............... locked until tapped again (Shift lock = Caps)
 * Every key sends down on touch and up on release (server autorepeats while held).
 */
public final class PcKeyboardLogic {

    public interface Output {
        void key(int vk, boolean down);

        void unicode(int codePoint, boolean down);

        void hotkey(int[] vks);

        void onKeyboardChanged();

        void onHideRequested();
    }

    public static final int K_CHAR = 0, K_VK = 1, K_MOD = 2, K_LANG = 3, K_LAYER = 4, K_HOTKEY = 5, K_HIDE = 6, K_FN = 7;
    public static final int MOD_SHIFT = 0, MOD_CTRL = 1, MOD_ALT = 2, MOD_WIN = 3;
    public static final int LAYER_LETTERS = 0, LAYER_SYMBOLS = 1, LAYER_FN = 2;
    public static final int LANG_EN = 0, LANG_RU = 1, LANG_UK = 2;
    public static final int ST_OFF = 0, ST_HELD = 1, ST_LATCHED = 2, ST_LOCKED = 3;

    private static final int[] MOD_VK = {
            PcInputProtocol.VK_LSHIFT, PcInputProtocol.VK_LCONTROL, PcInputProtocol.VK_LMENU, PcInputProtocol.VK_LWIN};

    public static final class Key {
        public final int kind;
        public final String label;
        public final String shiftLabel;
        public final int vk;
        public final int mod;
        public final int[] combo;
        public final float width;
        public final boolean special;

        Key(int kind, String label, String shiftLabel, int vk, int mod, int[] combo, float width, boolean special) {
            this.kind = kind;
            this.label = label;
            this.shiftLabel = shiftLabel;
            this.vk = vk;
            this.mod = mod;
            this.combo = combo;
            this.width = width;
            this.special = special;
        }
    }

    /** What a pressed key sent, so the matching release goes out on finger up. */
    public static final class Press {
        final Key key;
        final int sentVk;       // >0: a VK down was sent
        final int sentUnicode;  // >0: a Unicode down was sent

        Press(Key key, int sentVk, int sentUnicode) {
            this.key = key;
            this.sentVk = sentVk;
            this.sentUnicode = sentUnicode;
        }
    }

    private final Output out;
    private final int[] modState = new int[4];
    private final boolean[] modChord = new boolean[4];
    private final boolean[] modIgnoreUp = new boolean[4];
    private final boolean[] modVkDown = new boolean[4];
    private final List<Press> pressed = new ArrayList<>();
    private int lang = LANG_EN;
    private int layer = LAYER_LETTERS;
    private boolean gameKeys = false;

    public PcKeyboardLogic(Output out) {
        this.out = out;
    }

    // ------------------------------------------------------------------ state
    public int getLang() {
        return lang;
    }

    public void setLang(int l) {
        lang = Math.max(0, Math.min(2, l));
        out.onKeyboardChanged();
    }

    public int getLayer() {
        return layer;
    }

    public void setGameKeys(boolean on) {
        gameKeys = on;
    }

    public boolean isGameKeys() {
        return gameKeys;
    }

    public int getModState(int mod) {
        return modState[mod];
    }

    public boolean isShifted() {
        return modState[MOD_SHIFT] == ST_HELD || modState[MOD_SHIFT] == ST_LATCHED;
    }

    public boolean isCaps() {
        return modState[MOD_SHIFT] == ST_LOCKED;
    }

    private boolean commandModifierActive() {
        return modState[MOD_CTRL] != ST_OFF || modState[MOD_ALT] != ST_OFF || modState[MOD_WIN] != ST_OFF;
    }

    /** Text shown on the key for the current shift/caps state. */
    public String displayLabel(Key k) {
        if (k.kind == K_LANG) return lang == LANG_RU ? "RU" : (lang == LANG_UK ? "UK" : "EN");
        if (k.kind != K_CHAR) return k.label;
        return effectiveText(k);
    }

    private String effectiveText(Key k) {
        if (isShifted()) return k.shiftLabel != null ? k.shiftLabel : k.label.toUpperCase();
        if (isCaps() && Character.isLetter(k.label.codePointAt(0))) return k.label.toUpperCase();
        return k.label;
    }

    // ------------------------------------------------------------------ press / release
    public Press press(Key k) {
        Press p;
        switch (k.kind) {
            case K_MOD:
                modDown(k.mod);
                p = new Press(k, 0, 0);
                break;
            case K_CHAR: {
                markChord();
                if ((gameKeys || commandModifierActive()) && k.vk > 0) {
                    out.key(k.vk, true);
                    p = new Press(k, k.vk, 0);
                } else {
                    int cp = effectiveText(k).codePointAt(0);
                    out.unicode(cp, true);
                    p = new Press(k, 0, cp);
                }
                break;
            }
            case K_VK:
                markChord();
                out.key(k.vk, true);
                p = new Press(k, k.vk, 0);
                break;
            case K_HOTKEY:
                markChord();
                out.hotkey(k.combo);
                p = new Press(k, 0, 0);
                break;
            case K_LANG:
                lang = (lang + 1) % 3;
                if (layer != LAYER_LETTERS) layer = LAYER_LETTERS;
                out.onKeyboardChanged();
                p = new Press(k, 0, 0);
                break;
            case K_LAYER:
                layer = (layer == LAYER_LETTERS) ? LAYER_SYMBOLS : LAYER_LETTERS;
                out.onKeyboardChanged();
                p = new Press(k, 0, 0);
                break;
            case K_FN:
                layer = (layer == LAYER_FN) ? LAYER_LETTERS : LAYER_FN;
                out.onKeyboardChanged();
                p = new Press(k, 0, 0);
                break;
            case K_HIDE:
                p = new Press(k, 0, 0);
                break;
            default:
                p = new Press(k, 0, 0);
                break;
        }
        pressed.add(p);
        return p;
    }

    public void release(Press p) {
        if (p == null || !pressed.remove(p)) return;
        Key k = p.key;
        if (k.kind == K_MOD) {
            modUp(k.mod);
            return;
        }
        if (p.sentVk > 0) out.key(p.sentVk, false);
        if (p.sentUnicode > 0) out.unicode(p.sentUnicode, false);
        if (k.kind == K_CHAR || k.kind == K_VK || k.kind == K_HOTKEY) {
            releaseOneShotModifiers();
        } else if (k.kind == K_HIDE) {
            out.onHideRequested();
        }
    }

    private void markChord() {
        for (int m = 0; m < 4; m++) {
            if (modState[m] == ST_HELD) modChord[m] = true;
        }
    }

    private void modDown(int m) {
        switch (modState[m]) {
            case ST_OFF:
                setModVk(m, true);
                modState[m] = ST_HELD;
                modChord[m] = false;
                modIgnoreUp[m] = false;
                break;
            case ST_LATCHED:
                modState[m] = ST_LOCKED;
                if (m == MOD_SHIFT) setModVk(m, false); // Shift lock = Caps (letters only)
                modIgnoreUp[m] = true;
                break;
            case ST_LOCKED:
                setModVk(m, false);
                modState[m] = ST_OFF;
                modIgnoreUp[m] = true;
                break;
            default:
                break;
        }
        out.onKeyboardChanged();
    }

    private void modUp(int m) {
        if (modIgnoreUp[m]) {
            modIgnoreUp[m] = false;
            return;
        }
        if (modState[m] == ST_HELD) {
            if (modChord[m]) {
                setModVk(m, false);
                modState[m] = ST_OFF;
            } else {
                modState[m] = ST_LATCHED;
            }
            out.onKeyboardChanged();
        }
    }

    private void setModVk(int m, boolean down) {
        if (modVkDown[m] == down) return;
        modVkDown[m] = down;
        out.key(MOD_VK[m], down);
    }

    private void releaseOneShotModifiers() {
        boolean changed = false;
        for (int m = 0; m < 4; m++) {
            if (modState[m] == ST_LATCHED) {
                setModVk(m, false);
                modState[m] = ST_OFF;
                changed = true;
            }
        }
        if (changed) out.onKeyboardChanged();
    }

    /** Releases every key and modifier (keyboard hidden, view detached, touch cancelled). */
    public void releaseAll() {
        for (Press p : new ArrayList<>(pressed)) {
            if (p.sentVk > 0) out.key(p.sentVk, false);
            if (p.sentUnicode > 0) out.unicode(p.sentUnicode, false);
        }
        pressed.clear();
        for (int m = 0; m < 4; m++) {
            setModVk(m, false);
            modState[m] = ST_OFF;
            modIgnoreUp[m] = false;
        }
        out.onKeyboardChanged();
    }

    /** Re-sends held state after the input connection was re-established. */
    public void resync() {
        for (int m = 0; m < 4; m++) {
            if (modVkDown[m]) out.key(MOD_VK[m], true);
        }
        for (Press p : pressed) {
            if (p.sentVk > 0) out.key(p.sentVk, true);
            if (p.sentUnicode > 0) out.unicode(p.sentUnicode, true);
        }
    }

    // ------------------------------------------------------------------ layouts
    public List<Key[]> rows() {
        List<Key[]> rows = new ArrayList<>();
        rows.add(functionRow());
        if (layer == LAYER_SYMBOLS) {
            addSymbolRows(rows);
        } else if (layer == LAYER_FN) {
            addFnRows(rows);
        } else if (lang == LANG_RU) {
            addRuRows(rows);
        } else if (lang == LANG_UK) {
            addUkRows(rows);
        } else {
            addEnRows(rows);
        }
        rows.add(bottomRow());
        return rows;
    }

    private static Key ch(String label, String shift, int vk) {
        return new Key(K_CHAR, label, shift, vk, -1, null, 1f, false);
    }

    private static Key vk(String label, int vk, float w) {
        return new Key(K_VK, label, null, vk, -1, null, w, true);
    }

    private static Key mod(String label, int mod, float w) {
        return new Key(K_MOD, label, null, MOD_VK[mod], mod, null, w, true);
    }

    private static Key hk(String label, float w, int... vks) {
        return new Key(K_HOTKEY, label, null, 0, -1, vks, w, true);
    }

    private static Key other(int kind, String label, float w) {
        return new Key(kind, label, null, 0, -1, null, w, true);
    }

    private static Key[] functionRow() {
        return new Key[] {
                vk("Esc", PcInputProtocol.VK_ESCAPE, 1f), vk("Tab", PcInputProtocol.VK_TAB, 1f),
                other(K_FN, "Fn", 1f),
                vk("Home", PcInputProtocol.VK_HOME, 1f), vk("End", PcInputProtocol.VK_END, 1f),
                vk("PgUp", PcInputProtocol.VK_PRIOR, 1f), vk("PgDn", PcInputProtocol.VK_NEXT, 1f),
                vk("Ins", PcInputProtocol.VK_INSERT, 1f), vk("Del", PcInputProtocol.VK_DELETE, 1f),
                vk("PrtSc", PcInputProtocol.VK_SNAPSHOT, 1f), other(K_HIDE, "⌄", 1f),
        };
    }

    private Key[] bottomRow() {
        String layerLabel = layer == LAYER_LETTERS ? "123" : "ABC";
        return new Key[] {
                mod("Ctrl", MOD_CTRL, 1.3f), mod("Win", MOD_WIN, 1.1f), mod("Alt", MOD_ALT, 1.1f),
                other(K_LANG, "EN", 1.1f), other(K_LAYER, layerLabel, 1.1f),
                vk("␣", PcInputProtocol.VK_SPACE, 4.4f),
                vk("←", PcInputProtocol.VK_LEFT, 1f), vk("↓", PcInputProtocol.VK_DOWN, 1f), vk("→", PcInputProtocol.VK_RIGHT, 1f),
        };
    }

    private static Key backspace() {
        return vk("⌫", PcInputProtocol.VK_BACK, 1.5f);
    }

    private static Key enter() {
        return vk("⏎", PcInputProtocol.VK_RETURN, 1.6f);
    }

    private static Key up() {
        return vk("↑", PcInputProtocol.VK_UP, 1f);
    }

    private static Key[] digits(String first, String firstShift, String shifts) {
        Key[] r = new Key[14];
        r[0] = ch(first, firstShift, PcInputProtocol.VK_OEM_3);
        String nums = "1234567890";
        for (int i = 0; i < 10; i++) {
            r[1 + i] = ch(String.valueOf(nums.charAt(i)), String.valueOf(shifts.charAt(i)), nums.charAt(i));
        }
        r[11] = ch("-", "_", PcInputProtocol.VK_OEM_MINUS);
        r[12] = ch("=", "+", PcInputProtocol.VK_OEM_PLUS);
        r[13] = backspace();
        return r;
    }

    private static Key[] letters(String chars, String vks) {
        Key[] r = new Key[chars.length()];
        for (int i = 0; i < chars.length(); i++) {
            r[i] = ch(String.valueOf(chars.charAt(i)), null, vks.charAt(i));
        }
        return r;
    }

    private static Key[] concat(Key[] a, Key... b) {
        Key[] r = new Key[a.length + b.length];
        System.arraycopy(a, 0, r, 0, a.length);
        System.arraycopy(b, 0, r, a.length, b.length);
        return r;
    }

    private static Key shiftKey() {
        return mod("⇧", MOD_SHIFT, 1.5f);
    }

    private void addEnRows(List<Key[]> rows) {
        rows.add(digits("`", "~", "!@#$%^&*()"));
        rows.add(concat(letters("qwertyuiop", "QWERTYUIOP"),
                ch("[", "{", PcInputProtocol.VK_OEM_4), ch("]", "}", PcInputProtocol.VK_OEM_6),
                ch("\\", "|", PcInputProtocol.VK_OEM_5)));
        rows.add(concat(letters("asdfghjkl", "ASDFGHJKL"),
                ch(";", ":", PcInputProtocol.VK_OEM_1), ch("'", "\"", PcInputProtocol.VK_OEM_7), enter()));
        rows.add(concat(new Key[] {shiftKey()}, concat(letters("zxcvbnm", "ZXCVBNM"),
                ch(",", "<", PcInputProtocol.VK_OEM_COMMA), ch(".", ">", PcInputProtocol.VK_OEM_PERIOD),
                ch("/", "?", PcInputProtocol.VK_OEM_2), up())));
    }

    private static final String RU_ROW1 = "йцукенгшщзхъ";
    private static final String UK_ROW1 = "йцукенгшщзхї";
    private static final String CYR_ROW1_VK = "QWERTYUIOP" + (char) PcInputProtocol.VK_OEM_4 + (char) PcInputProtocol.VK_OEM_6;
    private static final String RU_ROW2 = "фывапролджэ";
    private static final String UK_ROW2 = "фівапролджє";
    private static final String CYR_ROW2_VK = "ASDFGHJKL" + (char) PcInputProtocol.VK_OEM_1 + (char) PcInputProtocol.VK_OEM_7;
    private static final String CYR_ROW3 = "ячсмитьбю";
    private static final String CYR_ROW3_VK = "ZXCVBNM" + (char) PcInputProtocol.VK_OEM_COMMA + (char) PcInputProtocol.VK_OEM_PERIOD;

    private void addRuRows(List<Key[]> rows) {
        rows.add(digits("ё", "Ё", "!\"№;%:?*()"));
        rows.add(concat(letters(RU_ROW1, CYR_ROW1_VK), ch("\\", "/", PcInputProtocol.VK_OEM_5)));
        rows.add(concat(letters(RU_ROW2, CYR_ROW2_VK), enter()));
        rows.add(concat(new Key[] {shiftKey()}, concat(letters(CYR_ROW3, CYR_ROW3_VK),
                ch(".", ",", PcInputProtocol.VK_OEM_2), up())));
    }

    private void addUkRows(List<Key[]> rows) {
        rows.add(digits("'", "₴", "!\"№;%:?*()"));
        rows.add(concat(letters(UK_ROW1, CYR_ROW1_VK), ch("ґ", "Ґ", PcInputProtocol.VK_OEM_5)));
        rows.add(concat(letters(UK_ROW2, CYR_ROW2_VK), enter()));
        rows.add(concat(new Key[] {shiftKey()}, concat(letters(CYR_ROW3, CYR_ROW3_VK),
                ch(".", ",", PcInputProtocol.VK_OEM_2), up())));
    }

    private void addSymbolRows(List<Key[]> rows) {
        Key[] r1 = new Key[11];
        String nums = "1234567890";
        for (int i = 0; i < 10; i++) r1[i] = ch(String.valueOf(nums.charAt(i)), null, nums.charAt(i));
        r1[10] = backspace();
        rows.add(r1);
        rows.add(symbols("@#$%&*-+=()"));
        rows.add(concat(symbols("!?\"':;/\\|~"), enter()));
        rows.add(concat(symbols("<>[]{}_^`€₴№"), up()));
    }

    private static Key[] symbols(String s) {
        List<Key> r = new ArrayList<>();
        for (int i = 0; i < s.length(); ) {
            int cp = s.codePointAt(i);
            r.add(new Key(K_CHAR, new String(Character.toChars(cp)), new String(Character.toChars(cp)), 0, -1, null, 1f, false));
            i += Character.charCount(cp);
        }
        return r.toArray(new Key[0]);
    }

    private void addFnRows(List<Key[]> rows) {
        Key[] f = new Key[13];
        for (int i = 0; i < 12; i++) f[i] = vk("F" + (i + 1), PcInputProtocol.VK_F1 + i, 1f);
        f[12] = backspace();
        rows.add(f);
        int C = PcInputProtocol.VK_LCONTROL, A = PcInputProtocol.VK_LMENU, W = PcInputProtocol.VK_LWIN, S = PcInputProtocol.VK_LSHIFT;
        rows.add(new Key[] {
                hk("Ctrl+C", 1f, C, 'C'), hk("Ctrl+V", 1f, C, 'V'), hk("Ctrl+X", 1f, C, 'X'),
                hk("Ctrl+Z", 1f, C, 'Z'), hk("Ctrl+Y", 1f, C, 'Y'), hk("Ctrl+A", 1f, C, 'A'),
                hk("Ctrl+S", 1f, C, 'S'), hk("Ctrl+F", 1f, C, 'F'),
        });
        rows.add(concat(new Key[] {
                hk("Alt+Tab", 1f, A, PcInputProtocol.VK_TAB), hk("Alt+F4", 1f, A, PcInputProtocol.VK_F1 + 3),
                hk("Win+D", 1f, W, 'D'), hk("Win+E", 1f, W, 'E'), hk("Win+R", 1f, W, 'R'),
                hk("Win+Tab", 1f, W, PcInputProtocol.VK_TAB), hk("Win+V", 1f, W, 'V'),
                hk("Ctrl⇧Esc", 1f, C, S, PcInputProtocol.VK_ESCAPE),
        }, enter()));
        rows.add(new Key[] {
                hk("Ctrl+W", 1f, C, 'W'), hk("Ctrl+T", 1f, C, 'T'), hk("Ctrl⇧T", 1f, C, S, 'T'),
                hk("Win⇧S", 1f, W, S, 'S'),
                vk("🔉", PcInputProtocol.VK_VOLUME_DOWN, 1f), vk("🔊", PcInputProtocol.VK_VOLUME_UP, 1f),
                vk("🔇", PcInputProtocol.VK_VOLUME_MUTE, 1f), vk("⏯", PcInputProtocol.VK_MEDIA_PLAY_PAUSE, 1f),
                up(),
        });
    }
}
