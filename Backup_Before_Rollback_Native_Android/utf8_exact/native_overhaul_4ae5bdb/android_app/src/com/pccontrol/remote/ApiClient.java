package com.pccontrol.remote;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * ApiClient - Полностью нативный клиент сетевых запросов к Windows-серверу PC Control.
 * Обеспечивает:
 * 1. Реальные асинхронные HTTP/JSON запросы без WebView.
 * 2. Автоматическое сохранение и загрузку адреса сервера и токена в SharedPreferences.
 * 3. LAN автодискавери сервера в локальной сети Wi-Fi.
 * 4. Управление питанием, медиа, громкостью, клавиатурой и мышью.
 */
public class ApiClient {
    private static final String TAG = "PCControl_ApiClient";
    private static final String PREFS_NAME = "pccontrol_native_prefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_AUTH_TOKEN = "auth_token";
    private static final String DEFAULT_SERVER_URL = "http://192.168.0.101:5000";
    private static final String DEFAULT_TOKEN = "<REDACTED>";

    private static ApiClient instance;
    private final Context context;
    private final SharedPreferences prefs;
    private final ExecutorService executor = Executors.newFixedThreadPool(4);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private String serverUrl;
    private String authToken;

    public interface ApiCallback {
        void onSuccess(JSONObject response);
        void onError(String error, int statusCode);
    }

    public interface DiscoveryCallback {
        void onDiscovered(String foundUrl);
        void onNotFound();
    }

    public static synchronized ApiClient getInstance(Context context) {
        if (instance == null) {
            instance = new ApiClient(context.getApplicationContext());
        }
        return instance;
    }

    private ApiClient(Context context) {
        this.context = context;
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        this.serverUrl = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL);
        this.authToken = prefs.getString(KEY_AUTH_TOKEN, DEFAULT_TOKEN);
    }

    public synchronized String getServerUrl() {
        return serverUrl != null ? serverUrl : DEFAULT_SERVER_URL;
    }

    public synchronized void setServerUrl(String url) {
        if (url == null) url = "";
        url = url.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        if (!url.isEmpty() && !url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        this.serverUrl = url;
        prefs.edit().putString(KEY_SERVER_URL, url).apply();
    }

    public synchronized String getAuthToken() {
        return authToken != null ? authToken : "";
    }

    public synchronized void setAuthToken(String token) {
        this.authToken = token != null ? token.trim() : "";
        prefs.edit().putString(KEY_AUTH_TOKEN, this.authToken).apply();
    }

    /**
     * Выполняет произвольный HTTP-запрос в пуле потоков.
     */
    public void executeRequest(final String endpoint, final String method, final JSONObject body, final ApiCallback callback) {
        executor.execute(new Runnable() {
            @Override
            public void run() {
                HttpURLConnection conn = null;
                try {
                    String base = getServerUrl();
                    if (!base.startsWith("http://") && !base.startsWith("https://")) {
                        base = "http://" + base;
                    }
                    String path = endpoint.startsWith("/") ? endpoint : "/" + endpoint;
                    URL url = new URL(base + path);
                    conn = (HttpURLConnection) url.openConnection();
                    conn.setRequestMethod(method);
                    conn.setConnectTimeout(3500);
                    conn.setReadTimeout(5000);
                    conn.setUseCaches(false);
                    conn.setRequestProperty("Accept", "application/json");
                    conn.setRequestProperty("User-Agent", "PCControl-Android/2.4.0");

                    String token = getAuthToken();
                    if (token != null && !token.isEmpty()) {
                        conn.setRequestProperty("X-Auth-Token", token);
                    }

                    if (body != null && ("POST".equalsIgnoreCase(method) || "PUT".equalsIgnoreCase(method))) {
                        conn.setDoOutput(true);
                        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
                        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                        try (OutputStream os = conn.getOutputStream()) {
                            os.write(bytes);
                            os.flush();
                        }
                    }

                    final int code = conn.getResponseCode();
                    InputStream is = (code >= 200 && code < 400) ? conn.getInputStream() : conn.getErrorStream();
                    String responseStr = "";
                    if (is != null) {
                        try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                            StringBuilder sb = new StringBuilder();
                            String line;
                            while ((line = br.readLine()) != null) {
                                sb.append(line);
                            }
                            responseStr = sb.toString();
                        }
                    }

                    if (code >= 200 && code < 400) {
                        JSONObject json;
                        try {
                            json = responseStr.isEmpty() ? new JSONObject() : new JSONObject(responseStr);
                        } catch (Exception e) {
                            json = new JSONObject();
                            json.put("raw", responseStr);
                        }
                        final JSONObject finalJson = json;
                        mainHandler.post(new Runnable() {
                            @Override
                            public void run() {
                                if (callback != null) callback.onSuccess(finalJson);
                            }
                        });
                    } else {
                        String errMsg = "HTTP " + code;
                        try {
                            JSONObject errJson = new JSONObject(responseStr);
                            if (errJson.has("message")) {
                                errMsg = errJson.getString("message");
                            }
                        } catch (Exception ignored) {}
                        final String finalErrMsg = errMsg;
                        mainHandler.post(new Runnable() {
                            @Override
                            public void run() {
                                if (callback != null) callback.onError(finalErrMsg, code);
                            }
                        });
                    }

                } catch (final Exception e) {
                    mainHandler.post(new Runnable() {
                        @Override
                        public void run() {
                            if (callback != null) callback.onError(e.getMessage() != null ? e.getMessage() : "Сбой сетевого подключения", -1);
                        }
                    });
                } finally {
                    if (conn != null) {
                        conn.disconnect();
                    }
                }
            }
        });
    }

    /**
     * Проверка статуса сервера и соединения.
     */
    public void checkStatus(final ApiCallback callback) {
        executeRequest("/status", "GET", null, callback);
    }

    /**
     * Управление питанием (shutdown, reboot, sleep, lock).
     */
    public void powerAction(String action, ApiCallback callback) {
        try {
            JSONObject body = new JSONObject();
            body.put("action", action);
            executeRequest("/action", "POST", body, callback);
        } catch (Exception e) {
            if (callback != null) callback.onError(e.getMessage(), -1);
        }
    }

    /**
     * Управление медиаплеером (play_pause, next, prev, stop).
     */
    public void mediaControl(String command, ApiCallback callback) {
        try {
            JSONObject body = new JSONObject();
            body.put("action", command);
            executeRequest("/media/control", "POST", body, callback);
        } catch (Exception e) {
            if (callback != null) callback.onError(e.getMessage(), -1);
        }
    }

    /**
     * Получение текущей громкости системы.
     */
    public void getVolume(ApiCallback callback) {
        executeRequest("/volume", "GET", null, callback);
    }

    /**
     * Установка громкости Windows (0..100).
     */
    public void setVolume(int level, ApiCallback callback) {
        try {
            JSONObject body = new JSONObject();
            body.put("level", Math.max(0, Math.min(100, level)));
            executeRequest("/volume", "POST", body, callback);
        } catch (Exception e) {
            if (callback != null) callback.onError(e.getMessage(), -1);
        }
    }

    /**
     * Переключение беззвучного режима (Mute).
     */
    public void toggleMute(ApiCallback callback) {
        executeRequest("/mute", "POST", new JSONObject(), callback);
    }

    /**
     * Отправка сочетания клавиш (hotkey).
     */
    public void keyboardHotkey(String[] keys, ApiCallback callback) {
        try {
            JSONObject body = new JSONObject();
            body.put("action", "hotkey");
            JSONArray arr = new JSONArray();
            for (String k : keys) arr.put(k);
            body.put("keys", arr);
            executeRequest("/api/keyboard", "POST", body, callback);
        } catch (Exception e) {
            if (callback != null) callback.onError(e.getMessage(), -1);
        }
    }

    /**
     * Отправка произвольного текста на ПК.
     */
    public void keyboardText(String text, ApiCallback callback) {
        try {
            JSONObject body = new JSONObject();
            body.put("action", "text");
            body.put("text", text);
            executeRequest("/api/keyboard", "POST", body, callback);
        } catch (Exception e) {
            if (callback != null) callback.onError(e.getMessage(), -1);
        }
    }

    /**
     * Быстрое автообнаружение ПК в локальной сети (LAN Auto-Discovery).
     */
    public void discoverServer(final DiscoveryCallback callback) {
        executor.execute(new Runnable() {
            @Override
            public void run() {
                // 1. Пробуем текущий сохранённый URL
                final String current = getServerUrl();
                if (pingUrl(current)) {
                    mainHandler.post(new Runnable() {
                        @Override
                        public void run() {
                            if (callback != null) callback.onDiscovered(current);
                        }
                    });
                    return;
                }

                // 2. Получаем IP адрес устройства в Wi-Fi сети
                String deviceIp = getLocalWifiIpAddress();
                if (deviceIp != null && deviceIp.contains(".")) {
                    String prefix = deviceIp.substring(0, deviceIp.lastIndexOf('.') + 1);
                    // Проверяем наиболее частые адреса роутеров и хостов в подсети
                    int[] quickCandidates = new int[]{101, 100, 102, 105, 110, 150, 200, 1, 2, 3};
                    for (int lastByte : quickCandidates) {
                        final String testUrl = "http://" + prefix + lastByte + ":5000";
                        if (pingUrl(testUrl)) {
                            setServerUrl(testUrl);
                            mainHandler.post(new Runnable() {
                                @Override
                                public void run() {
                                    if (callback != null) callback.onDiscovered(testUrl);
                                }
                            });
                            return;
                        }
                    }
                }

                mainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (callback != null) callback.onNotFound();
                    }
                });
            }
        });
    }

    private boolean pingUrl(String rawUrl) {
        if (rawUrl == null || rawUrl.trim().isEmpty()) return false;
        HttpURLConnection conn = null;
        try {
            URL u = new URL(rawUrl.endsWith("/") ? rawUrl + "status" : rawUrl + "/status");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(800);
            conn.setReadTimeout(1200);
            conn.setRequestMethod("GET");
            int code = conn.getResponseCode();
            return code == 200;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private String getLocalWifiIpAddress() {
        try {
            WifiManager wm = (WifiManager) context.getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                WifiInfo wi = wm.getConnectionInfo();
                int ipInt = wi.getIpAddress();
                if (ipInt != 0) {
                    return String.format("%d.%d.%d.%d",
                            (ipInt & 0xff),
                            (ipInt >> 8 & 0xff),
                            (ipInt >> 16 & 0xff),
                            (ipInt >> 24 & 0xff));
                }
            }
        } catch (Exception ignored) {}
        return null;
    }
}
