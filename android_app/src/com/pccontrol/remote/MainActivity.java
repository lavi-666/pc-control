package com.pccontrol.remote;

import android.app.Activity;
import android.content.Context;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.net.Uri;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class MainActivity extends Activity {
    private static MainActivity instance;
    private FrameLayout rootLayout;
    private WebView webView;
    private NativeScreenView nativeScreenView;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;

    public static MainActivity getInstance() {
        return instance;
    }

    public boolean checkOrRequestRecordAudioPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, 102);
                return false;
            }
        }
        return true;
    }

    public static void notifyBackgroundStateChanged(final boolean active) {
        if (instance != null && instance.webView != null) {
            instance.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    instance.webView.evaluateJavascript(
                        "if (typeof onBackgroundModeStateChanged === 'function') { onBackgroundModeStateChanged(" + active + "); }",
                        null
                    );
                }
            });
        }
    }

    public class AndroidBridge {
        // Send Wake-on-LAN Magic Packet: 6 x 0xFF + 16 x MAC (102 bytes) via UDP to ports 9 and 7.
        // Automatically finds Wi-Fi broadcast addresses and holds MulticastLock to protect against Android packet drops.
        @JavascriptInterface
        public String sendWakeOnLan(final String mac, final String targetsCsv) {
            final byte[] macBytes;
            try {
                String hex = mac.replaceAll("[^0-9A-Fa-f]", "");
                if (hex.length() != 12) {
                    return "error:bad_mac";
                }
                macBytes = new byte[6];
                for (int i = 0; i < 6; i++) {
                    macBytes[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
                }
            } catch (Exception e) {
                return "error:bad_mac";
            }

            final byte[] packet = new byte[6 + 16 * 6];
            for (int i = 0; i < 6; i++) {
                packet[i] = (byte) 0xFF;
            }
            for (int i = 6; i < packet.length; i += 6) {
                System.arraycopy(macBytes, 0, packet, i, 6);
            }

            final Set<String> targetSet = new HashSet<>();
            if (targetsCsv != null && !targetsCsv.trim().isEmpty()) {
                for (String t : targetsCsv.split(",")) {
                    String h = t.trim();
                    if (!h.isEmpty()) targetSet.add(h);
                }
            }
            targetSet.add("255.255.255.255");
            targetSet.add("192.168.0.255");
            targetSet.add("192.168.1.255");

            // Dynamically query device network interfaces to discover current Wi-Fi broadcast address
            try {
                Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
                while (interfaces != null && interfaces.hasMoreElements()) {
                    NetworkInterface ni = interfaces.nextElement();
                    if (!ni.isUp() || ni.isLoopback()) continue;
                    for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                        InetAddress bcast = ia.getBroadcast();
                        if (bcast != null && bcast.getHostAddress() != null) {
                            targetSet.add(bcast.getHostAddress());
                        }
                    }
                }
            } catch (Exception ignored) {}

            final List<String> targets = new ArrayList<>(targetSet);
            final int[] ports = new int[]{9, 7};
            final int[] sentCount = new int[]{0};

            Thread t = new Thread(new Runnable() {
                @Override
                public void run() {
                    DatagramSocket socket = null;
                    WifiManager.MulticastLock mLock = null;
                    try {
                        try {
                            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                            if (wm != null) {
                                mLock = wm.createMulticastLock("wol_lock");
                                mLock.setReferenceCounted(false);
                                mLock.acquire();
                            }
                        } catch (Exception ignored) {}

                        socket = new DatagramSocket();
                        socket.setBroadcast(true);

                        for (int attempt = 0; attempt < 3; attempt++) {
                            for (String host : targets) {
                                try {
                                    InetAddress addr = InetAddress.getByName(host);
                                    for (int port : ports) {
                                        socket.send(new DatagramPacket(packet, packet.length, addr, port));
                                        sentCount[0]++;
                                    }
                                } catch (Exception ignored) {}
                            }
                            try { Thread.sleep(100); } catch (InterruptedException ignored) {}
                        }
                    } catch (Exception ignored) {
                    } finally {
                        if (socket != null) {
                            try { socket.close(); } catch (Exception ignored) {}
                        }
                        if (mLock != null && mLock.isHeld()) {
                            try { mLock.release(); } catch (Exception ignored) {}
                        }
                    }
                }
            });
            t.start();
            try {
                t.join(3500);
            } catch (InterruptedException ignored) {}
            return sentCount[0] > 0 ? ("ok:" + sentCount[0]) : "error:send_failed";
        }

        @JavascriptInterface
        public void saveBase64File(String b64Data, String fileName) {
            try {
                final String safeFileName = (fileName != null && !fileName.trim().isEmpty())
                        ? new File(fileName).getName()
                        : ("screenshot_" + System.currentTimeMillis() + ".png");
                byte[] bytes = Base64.decode(b64Data, Base64.DEFAULT);
                File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (dir != null && !dir.exists()) {
                    dir.mkdirs();
                }
                File outFile = new File(dir, safeFileName);
                try (FileOutputStream fos = new FileOutputStream(outFile)) {
                    fos.write(bytes);
                    fos.flush();
                }
                final String savedPath = outFile.getAbsolutePath();
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "Saved to Downloads: " + safeFileName, Toast.LENGTH_SHORT).show();
                    }
                });
            } catch (final Exception e) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "Save error: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                    }
                });
            }
        }

        @JavascriptInterface
        public boolean isBackgroundMode() {
            return BackgroundAudioService.isRunning;
        }

        @JavascriptInterface
        public void setBackgroundMode(final boolean enable) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        if (enable) {
                            if (Build.VERSION.SDK_INT >= 33) {
                                if (checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
                                }
                            }
                            android.content.Intent intent = new android.content.Intent(MainActivity.this, BackgroundAudioService.class);
                            intent.setAction(BackgroundAudioService.ACTION_START);
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                                startForegroundService(intent);
                            } else {
                                startService(intent);
                            }
                        } else {
                            android.content.Intent intent = new android.content.Intent(MainActivity.this, BackgroundAudioService.class);
                            intent.setAction(BackgroundAudioService.ACTION_STOP);
                            startService(intent);
                        }
                    } catch (Exception e) {
                        Toast.makeText(MainActivity.this, "Background mode error: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                    }
                }
            });
        }

        @JavascriptInterface
        public void toggleBackgroundMode() {
            setBackgroundMode(!BackgroundAudioService.isRunning);
        }

        @JavascriptInterface
        public boolean isNativeScreenSupported() {
            return true;
        }

        @JavascriptInterface
        public void startNativeScreen(final String serverUrl, final String token, final int monitor, final int height, final int fps, final int bitrate, final String quality, final String codec) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (nativeScreenView != null) {
                        nativeScreenView.setOperatingMode(NativeScreenView.MODE_VIEW);
                        nativeScreenView.configure(serverUrl, token, monitor, height, fps, bitrate, quality, codec);
                        nativeScreenView.startStream();
                    }
                }
            });
        }

        @JavascriptInterface
        public void startNativePcControl(final String serverUrl, final String token, final int monitor, final int height, final int fps, final int bitrate, final String quality, final String codec) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (nativeScreenView != null) {
                        nativeScreenView.setOperatingMode(NativeScreenView.MODE_PC_CONTROL);
                        nativeScreenView.configure(serverUrl, token, monitor, height, fps, bitrate, quality, codec);
                        nativeScreenView.startStream();
                    }
                }
            });
        }

        @JavascriptInterface
        public void stopNativeScreen() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (nativeScreenView != null) {
                        nativeScreenView.stopStream();
                        setNativeFullscreen(false);
                    }
                }
            });
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        instance = this;

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        Window win = getWindow();
        win.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            win.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            win.setStatusBarColor(Color.parseColor("#030303"));
            win.setNavigationBarColor(Color.parseColor("#030303"));
        }

        rootLayout = new FrameLayout(this);
        rootLayout.setBackgroundColor(Color.parseColor("#030303"));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#030303"));

        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        // Защита: отключаем небезопасный доступ к локальным файлам через file:// и универсальный кросс-доменный доступ
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(true);
        ws.setAllowFileAccessFromFileURLs(false);
        ws.setAllowUniversalAccessFromFileURLs(false);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }

        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request != null && request.getUrl() != null) {
                    Uri uri = request.getUrl();
                    String host = uri.getHost();
                    if ("pccontrol.local".equalsIgnoreCase(host) || "127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host)) {
                        return false;
                    }
                    // Внешние ссылки открываются во внешнем системном браузере, а не внутри привилегированного WebView
                    try {
                        android.content.Intent browserIntent = new android.content.Intent(android.content.Intent.ACTION_VIEW, uri);
                        startActivity(browserIntent);
                    } catch (Exception ignored) {}
                    return true;
                }
                return false;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (request != null && request.getUrl() != null) {
                    WebResourceResponse resp = handleAssetRequest(request.getUrl());
                    if (resp != null) return resp;
                }
                return super.shouldInterceptRequest(view, request);
            }

            @SuppressWarnings("deprecation")
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
                if (url != null) {
                    try {
                        WebResourceResponse resp = handleAssetRequest(Uri.parse(url));
                        if (resp != null) return resp;
                    } catch (Exception ignored) {}
                }
                return super.shouldInterceptRequest(view, url);
            }

            private WebResourceResponse handleAssetRequest(Uri uri) {
                if (uri == null) return null;
                String host = uri.getHost();
                String scheme = uri.getScheme();
                if (host == null || "pccontrol.local".equalsIgnoreCase(host) || "file".equalsIgnoreCase(scheme)) {
                    String path = uri.getPath();
                    if (path != null) {
                        while (path.startsWith("/")) {
                            path = path.substring(1);
                        }
                        if (!path.isEmpty()) {
                            try {
                                InputStream is = getAssets().open(path);
                                String mime = "application/octet-stream";
                                String encoding = null;
                                if (path.endsWith(".png")) {
                                    mime = "image/png";
                                } else if (path.endsWith(".jpg") || path.endsWith(".jpeg")) {
                                    mime = "image/jpeg";
                                } else if (path.endsWith(".svg")) {
                                    mime = "image/svg+xml";
                                    encoding = "UTF-8";
                                } else if (path.endsWith(".ico")) {
                                    mime = "image/x-icon";
                                } else if (path.endsWith(".html")) {
                                    mime = "text/html";
                                    encoding = "UTF-8";
                                } else if (path.endsWith(".css")) {
                                    mime = "text/css";
                                    encoding = "UTF-8";
                                } else if (path.endsWith(".js")) {
                                    mime = "application/javascript";
                                    encoding = "UTF-8";
                                }
                                return new WebResourceResponse(mime, encoding, is);
                            } catch (Exception ignored) {}
                        }
                    }
                }
                return null;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (request == null) return;
                        Uri origin = request.getOrigin();
                        if (origin == null) {
                            request.deny();
                            return;
                        }
                        String host = origin.getHost();
                        // Разрешаем только доверенные локальные источники
                        boolean isTrustedOrigin = "pccontrol.local".equalsIgnoreCase(host)
                                || "127.0.0.1".equals(host)
                                || "localhost".equalsIgnoreCase(host);

                        if (!isTrustedOrigin) {
                            request.deny();
                            return;
                        }

                        // Проверяем типы ресурсов: разрешаем только аудио захват для WebRTC аудио, камеру и остальное отклоняем
                        List<String> allowed = new ArrayList<>();
                        for (String r : request.getResources()) {
                            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) {
                                allowed.add(r);
                            }
                        }
                        if (!allowed.isEmpty()) {
                            request.grant(allowed.toArray(new String[0]));
                        } else {
                            request.deny();
                        }
                    }
                });
            }

            @Override
            public void onShowCustomView(View view, CustomViewCallback callback) {
                if (customView != null) {
                    callback.onCustomViewHidden();
                    return;
                }
                customView = view;
                customViewCallback = callback;
                try {
                    setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
                } catch (Exception ignored) {}
                webView.setVisibility(View.GONE);
                rootLayout.addView(customView, new FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                ));
                getWindow().getDecorView().setSystemUiVisibility(
                        View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                );
            }

            @Override
            public void onHideCustomView() {
                if (customView == null) {
                    return;
                }
                try {
                    setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
                } catch (Exception ignored) {}
                rootLayout.removeView(customView);
                customView = null;
                if (customViewCallback != null) {
                    customViewCallback.onCustomViewHidden();
                    customViewCallback = null;
                }
                webView.setVisibility(View.VISIBLE);
                getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
            }
        });

        rootLayout.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        nativeScreenView = new NativeScreenView(this);
        nativeScreenView.setVisibility(View.GONE);
        nativeScreenView.setPlayerCallback(new NativeScreenView.PlayerCallback() {
            @Override
            public void onCloseRequested() {
                setNativeFullscreen(false);
                if (webView != null) {
                    webView.evaluateJavascript("if (typeof onNativeScreenClosed === 'function') { onNativeScreenClosed(); }", null);
                }
            }

            @Override
            public void onFullscreenToggled(boolean isFullscreen) {
                setNativeFullscreen(isFullscreen);
            }

            @Override
            public void onSettingsChanged(final int monitor, final int height, final int fps, final int bitrate) {
                if (webView != null) {
                    webView.evaluateJavascript("if (typeof onNativeScreenParamsUpdated === 'function') { onNativeScreenParamsUpdated(" + monitor + "," + height + "," + fps + "," + bitrate + "); }", null);
                }
            }
        });
        rootLayout.addView(nativeScreenView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        setContentView(rootLayout);

        String html = loadAssetHtml("index.html");
        webView.loadDataWithBaseURL(buildBaseUrl(getIntent()), html, "text/html", "UTF-8", null);
    }

    @Override
    protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (webView != null && intent != null && intent.getData() != null) {
            String html = loadAssetHtml("index.html");
            webView.loadDataWithBaseURL(buildBaseUrl(intent), html, "text/html", "UTF-8", null);
        }
    }

    private String buildBaseUrl(android.content.Intent intent) {
        if (intent != null && intent.getData() != null) {
            Uri uri = intent.getData();
            String query = uri.getEncodedQuery();
            if (query != null && !query.isEmpty()) {
                return "http://pccontrol.local/?" + query;
            }
        }
        return "http://pccontrol.local/";
    }

    private String loadAssetHtml(String name) {
        try (InputStream is = getAssets().open(name);
             ByteArrayOutputStream bos = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int r;
            while ((r = is.read(buf)) != -1) {
                bos.write(buf, 0, r);
            }
            return new String(bos.toByteArray(), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return "<html><body style='background:#030303;color:#fff;'>Error loading UI</body></html>";
        }
    }

    public void setNativeFullscreen(final boolean fullscreen) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                Window win = getWindow();
                if (fullscreen) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        android.view.WindowInsetsController controller = win.getInsetsController();
                        if (controller != null) {
                            controller.hide(android.view.WindowInsets.Type.statusBars() | android.view.WindowInsets.Type.navigationBars());
                            controller.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                        }
                    } else {
                        win.getDecorView().setSystemUiVisibility(
                                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                                | View.SYSTEM_UI_FLAG_FULLSCREEN
                                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        );
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        WindowManager.LayoutParams lp = win.getAttributes();
                        lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
                        win.setAttributes(lp);
                    }
                    try {
                        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
                    } catch (Exception ignored) {}
                } else {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        android.view.WindowInsetsController controller = win.getInsetsController();
                        if (controller != null) {
                            controller.show(android.view.WindowInsets.Type.statusBars() | android.view.WindowInsets.Type.navigationBars());
                        }
                    } else {
                        win.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        WindowManager.LayoutParams lp = win.getAttributes();
                        lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT;
                        win.setAttributes(lp);
                    }
                    try {
                        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
                    } catch (Exception ignored) {}
                }
            }
        });
    }

    @Override
    public void onBackPressed() {
        if (nativeScreenView != null && nativeScreenView.getVisibility() == View.VISIBLE) {
            if (nativeScreenView.handleBackPressed()) {
                return;
            }
            nativeScreenView.stopStream();
            setNativeFullscreen(false);
            if (webView != null) {
                webView.evaluateJavascript("if (typeof onNativeScreenClosed === 'function') { onNativeScreenClosed(); }", null);
            }
            return;
        }
        if (customView != null) {
            webView.getWebChromeClient().onHideCustomView();
            return;
        }
        if (webView != null) {
            webView.evaluateJavascript(
                "(function(){" +
                "  var pm = document.getElementById('presetsModalBackdrop');" +
                "  if (pm && pm.classList.contains('open')) { closePresetsModal(); return 'handled'; }" +
                "  var sm = document.getElementById('settingsModalBackdrop');" +
                "  if (sm && sm.classList.contains('open')) { closeSettingsModal(); return 'handled'; }" +
                "  var cm = document.getElementById('connModalBackdrop');" +
                "  if (cm && cm.classList.contains('open')) { toggleConnModal(false); return 'handled'; }" +
                "  var st = document.getElementById('screenStage');" +
                "  if (st && st.classList.contains('pseudo-fs')) { st.classList.remove('pseudo-fs'); return 'handled'; }" +
                "  var qp = document.getElementById('queuePanel');" +
                "  if (qp && qp.classList.contains('open')) { toggleQueuePanel(); return 'handled'; }" +
                "  var pb = document.getElementById('processesBox');" +
                "  if (pb && pb.style.display === 'block') { pb.style.display = 'none'; return 'handled'; }" +
                "  var hb = document.getElementById('historyBox');" +
                "  if (hb && hb.style.display === 'block') { hb.style.display = 'none'; return 'handled'; }" +
                "  var mm = document.getElementById('modeMenu');" +
                "  if (mm && mm.classList.contains('open')) { closeModeMenu(); return 'handled'; }" +
                "  var lm = document.getElementById('langMenu');" +
                "  if (lm && lm.classList.contains('open')) { closeLangMenu(); return 'handled'; }" +
                "  var ab = document.getElementById('appVolumesBox');" +
                "  if (ab && ab.style.display === 'block') { ab.style.display = 'none'; return 'handled'; }" +
                "  return 'exit';" +
                "})()",
                new android.webkit.ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (value == null || !value.contains("handled")) {
                            MainActivity.super.onBackPressed();
                        }
                    }
                }
            );
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) {
            webView.evaluateJavascript("window.__hostAppActive = false;", null);
            if (!BackgroundAudioService.isRunning) {
                webView.onPause();
            }
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
            webView.evaluateJavascript("window.__hostAppActive = true; if (typeof adaptivePollTick === 'function') adaptivePollTick();", null);
        }
        notifyBackgroundStateChanged(BackgroundAudioService.isRunning);
    }

    @Override
    protected void onDestroy() {
        if (nativeScreenView != null) {
            nativeScreenView.stopStream();
            setNativeFullscreen(false);
        }
        instance = null;
        super.onDestroy();
    }
}
