package com.pccontrol.remote;

/**
 * Icons of the main screens — the exact SVG paths of web/index.html, media.js and presets.js
 * (24x24 viewBox). "F" = filled (Material), "S" = stroked (Feather; rect / circle / line /
 * polyline elements rewritten as equivalent path data). Pure Java (JVM-tested like PcIcons).
 */
public final class PcAppIcons {
    private PcAppIcons() {}

    // ---------------------------------------------------------------- player
    public static final String[] MUSIC = {"F", "M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"};
    public static final String[] HISTORY = PcIcons.CLOCK;
    public static final String[] MODE_NORMAL = {"F", "M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"};
    public static final String[] MODE_REPEAT = {"F", "M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-4-2V9h-1l-2 1v1h1.5v4H13z"};
    public static final String[] MODE_SHUFFLE = {"F", "M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"};
    public static final String[] PREV = {"F", "M6 6h2v12H6zm3.5 6 8.5 6V6z"};
    public static final String[] PLAY = {"F", "M8 5v14l11-7z"};
    public static final String[] PAUSE = {"F", "M6 19h4V5H6v14zm8-14v14h4V5h-4z"};
    public static final String[] NEXT = {"F", "M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"};
    public static final String[] QUEUE = {"F", "M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"};
    public static final String[] VOL_LOW = {"F", "M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"};
    public static final String[] VOL_ON = {"F", "M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"};
    public static final String[] VOL_MUTE = {"F", "M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3 3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z"};
    public static final String[] TARGET = {"F", "M12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm8.94 3A8.994 8.994 0 0 0 13 3.06V1h-2v2.06A8.994 8.994 0 0 0 3.06 11H1v2h2.06A8.994 8.994 0 0 0 11 20.94V23h2v-2.06A8.994 8.994 0 0 0 20.94 13H23v-2h-2.06zM12 19c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"};
    public static final String[] SYNC = PcIcons.RESET;

    // ---------------------------------------------------------------- audio & streaming
    public static final String[] HEADPHONES = PcIcons.HEADPHONES;
    public static final String[] MIC = PcIcons.MIC;
    public static final String[] BG_MODE = {"F", "M12 1a9 9 0 0 0-9 9v7c0 1.66 1.34 3 3 3h3v-8H5v-2c0-3.87 3.13-7 7-7s7 3.13 7 7v2h-4v8h3c1.66 0 3-1.34 3-3v-7a9 9 0 0 0-9-9zm-1 11h2v1.17c.59.34 1 .98 1 1.83 0 1.1-.9 2-2 2s-2-.9-2-2c0-.85.41-1.49 1-1.83V12z"};
    public static final String[] PC = PcIcons.PC;
    public static final String[] MONITOR = PcIcons.MONITOR;
    public static final String[] TUNE = PcIcons.TUNE;
    public static final String[] EXPAND = {"F", "M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z"};

    // ---------------------------------------------------------------- input & system
    public static final String[] KEYBOARD = PcIcons.KEYBOARD;
    public static final String[] IMAGE = PcIcons.IMAGE;
    public static final String[] LIST = {"F", "M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"};
    public static final String[] SEARCH = {"F", "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"};
    public static final String[] REFRESH = {"F", "M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"};
    public static final String[] SPARKLE = {"F", "M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5z"};

    // ---------------------------------------------------------------- power
    public static final String[] POWER = {"F", "M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42A6.92 6.92 0 0 1 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.58 1.4-4.83 3.49-6.04L7.07 4.54C4.6 6.07 3 8.84 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-3.16-1.6-5.93-4.17-7.83z"};

    // ---------------------------------------------------------------- dialogs / fields (stroked)
    public static final String[] GEAR = PcIcons.GEAR;
    public static final String[] CLOSE = PcIcons.CLOSE;
    public static final String[] CHECK = PcIcons.CHECK;
    public static final String[] EYE = PcIcons.EYE;
    public static final String[] EYE_OFF = {"S",
            "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24",
            "M1 1L23 23"};
    public static final String[] COPY = {"S", "M11 9h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z",
            "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"};
    public static final String[] PENCIL = {"S", "M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"};
    public static final String[] TRASH = {"S", "M3 6h18", "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6", "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"};
    public static final String[] UP = {"S", "M18 15l-6-6-6 6"};
    public static final String[] DOWN = {"S", "M6 9l6 6 6-6"};
    public static final String[] SPINNER = {"S", "M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"};

    // ---------------------------------------------------------------- preset icons (presets.js PRESET_ICONS)
    public static final String[] P_BOLT = {"S", "M13 2L3 14h9l-1 8 10-12h-9l1-8z"};
    public static final String[] P_GAME = {"S", "M6 12h4", "M8 10v4", "M15 13h.01", "M18 11h.01",
            "M4 6h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"};
    public static final String[] P_ROCKET = {"S",
            "M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z",
            "M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z",
            "M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0", "M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"};
    public static final String[] P_WEB = {"S", "M22 12a10 10 0 1 1-20 0 10 10 0 1 1 20 0z",
            "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20", "M2 12h20"};
    public static final String[] P_TERMINAL = {"S", "M4 17l6-6-6-6", "M12 19h8"};
    public static final String[] P_MUSIC = {"S", "M9 18V5l12-2v13", "M9 18a3 3 0 1 1-6 0 3 3 0 1 1 6 0z", "M21 16a3 3 0 1 1-6 0 3 3 0 1 1 6 0z"};
    public static final String[] P_APP = {"S", "M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M8 21h8", "M12 17v4"};
    public static final String[] P_DELAY = {"S", "M22 12a10 10 0 1 1-20 0 10 10 0 1 1 20 0z", "M12 6v6l4 2"};

    public static final String[] PRESET_KEYS = {"bolt", "game", "rocket", "web", "terminal", "music", "app", "delay"};

    public static String[] preset(String key) {
        String k = key == null ? "" : key.toLowerCase(java.util.Locale.ROOT);
        switch (k) {
            case "game": return P_GAME;
            case "rocket": return P_ROCKET;
            case "web": return P_WEB;
            case "terminal": return P_TERMINAL;
            case "music": return P_MUSIC;
            case "app": return P_APP;
            case "delay": return P_DELAY;
            default: return P_BOLT;
        }
    }

    public static boolean isPresetKey(String key) {
        for (String k : PRESET_KEYS) if (k.equals(key)) return true;
        return false;
    }

    public static String[][] all() {
        return new String[][]{MUSIC, MODE_NORMAL, MODE_REPEAT, MODE_SHUFFLE, PREV, PLAY, PAUSE, NEXT, QUEUE,
                VOL_LOW, VOL_ON, VOL_MUTE, TARGET, BG_MODE, EXPAND, LIST, SEARCH, REFRESH, SPARKLE, POWER,
                EYE_OFF, COPY, PENCIL, TRASH, UP, DOWN, SPINNER, P_BOLT, P_GAME, P_ROCKET, P_WEB, P_TERMINAL,
                P_MUSIC, P_APP, P_DELAY};
    }
}
