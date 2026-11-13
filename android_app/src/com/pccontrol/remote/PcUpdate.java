package com.pccontrol.remote;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Обновление приложения из настроек: чистая логика без Android API (проверяется на JVM).
 * Сравнение версий установленного приложения и PC_Control.apk на ПК (GET /api/apk/info),
 * скачивание /download/apk с заголовком X-Auth-Token и проверка sha256, коды PackageInstaller.
 */
final class PcUpdate {
    private PcUpdate() {}

    // результат сравнения версий
    static final int NO_APK = 0, UP_TO_DATE = 1, NEWER = 2, OLDER_ON_PC = 3;

    /** Что предложить по ответу /api/apk/info. Понижение версии не предлагается никогда. */
    static int decide(long installedCode, PcJson.O info) {
        if (info == null || !info.bool("available", false)) return NO_APK;
        long pc = info.lng("version_code", 0);
        if (pc <= 0 || info.str("sha256").length() != 64) return NO_APK;
        if (pc > installedCode) return NEWER;
        if (pc == installedCode) return UP_TO_DATE;
        return OLDER_ON_PC;
    }

    /** «2.4.2 · Build 16» (как в разделе «О программе»). */
    static String label(String name, long code) {
        String n = name == null ? "" : name.trim();
        if (code <= 0) return n.isEmpty() ? "—" : n;
        return (n.isEmpty() ? "" : n + " · ") + "Build " + code;
    }

    static boolean sha256Matches(String expected, String actual) {
        if (expected == null || actual == null) return false;
        String e = expected.trim(), a = actual.trim();
        return e.length() == 64 && e.equalsIgnoreCase(a);
    }

    static String hex(byte[] d) {
        StringBuilder sb = new StringBuilder(d.length * 2);
        for (byte b : d) sb.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        return sb.toString();
    }

    static String sha256(File f) {
        try (InputStream in = new FileInputStream(f)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
            return hex(md.digest());
        } catch (Exception e) {
            return "";
        }
    }

    /** Процент 0..100 (или -1, если размер неизвестен). */
    static int percent(long done, long total) {
        if (total <= 0) return -1;
        return (int) Math.max(0, Math.min(100, done * 100 / total));
    }

    /** «1.2 / 2.6 MB». */
    static String sizeText(long done, long total) {
        String d = String.format(Locale.ROOT, "%.1f", done / 1048576.0);
        return total > 0 ? d + " / " + String.format(Locale.ROOT, "%.1f", total / 1048576.0) + " MB" : d + " MB";
    }

    /** Ключ строки для итогового кода PackageInstaller (EXTRA_STATUS). */
    static String statusKey(int status) {
        switch (status) {
            case 0: return "apk_upd_installed";               // STATUS_SUCCESS
            case 3: return "apk_upd_err_aborted";             // STATUS_FAILURE_ABORTED
            case 2: return "apk_upd_err_blocked";             // STATUS_FAILURE_BLOCKED
            case 5:                                           // STATUS_FAILURE_CONFLICT
            case 7: return "apk_upd_err_conflict";            // STATUS_FAILURE_INCOMPATIBLE
            case 6: return "apk_upd_err_storage";             // STATUS_FAILURE_STORAGE
            case 4: return "apk_upd_err_invalid";             // STATUS_FAILURE_INVALID
            default: return "apk_upd_err_install";
        }
    }

    interface Progress {
        void on(long done, long total);
    }

    static final class Result {
        boolean ok, cancelled;
        int code;
        String error = "";
        String sha256 = "";
        long size;
    }

    /**
     * Скачивает base+path в out (через временный файл .part), считая sha256 на лету.
     * Блокирующий вызов — только из рабочего потока. cancel = true прерывает загрузку.
     */
    static Result download(String base, String path, String token, File out, long expectedSize,
                           Progress progress, AtomicBoolean cancel) {
        Result r = new Result();
        File part = new File(out.getPath() + ".part");
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(PcHttp.join(base, path)).openConnection();
            c.setConnectTimeout(PcHttp.CONNECT_TIMEOUT);
            c.setReadTimeout(20000);
            c.setUseCaches(false);
            c.setRequestProperty("Cache-Control", "no-store");
            if (token != null && !token.isEmpty()) c.setRequestProperty("X-Auth-Token", PcConn.encodeURIComponent(token));
            r.code = c.getResponseCode();
            if (r.code != 200) {
                r.error = "HTTP " + r.code;
                return r;
            }
            long total = c.getContentLengthLong();
            if (total <= 0) total = expectedSize;
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            long done = 0, lastReport = 0;
            try (InputStream in = c.getInputStream(); OutputStream os = new FileOutputStream(part)) {
                byte[] buf = new byte[32768];
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (cancel != null && cancel.get()) {
                        r.cancelled = true;
                        break;
                    }
                    os.write(buf, 0, n);
                    md.update(buf, 0, n);
                    done += n;
                    if (done > 512L * 1024 * 1024) throw new java.io.IOException("file too large");
                    if (progress != null && (done - lastReport >= 32768 || done == total)) {
                        lastReport = done;
                        progress.on(done, total);
                    }
                }
            }
            if (r.cancelled) return r;
            if (progress != null) progress.on(done, total);
            r.size = done;
            r.sha256 = hex(md.digest());
            if (out.exists() && !out.delete()) throw new java.io.IOException("cannot replace " + out.getName());
            if (!part.renameTo(out)) throw new java.io.IOException("cannot rename " + part.getName());
            r.ok = true;
        } catch (Exception e) {
            r.error = e.getClass().getSimpleName() + (e.getMessage() == null ? "" : ": " + e.getMessage());
        } finally {
            if (c != null) c.disconnect();
            if (!r.ok) part.delete();
        }
        return r;
    }
}
