package com.pccontrol.remote;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Модель микшера громкости приложений (GET /app_volumes → [{pid, name, percent, muted}]).
 * Сервер (modules/volume.py) различает аудио-сессии по PID: /app_volume и /app_volume/mute
 * принимают {pid, percent} / {pid, mute}. Поэтому сессии не склеиваются по имени: у процессов
 * с одинаковым именем (Discord.exe ×2) показывается уточнение «PID 1234». Имя — как в вебе
 * (без обрезки «.exe»). Чистая Java — проверяется JVM-тестами.
 */
final class PcMixer {
    private PcMixer() {}

    static final class Session {
        final long pid;
        final String name;
        final int percent;
        final boolean muted;
        /** «PID 1234» для одноимённых сессий, иначе "". */
        String detail = "";

        Session(long pid, String name, int percent, boolean muted) {
            this.pid = pid;
            this.name = name;
            this.percent = percent;
            this.muted = muted;
        }

        /** Ключ строки (по нему приходят запросы на сервер). */
        String key() {
            return "pid:" + pid;
        }
    }

    /** Разбор ответа сервера; элементы без корректного PID пропускаются (сервер их не примет). */
    static List<Session> parse(List<PcJson.O> list) {
        List<Session> out = new ArrayList<>();
        java.util.Set<Long> seen = new java.util.HashSet<>();
        for (PcJson.O o : list) {
            Object raw = o.raw("pid");
            if (!(raw instanceof Number)) continue;
            long pid = ((Number) raw).longValue();
            if (!seen.add(pid)) continue;
            String name = o.str("name").trim();
            if (name.isEmpty()) name = "PID " + pid;
            int pct = Math.max(0, Math.min(100, o.integer("percent", 0)));
            out.add(new Session(pid, name, pct, o.bool("muted", false)));
        }
        Map<String, Integer> counts = new HashMap<>();
        for (Session s : out) {
            String k = s.name.toLowerCase(Locale.ROOT);
            Integer n = counts.get(k);
            counts.put(k, n == null ? 1 : n + 1);
        }
        for (Session s : out) {
            Integer n = counts.get(s.name.toLowerCase(Locale.ROOT));
            if (n != null && n > 1) s.detail = "PID " + s.pid;
        }
        return out;
    }

    /** Тело POST /app_volume. */
    static Map<String, Object> volumeBody(long pid, float percent) {
        return PcJson.map("pid", pid, "percent", clampPercent(percent));
    }

    /** Тело POST /app_volume/mute. */
    static Map<String, Object> muteBody(long pid, boolean mute) {
        return PcJson.map("pid", pid, "mute", mute);
    }

    static int clampPercent(float v) {
        return Math.max(0, Math.min(100, Math.round(v)));
    }
}
