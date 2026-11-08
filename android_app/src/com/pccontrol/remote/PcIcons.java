package com.pccontrol.remote;

/**
 * Icon set of the native player = the icons of the PC Control WebView interface
 * (assets/index.html, 24x24 viewBox). Element 0 is the style: "F" filled (Material),
 * "S" stroked (Feather, 2 px, round caps), the rest are SVG path data strings.
 * Pure Java so the JVM tests can verify that every icon parses and fits the viewBox.
 */
public final class PcIcons {
    private PcIcons() {}

    private static final String CIRCLE_R3 = "M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0z";

    /** Settings (index.html, settings modal). */
    public static final String[] GEAR = {"S", CIRCLE_R3,
            "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"};

    public static final String[] CLOSE = {"S", "M18 6L6 18M6 6l12 12"};
    public static final String[] CHEVRON_DOWN = {"S", "M6 9l6 6 6-6"};
    public static final String[] CHEVRON_LEFT = {"S", "M15 18l-6-6 6-6"};
    public static final String[] CHEVRON_RIGHT = {"S", "M9 18l6-6-6-6"};
    public static final String[] CHECK = {"S", "M20 6L9 17l-5-5"};
    public static final String[] EYE = {"S", "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z", CIRCLE_R3};
    public static final String[] RESET = {"S", "M23 4v6h-6", "M1 20v-6h6",
            "M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"};

    /** "Язык ввода Windows" button. */
    public static final String[] KEYBOARD = {"F",
            "M20 5H4c-1.1 0-1.99.9-1.99 2L2 17c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm-9 3h2v2h-2V8zm0 3h2v2h-2v-2zM8 8h2v2H8V8zm0 3h2v2H8v-2zm-1 2H5v-2h2v2zm0-3H5V8h2v2zm9 7H8v-2h8v2zm0-4h-2v-2h2v2zm0-3h-2V8h2v2zm3 3h-2v-2h2v2zm0-3h-2V8h2v2z"};
    /** Material "mouse". */
    public static final String[] MOUSE = {"F",
            "M13 1.07V9h7c0-4.08-3.05-7.44-7-7.93zM4 15c0 4.42 3.58 8 8 8s8-3.58 8-8v-4H4v4zm7-13.93C7.05 1.56 4 4.92 4 9h7V1.07z"};
    /** "Микрофон" button. */
    public static final String[] MIC = {"F",
            "M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15a.998.998 0 0 0-.98-.85c-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20H8v2h8v-2h-3v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"};
    /** "Звук ПК" button. */
    public static final String[] HEADPHONES = {"F",
            "M12 3a9 9 0 0 0-9 9v7c0 1.1.9 2 2 2h4v-8H5v-1c0-3.87 3.13-7 7-7s7 3.13 7 7v1h-4v8h4c1.1 0 2-.9 2-2v-7a9 9 0 0 0-9-9z"};
    /** "Демонстрация экрана" button. */
    public static final String[] MONITOR = {"F",
            "M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5c0-1.1-.9-2-2-2zm0 14H3V5h18v12z"};
    /** "Снимок экрана" button (used for picture quality). */
    public static final String[] IMAGE = {"F",
            "M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"};
    /** History/clock icon of the player (used for frame rate). */
    public static final String[] CLOCK = {"F",
            "M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"};
    /** Fullscreen button of the screen stage. */
    public static final String[] FULLSCREEN = {"F",
            "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"};
    /** Material "fullscreen_exit". */
    public static final String[] FULLSCREEN_EXIT = {"F",
            "M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"};
    /** Material "bar_chart" (diagnostics). */
    public static final String[] CHART = {"F", "M5 9.2h3V19H5V9.2zM10.6 5h2.8v14h-2.8V5zm5.6 8H19v6h-2.8v-6z"};
    /** Material "arrow_back". */
    public static final String[] ARROW_BACK = {"F", "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"};
    /** "Управление ПК" button. */
    public static final String[] PC = {"F",
            "M20 18c1.1 0 1.99-.9 1.99-2L22 5c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v11c0 1.1.9 2 2 2H0c0 1.1.9 2 2 2h20c1.1 0 2-.9 2-2h-4zM4 5h16v11H4V5zm8 14c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"};

    /** Material "tune" (settings inside the floating menu; the gear itself opens the menu). */
    public static final String[] TUNE = {"F",
            "M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z"};

    public static String[][] all() {
        return new String[][]{GEAR, CLOSE, CHEVRON_DOWN, CHEVRON_LEFT, CHEVRON_RIGHT, CHECK, EYE, RESET,
                KEYBOARD, MOUSE, MIC, HEADPHONES, MONITOR, IMAGE, CLOCK, FULLSCREEN, FULLSCREEN_EXIT,
                CHART, ARROW_BACK, PC, TUNE};
    }
}
