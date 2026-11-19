package com.pccontrol.remote;

import java.io.UnsupportedEncodingException;
import java.net.InetAddress;
import java.net.URLDecoder;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Connection model of the app (pure Java, unit-tested on the JVM): saved servers (home LAN,
 * Tailscale, custom), routing mode, token, Wake-on-LAN data, QR deep links, plus the small
 * formatting / filtering helpers the screens share. Mirrors web/js/app.js 1:1 (same storage keys).
 */
public final class PcConn {

    /** Key/value persistence (SharedPreferences on Android, a map in tests). */
    public interface Store {
        String get(String key);

        void put(String key, String value);

        void remove(String key);
    }

    public static final class MapStore implements Store {
        public final Map<String, String> m = new LinkedHashMap<>();

        @Override public String get(String key) { return m.get(key); }
        @Override public void put(String key, String value) { m.put(key, value); }
        @Override public void remove(String key) { m.remove(key); }
    }

    // storage keys = localStorage keys of the web UI
    public static final String K_LAN = "pc_lan_host";
    public static final String K_VPN = "pc_vpn_host";
    public static final String K_CUSTOM = "pc_custom_host";
    public static final String K_MODE = "pc_conn_mode";
    public static final String K_MAC = "pc_mac_address";
    public static final String K_TOKEN = "pc_token";
    public static final String K_RELAY = "pc_wol_relay";
    public static final String K_ACTIVE = "pc_active_server";
    public static final String K_LANG = "app_lang";
    /** Key that verifies the paired server on automatic routes (PcRoute), and its instance id. */
    public static final String K_ROUTE_KEY = "pc_route_key";
    public static final String K_INSTANCE = "pc_instance";
    /** Addresses saved from a deep link WITHOUT credentials: no password until they prove themselves. */
    public static final String K_UNTRUSTED = "pc_untrusted_hosts";

    public static final String MODE_AUTO = "auto";
    public static final String MODE_LAN = "lan";
    public static final String MODE_VPN = "vpn";
    public static final String MODE_CUSTOM = "custom";

    public static final class Candidate {
        public final String url;
        public final String labelKey; // i18n key or literal "Tailscale"

        public Candidate(String url, String labelKey) {
            this.url = url;
            this.labelKey = labelKey;
        }

        @Override public String toString() { return labelKey + "=" + url; }
    }

    private final Store store;
    /** Build-time defaults (assets/pc_defaults.json): token, lan, vpn, relay, mac. */
    private final Map<String, String> defaults;
    private String memoryToken = "";

    public PcConn(Store store, Map<String, String> defaults) {
        this.store = store;
        this.defaults = defaults != null ? defaults : new LinkedHashMap<String, String>();
    }

    private String saved(String k) {
        String v = store.get(k);
        return v == null ? "" : v.trim();
    }

    private String def(String k) {
        String v = defaults.get(k);
        return v == null ? "" : v.trim();
    }

    public String lanHost() {
        String s = saved(K_LAN);
        return !s.isEmpty() ? s : def("lan");
    }

    public String vpnHost() {
        String s = saved(K_VPN);
        return !s.isEmpty() ? s : def("vpn");
    }

    public String customHost() {
        return stripSlash(saved(K_CUSTOM));
    }

    public String mac() {
        String s = saved(K_MAC);
        return !s.isEmpty() ? s : def("mac");
    }

    public String relay() {
        String s = saved(K_RELAY);
        return !s.isEmpty() ? s : def("relay");
    }

    public String mode() {
        String m = saved(K_MODE);
        if (MODE_LAN.equals(m) || MODE_VPN.equals(m) || MODE_CUSTOM.equals(m)) return m;
        return MODE_AUTO;
    }

    public void setMode(String m) {
        store.put(K_MODE, m);
    }

    public String activeServer() {
        String a = saved(K_ACTIVE);
        return !a.isEmpty() ? a : lanHost();
    }

    public void setActiveServer(String url) {
        if (url != null && !url.isEmpty()) store.put(K_ACTIVE, url);
    }

    /** web getToken(): session (memory) → remembered → embedded in the APK at build time. */
    public String token() {
        if (!memoryToken.isEmpty()) return memoryToken;
        String s = saved(K_TOKEN);
        if (!s.isEmpty()) return s;
        return def("token");
    }

    public boolean hasToken() {
        return !token().isEmpty();
    }

    public void setToken(String tok, boolean remember) {
        String before = token();
        memoryToken = tok == null ? "" : tok.trim();
        if (remember && !memoryToken.isEmpty()) store.put(K_TOKEN, memoryToken);
        else store.remove(K_TOKEN);
        // the route key is derived from the password on the server: a new password = a new key
        if (!before.equals(memoryToken)) store.remove(K_ROUTE_KEY);
    }

    /** Token was rejected (401): forget the remembered one (as the web UI does). */
    public void dropToken() {
        memoryToken = "";
        store.remove(K_TOKEN);
        store.remove(K_ROUTE_KEY);
    }

    // ------------------------------------------------------------------ route verification
    public String routeKey() {
        return saved(K_ROUTE_KEY);
    }

    public String instance() {
        return saved(K_INSTANCE);
    }

    /** Answer of /api/route/key (only ever asked from an already verified / user-chosen server). */
    public void setRouteKey(String key, String instance) {
        putOrRemove(K_ROUTE_KEY, key);
        if (instance != null && !instance.trim().isEmpty()) store.put(K_INSTANCE, instance.trim());
    }

    public List<String> untrustedHosts() {
        List<String> out = new ArrayList<>();
        for (String s : saved(K_UNTRUSTED).split("\\s+")) if (!s.isEmpty()) out.add(s);
        return out;
    }

    private void setUntrusted(List<String> hosts) {
        StringBuilder sb = new StringBuilder();
        for (String h : hosts) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(h);
        }
        putOrRemove(K_UNTRUSTED, sb.toString());
    }

    /** The address proved to be our server, or the user entered / confirmed it. */
    public void markTrusted(String url) {
        String u = stripSlash(url);
        List<String> l = untrustedHosts();
        if (l.remove(u)) setUntrusted(l);
    }

    public boolean isUntrusted(String url) {
        return untrustedHosts().contains(stripSlash(url));
    }

    public String savedRaw(String key) {
        return saved(key);
    }

    public void putOrRemove(String key, String value) {
        if (value == null || value.trim().isEmpty()) store.remove(key);
        else store.put(key, value.trim());
    }

    public String lang() {
        return saved(K_LANG);
    }

    public void setLang(String l) {
        store.put(K_LANG, l);
    }

    /** web getApiBase() for the standalone app. */
    public String apiBase() {
        String m = mode();
        if (MODE_LAN.equals(m)) return lanHost();
        if (MODE_VPN.equals(m)) return vpnHost();
        String custom = customHost();
        if (MODE_CUSTOM.equals(m) && !custom.isEmpty()) return custom;
        return activeServer();
    }

    /** web probeBestServer() candidate list (no browser origin in the app). */
    public List<Candidate> candidates() {
        List<Candidate> out = new ArrayList<>();
        String m = mode();
        String lan = lanHost(), vpn = vpnHost(), custom = customHost();
        if (MODE_LAN.equals(m)) {
            if (!lan.isEmpty()) out.add(new Candidate(lan, "label_home"));
        } else if (MODE_VPN.equals(m)) {
            if (!vpn.isEmpty()) out.add(new Candidate(vpn, "Tailscale"));
        } else if (MODE_CUSTOM.equals(m) && !custom.isEmpty()) {
            out.add(new Candidate(custom, "label_custom_ip"));
        } else {
            if (!custom.isEmpty()) out.add(new Candidate(custom, "label_custom_ip"));
            if (!lan.isEmpty()) out.add(new Candidate(lan, "label_home"));
            if (!vpn.isEmpty()) out.add(new Candidate(vpn, "Tailscale"));
        }
        // de-duplicate identical addresses (LAN typed again as custom etc.)
        Set<String> seen = new LinkedHashSet<>();
        List<Candidate> uniq = new ArrayList<>();
        for (Candidate c : out) if (seen.add(c.url)) uniq.add(c);
        return uniq;
    }

    // ------------------------------------------------------------------ deep link / QR
    /**
     * pccontrol://connect?lan=..&vpn=..&token=..&mac=..&relay=..&ticket=.. (also lan_host / vpn_host).
     * Saves the network parameters, returns the pairing ticket to exchange (or "").
     */
    public String applyConnectParams(Map<String, String> q) {
        String lan = first(q, "lan", "lan_host");
        String vpn = first(q, "vpn", "vpn_host");
        String tok = first(q, "token");
        String mac = first(q, "mac");
        String relay = first(q, "relay");
        String ticket = first(q, "ticket");
        // Known bug A-7: a link with only ?lan=… used to switch the active server silently, and the
        // saved password went to that address. Now an address that arrives without credentials
        // (no token / ticket) is saved as untrusted: the password is sent there only after it proves
        // to be the paired server (PcRoute), or after the user signs in to it.
        boolean creds = !tok.isEmpty() || !ticket.isEmpty() || !hasToken();
        List<String> untrusted = untrustedHosts();
        if (!lan.isEmpty()) {
            String n = stripSlash(lan);
            boolean changed = !n.equals(lanHost());
            store.put(K_LAN, n);
            if (creds) {
                store.put(K_ACTIVE, n);
                untrusted.remove(n);
            } else if (changed && !untrusted.contains(n)) {
                untrusted.add(n);
            }
        }
        if (!vpn.isEmpty()) {
            String n = stripSlash(vpn);
            boolean changed = !n.equals(vpnHost());
            store.put(K_VPN, n);
            if (creds) untrusted.remove(n);
            else if (changed && !untrusted.contains(n)) untrusted.add(n);
        }
        setUntrusted(untrusted);
        if (!mac.isEmpty()) store.put(K_MAC, mac);
        if (!relay.isEmpty()) store.put(K_RELAY, stripSlash(relay));
        if (!tok.isEmpty()) setToken(tok, true);
        return ticket;
    }

    /** First non-empty value of the given query keys ("" if none). */
    public static String firstParam(Map<String, String> q, String... keys) {
        return first(q, keys);
    }

    private static String first(Map<String, String> q, String... keys) {
        for (String k : keys) {
            String v = q.get(k);
            if (v != null && !v.trim().isEmpty()) return v.trim();
        }
        return "";
    }

    /** Decodes an x-www-form-urlencoded query ("a=1&b=%20x"). */
    public static Map<String, String> parseQuery(String query) {
        Map<String, String> out = new LinkedHashMap<>();
        if (query == null || query.isEmpty()) return out;
        String q = query.startsWith("?") ? query.substring(1) : query;
        for (String part : q.split("&")) {
            if (part.isEmpty()) continue;
            int eq = part.indexOf('=');
            String k = eq >= 0 ? part.substring(0, eq) : part;
            String v = eq >= 0 ? part.substring(eq + 1) : "";
            try {
                out.put(URLDecoder.decode(k, "UTF-8"), URLDecoder.decode(v, "UTF-8"));
            } catch (UnsupportedEncodingException | IllegalArgumentException e) {
                out.put(k, v);
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ URLs
    public static String stripSlash(String s) {
        if (s == null) return "";
        String r = s.trim();
        while (r.endsWith("/")) r = r.substring(0, r.length() - 1);
        return r;
    }

    private static final Pattern HAS_SCHEME = Pattern.compile("^https?://.*", Pattern.CASE_INSENSITIVE);
    private static final Pattern HAS_PORT = Pattern.compile(".*:\\d+$");

    /** web normalizeHostUrl(): "192.168.0.5" → "http://192.168.0.5:5000". */
    public static String normalizeHostUrl(String raw) {
        String s = stripSlash(raw);
        if (s.isEmpty()) return "";
        if (!HAS_SCHEME.matcher(s).matches()) s = "http://" + s;
        String rest = s.replaceFirst("(?i)^https?://", "");
        if (!HAS_PORT.matcher(rest).matches()) s = s + ":5000";
        return s;
    }

    /** "http://192.168.0.5:5000" → "192.168.0.5" (route card subtitle). */
    public static String hostOnly(String url) {
        if (url == null) return "";
        return url.replaceFirst("(?i)^https?://", "").replaceFirst(":\\d+$", "");
    }

    /** JavaScript encodeURIComponent (the server unquotes the X-Auth-Token header). */
    public static String encodeURIComponent(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder();
        byte[] bytes;
        try {
            bytes = s.getBytes("UTF-8");
        } catch (UnsupportedEncodingException e) {
            return s;
        }
        for (byte b : bytes) {
            int c = b & 0xFF;
            if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
                    || "-_.!~*'()".indexOf(c) >= 0) {
                sb.append((char) c);
            } else {
                sb.append('%').append(Character.toUpperCase(Character.forDigit(c >> 4, 16)))
                        .append(Character.toUpperCase(Character.forDigit(c & 15, 16)));
            }
        }
        return sb.toString();
    }

    private static final SecureRandom RNG = new SecureRandom();

    /** X-Request-Id for mutating requests (web generateRequestId). */
    public static String requestId() {
        byte[] b = new byte[16];
        RNG.nextBytes(b);
        StringBuilder sb = new StringBuilder("req_");
        for (byte x : b) sb.append(String.format("%02x", x & 0xFF));
        return sb.toString();
    }

    // ------------------------------------------------------------------ Wake-on-LAN
    /** web getWolTargetsList(): global broadcast + PC IP + its /24 broadcast. */
    public static List<String> wolTargets(String lanHost) {
        List<String> t = new ArrayList<>();
        t.add("255.255.255.255");
        String host = hostOnly(lanHost == null ? "" : lanHost.trim());
        if (host.matches("^(\\d{1,3}\\.){3}\\d{1,3}$")) {
            t.add(host);
            String bc = host.substring(0, host.lastIndexOf('.')) + ".255";
            if (!t.contains(bc)) t.add(bc);
        } else {
            t.add("192.168.0.255");
            t.add("192.168.0.100");
        }
        return t;
    }

    /** 6 × 0xFF + 16 × MAC (102 bytes), or null for an invalid MAC. */
    public static byte[] magicPacket(String mac) {
        if (mac == null) return null;
        String hex = mac.replaceAll("[^0-9A-Fa-f]", "");
        if (hex.length() != 12) return null;
        byte[] m = new byte[6];
        for (int i = 0; i < 6; i++) m[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        byte[] p = new byte[6 + 16 * 6];
        for (int i = 0; i < 6; i++) p[i] = (byte) 0xFF;
        for (int i = 6; i < p.length; i += 6) System.arraycopy(m, 0, p, i, 6);
        return p;
    }

    public static boolean isIpv4(String s) {
        if (s == null || !s.matches("^(\\d{1,3}\\.){3}\\d{1,3}$")) return false;
        for (String p : s.split("\\.")) if (Integer.parseInt(p) > 255) return false;
        return true;
    }

    /** Resolve a literal IPv4 without DNS (UDP targets are numeric). */
    public static InetAddress ipv4(String s) throws java.net.UnknownHostException {
        String[] p = s.split("\\.");
        byte[] b = new byte[4];
        for (int i = 0; i < 4; i++) b[i] = (byte) Integer.parseInt(p[i]);
        return InetAddress.getByAddress(b);
    }

    // ------------------------------------------------------------------ formatting
    /** web fmtTime(): 0:00 style. */
    public static String fmtTime(double sec) {
        if (Double.isNaN(sec) || Double.isInfinite(sec) || sec <= 0) return "0:00";
        long total = (long) Math.floor(sec);
        long m = total / 60, s = total % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    /** web fmtHistoryTime(): HH:MM local time of a unix timestamp (seconds). */
    public static String fmtClock(double ts) {
        if (ts <= 0) return "";
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis((long) (ts * 1000));
        return String.format(Locale.ROOT, "%02d:%02d", c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE));
    }

    /** Shutdown countdown text: m:ss. */
    public static String fmtCountdown(long remaining) {
        long m = Math.max(0, remaining) / 60, s = Math.max(0, remaining) % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    /** web renderProcessesList() filter: name / pid substring, then separators-insensitive match. */
    public static List<PcJson.O> filterProcesses(List<PcJson.O> all, String query) {
        String raw = query == null ? "" : query.trim().toLowerCase(Locale.ROOT);
        if (raw.isEmpty()) return new ArrayList<>(all);
        String norm = raw.replaceAll("[\\-_.\\s]", "");
        List<PcJson.O> out = new ArrayList<>();
        for (PcJson.O p : all) {
            String name = p.str("name").toLowerCase(Locale.ROOT);
            String pid = p.str("pid");
            if (name.contains(raw) || pid.contains(raw)) { out.add(p); continue; }
            if (!norm.isEmpty() && name.replaceAll("[\\-_.\\s]", "").contains(norm)) out.add(p);
        }
        return out;
    }

    // ------------------------------------------------------------------ presets
    /** Name of an "app" step: explicit name, else file name of the target without .lnk. */
    public static String appStepName(String name, String target) {
        String n = name == null ? "" : name.trim();
        if (!n.isEmpty()) return n;
        String t = target == null ? "" : target.trim();
        String[] parts = t.split("[/\\\\]");
        String last = parts.length > 0 ? parts[parts.length - 1] : t;
        return last.replaceAll("(?i)\\.lnk$", "");
    }

    /** "youtube.com" → "https://youtube.com" (web addUrlStepFromInputs). */
    public static String normalizeStepUrl(String raw) {
        String t = raw == null ? "" : raw.trim();
        if (t.isEmpty()) return "";
        if (!t.matches("(?i)^https?://.*")) t = "https://" + t;
        return t;
    }

    /** Default URL step name: host without www. */
    public static String urlStepName(String name, String url) {
        String n = name == null ? "" : name.trim();
        if (!n.isEmpty()) return n;
        String u = (url == null ? "" : url).replaceFirst("(?i)^https?://(www\\.)?", "");
        int slash = u.indexOf('/');
        return slash >= 0 ? u.substring(0, slash) : u;
    }

    public static int clampDelay(String raw) {
        int v;
        try {
            v = Integer.parseInt(raw == null ? "" : raw.trim());
        } catch (NumberFormatException e) {
            v = 3;
        }
        return Math.max(1, Math.min(300, v));
    }
}
