package com.pccontrol.remote;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Automatic route to the PC (pure Java, unit-tested on the JVM): USB cable via adb reverse
 * (127.0.0.1) → USB tethering → saved custom / home LAN address → Tailscale. Every candidate is
 * asked GET /status?nonce=… WITHOUT the password; the server answers with
 * proof = HMAC-SHA256(route key, "pcc-route|nonce|instance") (server core/route_auth.py). The route
 * key is fetched once after a normal authenticated connection (/api/route/key). The saved password is
 * sent only to a route that proved it is the same server — a deep link / stale DHCP address /
 * other app on 127.0.0.1 / another PC on the cable never gets it.
 */
public final class PcRoute {
    private PcRoute() {}

    /** Priority order (lower = preferred). */
    public static final int USB_ADB = 0, USB_TETHER = 1, CUSTOM = 2, LAN = 3, VPN = 4;

    public static final class Target {
        public final String url;
        public final int kind;
        /** Address the user typed / confirmed (settings, login, QR with credentials). */
        public final boolean trusted;

        public Target(String url, int kind, boolean trusted) {
            this.url = PcConn.stripSlash(url);
            this.kind = kind;
            this.trusted = trusted;
        }

        @Override public String toString() { return kind + (trusted ? "*" : "") + "=" + url; }
    }

    public static final class Probe {
        public final Target target;
        public volatile boolean done;
        public boolean answered, verified, proofMismatch;
        public PcJson.O status = new PcJson.O(new java.util.LinkedHashMap<String, Object>());

        public Probe(Target t) {
            target = t;
        }
    }

    public static String labelKey(int kind) {
        switch (kind) {
            case USB_ADB: return "route_usb";
            case USB_TETHER: return "route_usb_tether";
            case CUSTOM: return "route_custom";
            case VPN: return "route_vpn";
            default: return "route_lan";
        }
    }

    public static boolean isUsb(int kind) {
        return kind == USB_ADB || kind == USB_TETHER;
    }

    public static boolean isLoopback(String url) {
        String h = PcConn.hostOnly(url == null ? "" : url.trim()).toLowerCase(Locale.ROOT);
        return h.equals("127.0.0.1") || h.equals("localhost") || h.equals("[::1]");
    }

    public static boolean isTailscale(String url) {
        String h = PcConn.hostOnly(url == null ? "" : url.trim());
        if (!PcConn.isIpv4(h)) return h.toLowerCase(Locale.ROOT).endsWith(".ts.net");
        String[] p = h.split("\\.");
        int a = Integer.parseInt(p[0]), b = Integer.parseInt(p[1]);
        return a == 100 && b >= 64 && b <= 127;
    }

    /** Kind of an address by its look (used for labels of the active server). */
    public static int kindOf(String url) {
        if (isLoopback(url)) return USB_ADB;
        if (isTailscale(url)) return VPN;
        return LAN;
    }

    /** Port of "http://host:port" (5000 when absent / invalid). */
    public static int portOf(String url) {
        String s = url == null ? "" : url.trim().replaceFirst("(?i)^https?://", "");
        int slash = s.indexOf('/');
        if (slash >= 0) s = s.substring(0, slash);
        int colon = s.lastIndexOf(':');
        if (colon > 0) {
            try {
                int p = Integer.parseInt(s.substring(colon + 1));
                if (p > 0 && p < 65536) return p;
            } catch (NumberFormatException ignored) {
            }
        }
        return 5000;
    }

    // ------------------------------------------------------------------ proof
    private static final SecureRandom RNG = new SecureRandom();

    public static String newNonce() {
        byte[] b = new byte[16];
        RNG.nextBytes(b);
        return hex(b);
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) sb.append(String.format("%02x", x & 0xFF));
        return sb.toString();
    }

    public static String hmacHex(String key, String msg) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return hex(mac.doFinal(msg.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            return "";
        }
    }

    public static String expectedProof(String routeKey, String nonce, String instance) {
        if (routeKey == null || routeKey.isEmpty()) return "";
        return hmacHex(routeKey, "pcc-route|" + nonce + "|" + (instance == null ? "" : instance));
    }

    /** Fills answered / verified / proofMismatch of a probe from the /status JSON (or null = no answer). */
    public static void evaluate(Probe p, PcJson.O status, String nonce, String routeKey, String expectedInstance) {
        p.answered = status != null && (status.has("status") || status.has("hostname"));
        if (!p.answered) return;
        p.status = status;
        String proof = status.str("proof");
        String inst = status.str("instance");
        if (routeKey == null || routeKey.isEmpty() || proof.isEmpty()) return;
        String want = expectedProof(routeKey, nonce, inst);
        boolean ok = !want.isEmpty() && MessageDigest.isEqual(want.getBytes(StandardCharsets.UTF_8),
                proof.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8));
        if (ok && expectedInstance != null && !expectedInstance.isEmpty() && !expectedInstance.equals(inst)) ok = false;
        p.verified = ok;
        p.proofMismatch = !ok;
    }

    /**
     * May the saved password be sent to this route?
     * - proof matches the route key → yes;
     * - a proof that does NOT match (another server / changed password) → never;
     * - no proof at all (server older than the app, or no route key yet): with no saved password
     *   there is nothing to leak (the login window asks for it); otherwise only addresses the user
     *   entered (the behaviour before route keys). Automatic routes (USB, tethering, beacons, deep
     *   links without credentials) always need a matching proof.
     */
    public static boolean acceptable(Probe p, boolean haveRouteKey, boolean haveToken) {
        if (!p.answered) return false;
        if (p.verified) return true;
        if (p.proofMismatch) return false;
        if (!haveToken) return !haveRouteKey || p.target.trusted;
        return p.target.trusted;
    }

    public static final int UNDECIDED = -2, NONE = -1;

    /**
     * Index of the best acceptable probe (list is in priority order): a probe wins only when every
     * higher-priority probe has finished. UNDECIDED while waiting; with finalPick, unfinished probes
     * count as failed.
     */
    public static int pick(List<Probe> probes, boolean haveRouteKey, boolean haveToken, boolean finalPick) {
        for (int i = 0; i < probes.size(); i++) {
            Probe p = probes.get(i);
            if (!p.done && !finalPick) return UNDECIDED;
            if (p.done && acceptable(p, haveRouteKey, haveToken)) return i;
        }
        return NONE;
    }

    /** A user-entered address answered but proved to be another server (or the password changed). */
    public static Probe trustedMismatch(List<Probe> probes) {
        for (Probe p : probes) if (p.done && p.answered && p.proofMismatch && p.target.trusted) return p;
        return null;
    }

    /** Adds a target (if its address is new) keeping the priority order; a trusted duplicate upgrades trust. */
    public static List<Target> withTarget(List<Target> list, Target extra) {
        List<Target> out = new ArrayList<>();
        boolean added = false;
        for (Target t : list) {
            if (t.url.equals(extra.url)) {
                out.add(extra.trusted && !t.trusted ? new Target(t.url, t.kind, true) : t);
                added = true;
            } else {
                out.add(t);
            }
        }
        if (!added && !extra.url.isEmpty()) {
            int i = 0;
            while (i < out.size() && out.get(i).kind <= extra.kind) i++;
            out.add(i, extra);
        }
        return out;
    }

    // ------------------------------------------------------------------ candidates
    /**
     * Candidate list in priority order. Auto mode: USB (adb reverse, phone's own 127.0.0.1) and the
     * tethering / beacon addresses (untrusted until verified), then custom, LAN, Tailscale. A forced
     * mode (LAN / VPN / custom) keeps only that address.
     *
     * @param tetherUrls  PC addresses found on the phone's USB tethering interface
     * @param beaconUrls  PC addresses announced by the server's beacon on other networks (Wi-Fi)
     * @param untrusted   saved addresses that came from a deep link without credentials
     */
    public static List<Target> candidates(PcConn conn, Collection<String> tetherUrls, Collection<String> beaconUrls,
                                          Collection<String> untrusted) {
        List<Target> out = new ArrayList<>();
        String m = conn.mode();
        String lan = conn.lanHost(), vpn = conn.vpnHost(), custom = conn.customHost();
        Set<String> bad = new LinkedHashSet<>();
        if (untrusted != null) for (String u : untrusted) bad.add(PcConn.stripSlash(u));
        if (PcConn.MODE_LAN.equals(m)) {
            if (!lan.isEmpty()) out.add(new Target(lan, kindOf(lan) == USB_ADB ? USB_ADB : LAN, !bad.contains(lan)));
        } else if (PcConn.MODE_VPN.equals(m)) {
            if (!vpn.isEmpty()) out.add(new Target(vpn, VPN, !bad.contains(vpn)));
        } else if (PcConn.MODE_CUSTOM.equals(m) && !custom.isEmpty()) {
            out.add(new Target(custom, CUSTOM, !bad.contains(custom)));
        } else {
            int port = portOf(!lan.isEmpty() ? lan : (!custom.isEmpty() ? custom : vpn));
            out.add(new Target("http://127.0.0.1:" + port, USB_ADB, false));
            if (tetherUrls != null) for (String u : tetherUrls) out.add(new Target(u, USB_TETHER, false));
            if (!custom.isEmpty()) out.add(new Target(custom, CUSTOM, !bad.contains(custom)));
            if (!lan.isEmpty()) out.add(new Target(lan, kindOf(lan) == VPN ? VPN : LAN, !bad.contains(lan)));
            if (beaconUrls != null) for (String u : beaconUrls) out.add(new Target(u, kindOf(u) == VPN ? VPN : LAN, false));
            if (!vpn.isEmpty()) out.add(new Target(vpn, VPN, !bad.contains(vpn)));
        }
        // stable sort by priority, then de-duplicate (first = most trusted / best kind wins)
        List<Target> sorted = new ArrayList<>();
        for (int k = USB_ADB; k <= VPN; k++) for (Target t : out) if (t.kind == k) sorted.add(t);
        List<Target> uniq = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (Target t : sorted) {
            if (t.url.isEmpty()) continue;
            if (seen.add(t.url)) {
                uniq.add(t);
            } else if (t.trusted) { // same address typed by the user: keep its trust
                for (int i = 0; i < uniq.size(); i++) {
                    if (uniq.get(i).url.equals(t.url) && !uniq.get(i).trusted) uniq.set(i, new Target(t.url, uniq.get(i).kind, true));
                }
            }
        }
        return uniq;
    }
}
