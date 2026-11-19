package com.pccontrol.remote;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * HTTP client of the native app (pure Java / HttpURLConnection, blocking — always called from a
 * worker thread). Same contract as web apiFetch(): X-Auth-Token = encodeURIComponent(token),
 * X-Request-Id on mutating requests, JSON bodies.
 */
public final class PcHttp {
    private PcHttp() {}

    public static final int CONNECT_TIMEOUT = 4000;
    public static final int READ_TIMEOUT = 8000;
    public static final int MAX_BODY = 32 * 1024 * 1024;
    /** UI language (uk / ru / en): server messages come back in it (QA T-1). */
    public static volatile String acceptLanguage = "";

    public static final class Resp {
        public int code;
        public byte[] body = new byte[0];
        public String contentType = "";
        public Exception error;
        public long millis;
        public String url = "";
        private PcJson.O json;

        public boolean ok() {
            return error == null && code >= 200 && code < 300;
        }

        public boolean unauthorized() {
            return error == null && code == 401;
        }

        public boolean timedOut() {
            return error instanceof SocketTimeoutException;
        }

        public String text() {
            return new String(body, StandardCharsets.UTF_8);
        }

        public PcJson.O json() {
            if (json == null) json = PcJson.parseObj(text());
            return json;
        }

        /** Top-level JSON array (e.g. /processes, /app_volumes); empty list otherwise. */
        public List<PcJson.O> jsonArray() {
            try {
                return PcJson.objsOf(PcJson.parse(text()));
            } catch (RuntimeException e) {
                return new java.util.ArrayList<>();
            }
        }

        /** Server "message" (for the status line), or "". */
        public String message() {
            return error == null ? json().str("message", "") : "";
        }
    }

    public static String join(String base, String path) {
        if (path.startsWith("http://") || path.startsWith("https://")) return path;
        String b = PcConn.stripSlash(base);
        return b + (path.startsWith("/") ? path : "/" + path);
    }

    /**
     * @param body null (no body), a String (sent as is) or a Map / List / PcJson.O (sent as JSON)
     */
    public static Resp request(String base, String method, String path, String token, Object body,
                               int connectTimeoutMs, int readTimeoutMs, Map<String, String> headers) {
        Resp r = new Resp();
        long t0 = System.nanoTime();
        HttpURLConnection c = null;
        try {
            if (base == null || base.trim().isEmpty()) {
                if (!path.startsWith("http")) throw new java.net.MalformedURLException("no server address");
            }
            r.url = join(base == null ? "" : base, path);
            c = (HttpURLConnection) new URL(r.url).openConnection();
            c.setConnectTimeout(connectTimeoutMs);
            c.setReadTimeout(readTimeoutMs);
            c.setUseCaches(false);
            // QA R-17: Android's HttpURLConnection (OkHttp) carries custom headers such as X-Auth-Token
            // over a redirect to another host. The PC Control server never redirects: an authenticated
            // request does not follow redirects at all.
            c.setInstanceFollowRedirects(token == null || token.isEmpty());
            c.setRequestMethod(method);
            c.setRequestProperty("Accept", "application/json, */*");
            c.setRequestProperty("Cache-Control", "no-store");
            if (!acceptLanguage.isEmpty()) c.setRequestProperty("Accept-Language", acceptLanguage);
            if (token != null && !token.isEmpty()) {
                c.setRequestProperty("X-Auth-Token", PcConn.encodeURIComponent(token));
            }
            boolean mutating = "POST".equals(method) || "PUT".equals(method) || "DELETE".equals(method);
            if (mutating) c.setRequestProperty("X-Request-Id", PcConn.requestId());
            if (headers != null) for (Map.Entry<String, String> h : headers.entrySet()) c.setRequestProperty(h.getKey(), h.getValue());
            byte[] payload = null;
            if (body != null) {
                String s = body instanceof String ? (String) body : PcJson.stringify(body);
                payload = s.getBytes(StandardCharsets.UTF_8);
                c.setRequestProperty("Content-Type", "application/json");
            } else if (mutating) {
                payload = new byte[0];
            }
            if (payload != null) {
                c.setDoOutput(true);
                c.setFixedLengthStreamingMode(payload.length);
                try (OutputStream os = c.getOutputStream()) {
                    os.write(payload);
                }
            }
            r.code = c.getResponseCode();
            String ct = c.getContentType();
            r.contentType = ct == null ? "" : ct;
            InputStream in = r.code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in != null) {
                try (InputStream is = in) {
                    r.body = readAll(is, MAX_BODY);
                }
            }
        } catch (Exception e) {
            r.error = e;
        } finally {
            if (c != null) c.disconnect();
            r.millis = (System.nanoTime() - t0) / 1_000_000L;
        }
        // measurements: method, host, path WITHOUT query (no secrets), status, ms
        PcLog.i("http " + method + " " + PcConn.hostOnly(base == null ? "" : base) + " " + PcLog.path(path)
                + " -> " + (r.error != null ? r.error.getClass().getSimpleName() : String.valueOf(r.code)) + " " + r.millis + "ms");
        return r;
    }

    public static byte[] readAll(InputStream is, int max) throws java.io.IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = is.read(buf)) > 0) {
            bos.write(buf, 0, n);
            if (bos.size() > max) throw new java.io.IOException("response too large");
        }
        return bos.toByteArray();
    }

    public static Resp get(String base, String path, String token, int timeoutMs) {
        return request(base, "GET", path, token, null, Math.min(timeoutMs, CONNECT_TIMEOUT), timeoutMs, null);
    }

    // ------------------------------------------------------------------ server probing
    public static final class ProbeResult {
        public final PcConn.Candidate candidate;
        public final PcJson.O status;

        ProbeResult(PcConn.Candidate c, PcJson.O s) {
            candidate = c;
            status = s;
        }
    }

    public static final class RouteResult {
        /** Winner (null = no acceptable route). */
        public final PcRoute.Probe winner;
        public final List<PcRoute.Probe> all;

        RouteResult(PcRoute.Probe w, List<PcRoute.Probe> all) {
            winner = w;
            this.all = all;
        }
    }

    /**
     * Automatic route choice (PcRoute): GET /status?nonce=… on every target in parallel, WITHOUT the
     * password. Returns as soon as the best route by priority is known (a lower-priority answer waits
     * only for the higher-priority probes still running), or after timeoutMs.
     */
    public static RouteResult probeRoutes(List<PcRoute.Target> targets, final String routeKey, final String instance,
                                          final boolean haveToken, final int timeoutMs) {
        final List<PcRoute.Probe> probes = new java.util.ArrayList<>();
        if (targets == null || targets.isEmpty()) return new RouteResult(null, probes);
        for (PcRoute.Target t : targets) probes.add(new PcRoute.Probe(t));
        final boolean haveKey = routeKey != null && !routeKey.isEmpty();
        final String nonce = PcRoute.newNonce();
        final CountDownLatch decided = new CountDownLatch(1);
        final Object lock = new Object();
        for (final PcRoute.Probe p : probes) {
            Thread th = new Thread(new Runnable() {
                @Override
                public void run() {
                    PcJson.O js = null;
                    try {
                        // the phone's own 127.0.0.1 answers (or refuses) at once
                        int connect = p.target.kind == PcRoute.USB_ADB ? 800 : Math.min(timeoutMs, 3000);
                        Resp r = request(p.target.url, "GET", "/status?nonce=" + nonce, null, null, connect, timeoutMs, null);
                        if (r.ok()) js = r.json();
                    } finally {
                        synchronized (lock) {
                            PcRoute.evaluate(p, js, nonce, routeKey, instance);
                            p.done = true;
                            if (PcRoute.pick(probes, haveKey, haveToken, false) != PcRoute.UNDECIDED) decided.countDown();
                        }
                    }
                }
            }, "pc-route-probe");
            th.setDaemon(true);
            th.start();
        }
        try {
            decided.await(timeoutMs + 500L, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        synchronized (lock) {
            int i = PcRoute.pick(probes, haveKey, haveToken, true);
            return new RouteResult(i >= 0 ? probes.get(i) : null, probes);
        }
    }

    /**
     * web probeBestServer(): GET /status on every candidate in parallel, the first that answers
     * 200 + JSON wins (Promise.any). Returns null when none answers within the timeout.
     */
    public static ProbeResult probe(List<PcConn.Candidate> candidates, final String token, final int timeoutMs) {
        if (candidates == null || candidates.isEmpty()) return null;
        final AtomicReference<ProbeResult> winner = new AtomicReference<>();
        final CountDownLatch done = new CountDownLatch(1);
        final AtomicInteger pending = new AtomicInteger(candidates.size());
        for (final PcConn.Candidate cand : candidates) {
            Thread t = new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Resp r = request(cand.url, "GET", "/status", token, null, Math.min(timeoutMs, 3000), timeoutMs, null);
                        if (r.ok()) {
                            PcJson.O js = r.json();
                            if (js.has("status") || js.has("hostname")) {
                                if (winner.compareAndSet(null, new ProbeResult(cand, js))) done.countDown();
                            }
                        }
                    } finally {
                        if (pending.decrementAndGet() == 0) done.countDown();
                    }
                }
            }, "pc-probe");
            t.setDaemon(true);
            t.start();
        }
        try {
            done.await(timeoutMs + 500L, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return winner.get();
    }
}
