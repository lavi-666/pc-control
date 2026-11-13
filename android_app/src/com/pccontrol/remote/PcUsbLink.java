package com.pccontrol.remote;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

/**
 * Finding the PC over USB tethering ("USB modem"), pure java.net (unit-tested on the JVM).
 * The server broadcasts {"pcc":1,"port":5000,"inst":"…"} to UDP 5058 every 3 s on its private
 * interfaces (core/usb_link.py); here a listener collects the senders. When the phone has a
 * tethering interface (rndis0 / usb0 / ncm0) but no beacon arrives (broadcast filtered), the small
 * tethering subnet is scanned for the server port as a fallback. Found addresses are only
 * candidates: PcRoute verifies them before the password is used.
 */
final class PcUsbLink {
    static final int BEACON_PORT = 5058;
    static final long BEACON_TTL_MS = 12000;
    private static final Pattern TETHER_IFACE = Pattern.compile("^(rndis|usb|ncm)\\d*$");

    static final class Beacon {
        final String ip;
        final int port;
        final String inst;
        final long at;

        Beacon(String ip, int port, String inst, long at) {
            this.ip = ip;
            this.port = port;
            this.inst = inst;
            this.at = at;
        }

        String url() {
            return "http://" + ip + ":" + port;
        }
    }

    static final class Iface {
        final String name, ip;
        final int prefix;

        Iface(String name, String ip, int prefix) {
            this.name = name;
            this.ip = ip;
            this.prefix = prefix;
        }
    }

    private final Map<String, Beacon> seen = new ConcurrentHashMap<>();
    private volatile boolean running;
    private volatile DatagramSocket socket;
    private Thread thread;
    private final int port;
    /** Called (from the listener thread) when a new PC address appears. */
    volatile Runnable onNewBeacon;

    private volatile long lastScanAt;
    private volatile List<String> lastScan = Collections.emptyList();

    PcUsbLink() {
        this(BEACON_PORT);
    }

    PcUsbLink(int port) {
        this.port = port;
    }

    // ------------------------------------------------------------------ beacon listener
    synchronized void start() {
        if (running) return;
        running = true;
        thread = new Thread(this::listen, "pc-usb-beacon");
        thread.setDaemon(true);
        thread.start();
    }

    synchronized void stop() {
        running = false;
        DatagramSocket s = socket;
        if (s != null) s.close();
        if (thread != null) thread.interrupt();
        thread = null;
    }

    private void listen() {
        byte[] buf = new byte[512];
        while (running) {
            DatagramSocket s = null;
            try {
                s = new DatagramSocket(null);
                s.setReuseAddress(true);
                s.setBroadcast(true);
                s.bind(new InetSocketAddress(port));
                s.setSoTimeout(5000);
                socket = s;
                while (running) {
                    DatagramPacket pk = new DatagramPacket(buf, buf.length);
                    try {
                        s.receive(pk);
                    } catch (java.net.SocketTimeoutException e) {
                        continue;
                    }
                    InetAddress from = pk.getAddress();
                    if (!(from instanceof Inet4Address)) continue;
                    Beacon b = parse(from.getHostAddress(), new String(pk.getData(), 0, pk.getLength(), StandardCharsets.UTF_8),
                            System.currentTimeMillis());
                    if (b == null) continue;
                    Beacon old = seen.put(b.ip, b);
                    Runnable cb = onNewBeacon;
                    if ((old == null || old.port != b.port) && cb != null) cb.run();
                }
            } catch (Exception e) {
                if (s != null) s.close();
                socket = null;
                if (!running) return;
                try {
                    Thread.sleep(10000); // port busy / no network: try again later
                } catch (InterruptedException ie) {
                    return;
                }
            }
        }
        DatagramSocket s = socket;
        if (s != null) s.close();
    }

    /** {"pcc":1,"port":5000,"inst":"…"} from ip, or null. */
    static Beacon parse(String ip, String text, long now) {
        if (!PcConn.isIpv4(ip)) return null;
        PcJson.O o = PcJson.parseObj(text);
        if (o.integer("pcc", 0) != 1) return null;
        int p = o.integer("port", 0);
        if (p <= 0 || p > 65535) return null;
        return new Beacon(ip, p, o.str("inst"), now);
    }

    /** Test hook / manual feed. */
    void record(Beacon b) {
        seen.put(b.ip, b);
    }

    List<Beacon> recent(long now) {
        List<Beacon> out = new ArrayList<>();
        for (Beacon b : seen.values()) if (now - b.at <= BEACON_TTL_MS) out.add(b);
        return out;
    }

    // ------------------------------------------------------------------ tethering interface
    static boolean isTetherName(String name) {
        return name != null && TETHER_IFACE.matcher(name).matches();
    }

    /** Up USB-tethering interfaces of the phone with their IPv4 address. */
    static List<Iface> tetherInterfaces() {
        List<Iface> out = new ArrayList<>();
        try {
            Enumeration<NetworkInterface> en = NetworkInterface.getNetworkInterfaces();
            if (en == null) return out;
            for (NetworkInterface ni : Collections.list(en)) {
                if (!isTetherName(ni.getName()) || !ni.isUp()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    if (ia.getAddress() instanceof Inet4Address) {
                        out.add(new Iface(ni.getName(), ia.getAddress().getHostAddress(), ia.getNetworkPrefixLength()));
                    }
                }
            }
        } catch (Exception ignored) {
            // no permission / no interfaces
        }
        return out;
    }

    static long ipToLong(String ip) {
        String[] p = ip.split("\\.");
        long v = 0;
        for (String s : p) v = (v << 8) | (Integer.parseInt(s) & 0xFF);
        return v;
    }

    static String longToIp(long v) {
        return ((v >> 24) & 0xFF) + "." + ((v >> 16) & 0xFF) + "." + ((v >> 8) & 0xFF) + "." + (v & 0xFF);
    }

    static boolean inSubnet(String ip, String ifaceIp, int prefix) {
        if (!PcConn.isIpv4(ip) || !PcConn.isIpv4(ifaceIp) || prefix < 0 || prefix > 32) return false;
        long mask = prefix == 0 ? 0 : (0xFFFFFFFFL << (32 - prefix)) & 0xFFFFFFFFL;
        return (ipToLong(ip) & mask) == (ipToLong(ifaceIp) & mask);
    }

    /** Hosts of the interface's subnet to scan (at most a /24 around the phone, without itself). */
    static List<String> scanHosts(String ifaceIp, int prefix) {
        List<String> out = new ArrayList<>();
        if (!PcConn.isIpv4(ifaceIp)) return out;
        int pf = Math.max(24, Math.min(30, prefix));
        long mask = (0xFFFFFFFFL << (32 - pf)) & 0xFFFFFFFFL;
        long net = ipToLong(ifaceIp) & mask;
        long bcast = net | (~mask & 0xFFFFFFFFL);
        long self = ipToLong(ifaceIp);
        for (long a = net + 1; a < bcast; a++) if (a != self) out.add(longToIp(a));
        return out;
    }

    /**
     * PC addresses on the tethering interfaces: beacons from those subnets; else (at most every
     * 20 s) a quick TCP scan of the subnet for the server port.
     */
    List<String> tetherUrls(int serverPort, long now) {
        List<Iface> ifs = tetherInterfaces();
        Set<String> out = new LinkedHashSet<>();
        if (ifs.isEmpty()) return new ArrayList<>(out);
        for (Beacon b : recent(now)) {
            for (Iface f : ifs) if (inSubnet(b.ip, f.ip, f.prefix)) out.add(b.url());
        }
        if (!out.isEmpty()) return new ArrayList<>(out);
        if (now - lastScanAt > 20000) {
            lastScanAt = now;
            List<String> found = new ArrayList<>();
            for (Iface f : ifs) found.addAll(scan(scanHosts(f.ip, f.prefix), serverPort, 350));
            lastScan = found;
        }
        for (String ip : lastScan) out.add("http://" + ip + ":" + serverPort);
        return new ArrayList<>(out);
    }

    /** Beacon senders that are NOT on a tethering interface (PC on the Wi-Fi network). */
    List<String> otherBeaconUrls(long now, List<String> exclude) {
        List<String> out = new ArrayList<>();
        for (Beacon b : recent(now)) {
            String u = b.url();
            if (!exclude.contains(u) && !out.contains(u)) out.add(u);
        }
        return out;
    }

    static List<String> scan(List<String> hosts, final int port, final int timeoutMs) {
        final List<String> open = Collections.synchronizedList(new ArrayList<String>());
        if (hosts.isEmpty()) return open;
        ExecutorService ex = Executors.newFixedThreadPool(Math.min(48, hosts.size()));
        for (final String h : hosts) {
            ex.execute(() -> {
                try (Socket s = new Socket()) {
                    s.connect(new InetSocketAddress(h, port), timeoutMs);
                    open.add(h);
                } catch (Exception ignored) {
                }
            });
        }
        ex.shutdown();
        try {
            ex.awaitTermination(timeoutMs * (hosts.size() / 48 + 2) + 1000L, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        ex.shutdownNow();
        return new ArrayList<>(open);
    }
}
