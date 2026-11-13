package com.pccontrol.remote;

import java.lang.reflect.Method;

/**
 * Logcat with tag "PcControl" for measurements (adb logcat -s PcControl). Pure Java: android.util.Log
 * is reached by reflection, so the classes that log still run in the desktop JVM tests (no-op there).
 * Never log passwords / tokens: callers pass paths without query strings.
 */
final class PcLog {
    private PcLog() {}

    static final String TAG = "PcControl";
    private static final Method I, W;

    static {
        Method i = null, w = null;
        try {
            Class<?> log = Class.forName("android.util.Log");
            i = log.getMethod("i", String.class, String.class);
            w = log.getMethod("w", String.class, String.class);
        } catch (Throwable ignored) {
            // desktop JVM
        }
        I = i;
        W = w;
    }

    static void i(String msg) {
        call(I, msg);
    }

    static void w(String msg) {
        call(W, msg);
    }

    private static void call(Method m, String msg) {
        if (m == null) return;
        try {
            m.invoke(null, TAG, msg);
        } catch (Throwable ignored) {
        }
    }

    /** "/api/x?token=…" → "/api/x" (query strings may carry secrets). */
    static String path(String p) {
        if (p == null) return "";
        int q = p.indexOf('?');
        return q >= 0 ? p.substring(0, q) : p;
    }
}
