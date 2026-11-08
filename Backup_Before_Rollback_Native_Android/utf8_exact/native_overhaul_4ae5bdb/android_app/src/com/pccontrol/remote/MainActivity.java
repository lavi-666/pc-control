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
    private NativeDashboardView nativeDashboardView;
    private NativeScreenView nativeScreenView;
    private WebView webView;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private ApiClient apiClient;

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
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "Скриншот сохранён: " + safeFileName, Toast.LENGTH_SHORT).show();
                    }
                });
            } catch (final Exception e) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "Ошибка сохранения: " + e.getMessage(), Toast.LENGTH_SHORT).show();
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
                        Toast.makeText(MainActivity.this, "Фоновый режим: " + e.getMessage(), Toast.LENGTH_SHORT).show();
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
                    startNativeStreamingInternal(serverUrl, token, monitor, height, fps, bitrate, quality, codec, NativeScreenView.MODE_VIEW);
                }
            });
        }

        @JavascriptInterface
        public void startNativePcControl(final String serverUrl, final String token, final int monitor, final int height, final int fps, final int bitrate, final String quality, final String codec) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    startNativeStreamingInternal(serverUrl, token, monitor, height, fps, bitrate, quality, codec, NativeScreenView.MODE_PC_CONTROL);
                }
            });
        }

        @JavascriptInterface
        public void stopNativeScreen() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    stopNativeStreamingInternal();
                }
            });
        }
    }

    private void startNativeStreamingInternal(String serverUrl, String token, int monitor, int height, int fps, int bitrate, String quality, String codec, int mode) {
        String effUrl = (serverUrl != null && !serverUrl.trim().isEmpty() && !serverUrl.contains("pccontrol.local"))
                ? serverUrl.trim() : apiClient.getServerUrl();
        String effToken = (token != null && !token.trim().isEmpty())
                ? token.trim() : apiClient.getAuthToken();

        if (nativeDashboardView != null) nativeDashboardView.setVisibility(View.GONE);
        if (webView != null) webView.setVisibility(View.GONE);

        if (nativeScreenView != null) {
            nativeScreenView.setVisibility(View.VISIBLE);
            nativeScreenView.setOperatingMode(mode);
            nativeScreenView.configure(effUrl, effToken, monitor, height, fps, bitrate, quality, codec);
            nativeScreenView.startStream();
            setNativeFullscreen(true);
        }
    }

    private void stopNativeStreamingInternal() {
        if (nativeScreenView != null) {
            nativeScreenView.stopStream();
            nativeScreenView.setVisibility(View.GONE);
        }
        setNativeFullscreen(false);
        if (nativeDashboardView != null) {
            nativeDashboardView.setVisibility(View.VISIBLE);
            nativeDashboardView.refreshStatus();
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        instance = this;
        apiClient = ApiClient.getInstance(this);

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

        // 1. Создаем нативный главный дашборд PC Control (Основной интерфейс)
        nativeDashboardView = new NativeDashboardView(this);
        nativeDashboardView.setCallback(new NativeDashboardView.DashboardCallback() {
            @Override
            public void onStartPcControlRequested() {
                startNativeStreamingInternal(null, null, 0, 1080, 60, 50, "auto", "auto", NativeScreenView.MODE_PC_CONTROL);
            }

            @Override
            public void onStartScreenRequested() {
                startNativeStreamingInternal(null, null, 0, 1080, 60, 50, "auto", "auto", NativeScreenView.MODE_VIEW);
            }

            @Override
            public void onOpenWebViewRequested() {
                if (nativeDashboardView != null) nativeDashboardView.setVisibility(View.GONE);
                if (webView != null) {
                    webView.setVisibility(View.VISIBLE);
                    String html = loadAssetHtml("index.html");
                    webView.loadDataWithBaseURL(apiClient.getServerUrl() + "/", html, "text/html", "UTF-8", null);
                }
            }
        });
        rootLayout.addView(nativeDashboardView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        // 2. Создаем нативный плеер стриминга и управления (MediaCodec + SurfaceView + Touchpad + Keyboard)
        nativeScreenView = new NativeScreenView(this);
        nativeScreenView.setVisibility(View.GONE);
        nativeScreenView.setPlayerCallback(new NativeScreenView.PlayerCallback() {
            @Override
            public void onCloseRequested() {
                stopNativeStreamingInternal();
            }

            @Override
            public void onFullscreenToggled(boolean isFullscreen) {
                setNativeFullscreen(isFullscreen);
            }

            @Override
            public void onSettingsChanged(final int monitor, final int height, final int fps, final int bitrate) {}
        });
        rootLayout.addView(nativeScreenView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        // 3. Создаем вспомогательный WebView (для глубоких настроек и веб-инструментов)
        setupAuxiliaryWebView();

        setContentView(rootLayout);

        handleIntent(getIntent());
    }

    private void setupAuxiliaryWebView() {
        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#030303"));
        webView.setVisibility(View.GONE);

        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
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
                                if (path.endsWith(".png")) mime = "image/png";
                                else if (path.endsWith(".jpg") || path.endsWith(".jpeg")) mime = "image/jpeg";
                                else if (path.endsWith(".svg")) { mime = "image/svg+xml"; encoding = "UTF-8"; }
                                else if (path.endsWith(".ico")) mime = "image/x-icon";
                                else if (path.endsWith(".html")) { mime = "text/html"; encoding = "UTF-8"; }
                                else if (path.endsWith(".css")) { mime = "text/css"; encoding = "UTF-8"; }
                                else if (path.endsWith(".js")) { mime = "application/javascript"; encoding = "UTF-8"; }
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
                        List<String> allowed = new ArrayList<>();
                        for (String r : request.getResources()) {
                            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) {
                                allowed.add(r);
                            }
                        }
                        if (!allowed.isEmpty()) request.grant(allowed.toArray(new String[0]));
                        else request.deny();
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
            }

            @Override
            public void onHideCustomView() {
                if (customView == null) return;
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
            }
        });

        rootLayout.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
    }

    private void handleIntent(android.content.Intent intent) {
        if (intent != null && intent.getData() != null) {
            Uri uri = intent.getData();
            String host = uri.getQueryParameter("host");
            String token = uri.getQueryParameter("token");
            if (host != null && !host.trim().isEmpty()) {
                apiClient.setServerUrl(host);
            }
            if (token != null && !token.trim().isEmpty()) {
                apiClient.setAuthToken(token);
            }
            if (nativeDashboardView != null) {
                nativeDashboardView.refreshStatus();
            }
        }
    }

    @Override
    protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
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
            stopNativeStreamingInternal();
            return;
        }
        if (webView != null && webView.getVisibility() == View.VISIBLE) {
            webView.setVisibility(View.GONE);
            if (nativeDashboardView != null) {
                nativeDashboardView.setVisibility(View.VISIBLE);
                nativeDashboardView.refreshStatus();
            }
            return;
        }
        if (customView != null && webView != null) {
            webView.getWebChromeClient().onHideCustomView();
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
        if (nativeDashboardView != null && nativeDashboardView.getVisibility() == View.VISIBLE) {
            nativeDashboardView.refreshStatus();
        }
        if (webView != null && webView.getVisibility() == View.VISIBLE) {
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
