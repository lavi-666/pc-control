package com.pccontrol.remote;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Localisation of the native app = the dictionary of the web interface (web/js/i18n.js):
 * same keys, same {placeholder} substitution, same fallback (current language → ru → key).
 */
public final class PcI18n {
    public static final String[] LANGS = {"uk", "ru", "en"};
    private static final Map<String, Map<String, String>> DICTS = new HashMap<>();

    static {
        DICTS.put("ru", toMap(PcStrings.RU));
        DICTS.put("uk", toMap(PcStrings.UK));
        DICTS.put("en", toMap(PcStrings.EN));
    }

    private static Map<String, String> toMap(String[] kv) {
        Map<String, String> m = new HashMap<>(kv.length);
        for (int i = 0; i + 1 < kv.length; i += 2) m.put(kv[i], kv[i + 1]);
        return m;
    }

    private String lang;

    public PcI18n(String lang) {
        setLang(lang);
    }

    public void setLang(String l) {
        lang = DICTS.containsKey(l) ? l : "en"; // QA T-3: unknown language → English
    }

    public String lang() {
        return lang;
    }

    /** Saved choice wins; otherwise device language uk / ru / en; anything else → ru (as the web UI). */
    public static String resolve(String saved, Locale device) {
        if (saved != null && DICTS.containsKey(saved)) return saved;
        String nav = device != null ? device.getLanguage().toLowerCase(Locale.ROOT) : "";
        if (nav.startsWith("uk")) return "uk";
        if (nav.startsWith("ru")) return "ru";
        if (nav.startsWith("en")) return "en";
        return "en"; // QA T-3: any other device language → English (was Russian)
    }

    public static boolean has(String lang, String key) {
        Map<String, String> d = DICTS.get(lang);
        return d != null && d.containsKey(key);
    }

    /** t("msg_play_track", "title", "Song") — vars are name / value pairs. */
    public String t(String key, Object... vars) {
        Map<String, String> d = DICTS.get(lang);
        String s = d != null ? d.get(key) : null;
        if (s == null || s.isEmpty()) s = DICTS.get("ru").get(key);
        if (s == null) s = key;
        for (int i = 0; i + 1 < vars.length; i += 2) {
            s = s.replace("{" + vars[i] + "}", String.valueOf(vars[i + 1]));
        }
        return s;
    }
}
