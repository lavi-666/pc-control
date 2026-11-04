"""
PC Control - Standalone Android App Builder (PC_Control.apk).
Uses portable Android SDK (aapt2, d8, zipalign, apksigner) and OpenJDK 17
from .android_sdk directory to build a signed APK with embedded web interface.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent.parent
SDK_DIR = BASE_DIR / ".android_sdk"
APP_DIR = BASE_DIR / "android_app"
OUT_APK = BASE_DIR / "PC_Control.apk"


def _find_first(pattern: str) -> Path:
    matches = list(SDK_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"Tool not found matching pattern: {pattern}")
    return matches[0].resolve()


def generate_app_icons(res_dir: Path):
    """Generates official PC Control app icons with stylish PC logo."""
    sizes = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    master_logo = BASE_DIR / "web" / "logo.png"
    if not master_logo.exists():
        master_logo = BASE_DIR / "android_app" / "res" / "logo_master.png"

    src_img = None
    if master_logo.exists():
        try:
            src_img = Image.open(master_logo).convert("RGBA")
        except Exception:
            src_img = None

    for folder, sz in sizes.items():
        d = res_dir / folder
        d.mkdir(parents=True, exist_ok=True)
        if src_img:
            # Scale master logo using Lanczos resampling
            out_img = src_img.resize((sz, sz), Image.Resampling.LANCZOS)
            out_img.save(d / "ic_launcher.png", format="PNG")

            # Round launcher icon with smoothed edges for Android launchers
            scale = 4
            mask = Image.new("L", (sz * scale, sz * scale), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, sz * scale - 1, sz * scale - 1], fill=255)
            mask = mask.resize((sz, sz), Image.Resampling.LANCZOS)

            round_img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
            round_img.paste(out_img, (0, 0), mask)
            round_img.save(d / "ic_launcher_round.png", format="PNG")
        else:
            # Fallback PC logo drawing if file not found
            scale = 4
            big = sz * scale
            img = Image.new("RGBA", (big, big), (0, 0, 0, 255))
            out_img = img.resize((sz, sz), Image.Resampling.LANCZOS)
            out_img.save(d / "ic_launcher.png", format="PNG")
            out_img.save(d / "ic_launcher_round.png", format="PNG")


JAVA_BACKGROUND_SERVICE = r"""package com.pccontrol.remote;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

public class BackgroundAudioService extends Service {
    public static final String CHANNEL_ID = "pc_control_bg_channel";
    public static final int NOTIFICATION_ID = 2026;
    public static final String ACTION_START = "com.pccontrol.remote.START_BACKGROUND";
    public static final String ACTION_STOP = "com.pccontrol.remote.STOP_BACKGROUND";

    public static volatile boolean isRunning = false;

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopBackground();
            return START_NOT_STICKY;
        }

        startBackground();
        return START_STICKY;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "PC Remote Background Audio",
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Keeps PC audio streaming active while screen is off");
            channel.setShowBadge(false);
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
    }

    private void startBackground() {
        if (isRunning) return;
        isRunning = true;

        Intent tapIntent = new Intent(this, MainActivity.class);
        tapIntent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int pFlags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
            ? (PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)
            : PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent pTapIntent = PendingIntent.getActivity(this, 0, tapIntent, pFlags);

        Intent stopIntent = new Intent(this, BackgroundAudioService.class);
        stopIntent.setAction(ACTION_STOP);
        PendingIntent pStopIntent = PendingIntent.getService(this, 1, stopIntent, pFlags);

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }

        builder.setContentTitle("PC Remote Control · Background mode")
               .setContentText("PC audio streaming continues with screen off")
               .setSmallIcon(R.mipmap.ic_launcher)
               .setContentIntent(pTapIntent)
               .setOngoing(true)
               .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Disconnect", pStopIntent);

        Notification notif = builder.build();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(NOTIFICATION_ID, notif);
        }

        try {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null && wakeLock == null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PCRemoteControl::BgWakeLock");
                wakeLock.setReferenceCounted(false);
                wakeLock.acquire();
            }
        } catch (Exception ignored) {}

        try {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wm != null && wifiLock == null) {
                int mode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                    : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
                wifiLock = wm.createWifiLock(mode, "PCRemoteControl::BgWifiLock");
                wifiLock.setReferenceCounted(false);
                wifiLock.acquire();
            }
        } catch (Exception ignored) {}

        MainActivity.notifyBackgroundStateChanged(true);
    }

    private void stopBackground() {
        isRunning = false;

        if (wakeLock != null && wakeLock.isHeld()) {
            try { wakeLock.release(); } catch (Exception ignored) {}
            wakeLock = null;
        }

        if (wifiLock != null && wifiLock.isHeld()) {
            try { wifiLock.release(); } catch (Exception ignored) {}
            wifiLock = null;
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                stopForeground(STOP_FOREGROUND_REMOVE);
            } else {
                stopForeground(true);
            }
        } catch (Exception ignored) {}

        stopSelf();
        MainActivity.notifyBackgroundStateChanged(false);
    }

    @Override
    public void onDestroy() {
        stopBackground();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
"""

JAVA_MAIN_ACTIVITY = r"""package com.pccontrol.remote;

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
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;

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
        ws.setAllowFileAccess(true);
        ws.setAllowContentAccess(true);
        ws.setAllowFileAccessFromFileURLs(true);
        ws.setAllowUniversalAccessFromFileURLs(true);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
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
                        request.grant(request.getResources());
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
        setContentView(rootLayout);

        String html = loadAssetHtml("index.html");
        webView.loadDataWithBaseURL("http://pccontrol.local/", html, "text/html", "UTF-8", null);
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

    @Override
    public void onBackPressed() {
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
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
        notifyBackgroundStateChanged(BackgroundAudioService.isRunning);
    }

    @Override
    protected void onDestroy() {
        instance = null;
        super.onDestroy();
    }
}
"""

ANDROID_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.pccontrol.remote"
    android:versionCode="5"
    android:versionName="2.3">

    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="29" />

    <application
        android:label="PC Control"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:usesCleartextTraffic="true"
        android:hardwareAccelerated="true"
        android:allowBackup="true"
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:label="PC Control"
            android:exported="true"
            android:launchMode="singleTop"
            android:configChanges="orientation|screenSize|keyboardHidden|smallestScreenSize|screenLayout">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".BackgroundAudioService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="mediaPlayback" />
    </application>
</manifest>
"""


def build():
    web_file = BASE_DIR / "web" / "index.html"
    if web_file.exists():
        raw_html = web_file.read_text(encoding="utf-8")
    else:
        try:
            import server
            raw_html = getattr(server, "PAGE", "")
        except Exception:
            raw_html = ""

    aapt2 = _find_first("build-tools/**/aapt2.exe")
    zipalign = _find_first("build-tools/**/zipalign.exe")
    d8_jar = _find_first("build-tools/**/lib/d8.jar")
    apksigner_jar = _find_first("build-tools/**/lib/apksigner.jar")
    android_jar = _find_first("platform/**/android.jar")
    javac = _find_first("jdk/**/bin/javac.exe")
    java = _find_first("jdk/**/bin/java.exe")
    keytool = _find_first("jdk/**/bin/keytool.exe")

    # android_app contains tracked Java sources. Clean generated output only;
    # never erase user changes to the application when rebuilding from the UI.
    for name in ("classes", "compiled_res", "assets"):
        generated = APP_DIR / name
        if generated.is_dir():
            if generated.resolve().parent != APP_DIR.resolve():
                raise ValueError(f"Build output escapes application directory: {generated}")
            shutil.rmtree(generated)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    res_dir = APP_DIR / "res"
    assets_dir = APP_DIR / "assets"
    src_dir = APP_DIR / "src" / "com" / "pccontrol" / "remote"
    classes_dir = APP_DIR / "classes"
    compiled_res_dir = APP_DIR / "compiled_res"

    for d in (res_dir, assets_dir, src_dir, classes_dir, compiled_res_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Icons and manifest
    generate_app_icons(res_dir)
    manifest_path = APP_DIR / "AndroidManifest.xml"
    if not manifest_path.exists():
        manifest_path.write_text(ANDROID_MANIFEST, encoding="utf-8")

    # 2. Embed up-to-date web interface from web/index.html into assets/index.html
    # В целях безопасности токен НИКОГДА не зашивается в бинарный APK.
    is_clean_build = "--clean" in sys.argv
    cfg_file = BASE_DIR / "config.json"
    if cfg_file.exists() and not is_clean_build:
        try:
            import json as _json
            import re as _re
            cfg = _json.loads(cfg_file.read_text(encoding="utf-8"))
            port = cfg.get("port", 5000)
            relay_port = cfg.get("relay_port", 5050)
            raw_html = _re.sub(
                r"const\s+DEFAULT_APP_TOKEN\s*=\s*['\"][^'\"]*['\"];",
                "const DEFAULT_APP_TOKEN = '';",
                raw_html,
                count=1,
            )
            if cfg.get("lan_ip"):
                lan_url = "http://{}:{}".format(cfg["lan_ip"], port)
                raw_html = _re.sub(
                    r"const\s+DEFAULT_LAN_HOST\s*=\s*['\"][^'\"]*['\"];",
                    "const DEFAULT_LAN_HOST = {};".format(_json.dumps(lan_url)),
                    raw_html,
                    count=1,
                )
            if cfg.get("vpn_ip"):
                vpn_url = "http://{}:{}".format(cfg["vpn_ip"], port)
                raw_html = _re.sub(
                    r"const\s+DEFAULT_VPN_HOST\s*=\s*['\"][^'\"]*['\"];",
                    "const DEFAULT_VPN_HOST = {};".format(_json.dumps(vpn_url)),
                    raw_html,
                    count=1,
                )
            if cfg.get("wol_relay_ip"):
                relay_url = "http://{}:{}".format(cfg["wol_relay_ip"], relay_port)
                raw_html = _re.sub(
                    r"const\s+DEFAULT_WOL_RELAY\s*=\s*['\"][^'\"]*['\"];",
                    "const DEFAULT_WOL_RELAY = {};".format(_json.dumps(relay_url)),
                    raw_html,
                    count=1,
                )
            if cfg.get("mac_address"):
                raw_html = _re.sub(
                    r"const\s+PC_MAC_ADDRESS\s*=\s*['\"][^'\"]*['\"];",
                    f"const PC_MAC_ADDRESS = {_json.dumps(str(cfg['mac_address']).strip())};",
                    raw_html,
                    count=1,
                )
        except Exception:
            pass

    html_page = raw_html.replace(
        "<head>",
        "<head>\n<script>window.IS_STANDALONE_APK = true;</script>",
        1,
    )
    (assets_dir / "index.html").write_text(html_page, encoding="utf-8")
    logo_file = BASE_DIR / "web" / "logo.png"
    if logo_file.exists():
        shutil.copy(logo_file, assets_dir / "logo.png")
    web_css = BASE_DIR / "web" / "css"
    if web_css.exists():
        shutil.copytree(web_css, assets_dir / "css", dirs_exist_ok=True)
    web_js = BASE_DIR / "web" / "js"
    if web_js.exists():
        shutil.copytree(web_js, assets_dir / "js", dirs_exist_ok=True)

    # 3. Write Java source files
    for filename, template in (("BackgroundAudioService.java", JAVA_BACKGROUND_SERVICE),
                               ("MainActivity.java", JAVA_MAIN_ACTIVITY)):
        source = src_dir / filename
        if not source.exists():
            source.write_text(template, encoding="utf-8")

    # 4. Compile resources via aapt2
    compiled_flata = APP_DIR / "compiled_res.zip"
    subprocess.run(
        [str(aapt2), "compile", "--dir", str(res_dir), "-o", str(compiled_flata)],
        check=True,
    )

    # 5. Link resources, manifest and assets into unsigned.apk + generate R.java
    unsigned_apk = APP_DIR / "unsigned.apk"
    subprocess.run(
        [
            str(aapt2), "link",
            "-I", str(android_jar),
            "--manifest", str(manifest_path),
            "-A", str(assets_dir),
            "--java", str(APP_DIR / "src"),
            "-o", str(unsigned_apk),
            str(compiled_flata),
        ],
        check=True,
    )

    # 6. Compile Java code into .class files (Java 8 compatibility for d8)
    java_sources = [str(p) for p in (APP_DIR / "src").rglob("*.java")]
    subprocess.run(
        [
            str(javac),
            "-source", "1.8",
            "-target", "1.8",
            "-encoding", "UTF-8",
            "-cp", str(android_jar),
            "-d", str(classes_dir),
            *java_sources,
        ],
        check=True,
    )

    # 7. Build classes.dex via d8.jar
    class_files = [str(p) for p in classes_dir.rglob("*.class")]
    subprocess.run(
        [
            str(java), "-cp", str(d8_jar),
            "com.android.tools.r8.D8",
            "--lib", str(android_jar),
            "--min-api", "24",
            "--output", str(APP_DIR),
            *class_files,
        ],
        check=True,
    )

    # 8. Pack classes.dex into unsigned.apk
    dex_path = APP_DIR / "classes.dex"
    with zipfile.ZipFile(unsigned_apk, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(dex_path, arcname="classes.dex")

    # 9. Align APK via zipalign (required for Android 11-15)
    aligned_apk = APP_DIR / "aligned.apk"
    subprocess.run(
        [str(zipalign), "-f", "-p", "4", str(unsigned_apk), str(aligned_apk)],
        check=True,
    )

    # 10. Generate signing key (if missing) and sign APK (v1 + v2 + v3)
    keystore = BASE_DIR / ".android_sdk" / "pccontrol_release.jks"
    if not keystore.exists():
        subprocess.run(
            [
                str(keytool), "-genkeypair",
                "-v",
                "-keystore", str(keystore),
                "-alias", "pccontrol",
                "-keyalg", "RSA",
                "-keysize", "2048",
                "-validity", "10000",
                "-storepass", "pccontrol123",
                "-keypass", "pccontrol123",
                "-dname", "CN=PC Control, OU=Remote, O=PCControl, L=City, S=State, C=US",
            ],
            check=True,
        )

    subprocess.run(
        [
            str(java), "-jar", str(apksigner_jar),
            "sign",
            "--ks", str(keystore),
            "--ks-key-alias", "pccontrol",
            "--ks-pass", "pass:pccontrol123",
            "--key-pass", "pass:pccontrol123",
            "--v1-signing-enabled", "true",
            "--v2-signing-enabled", "true",
            "--v3-signing-enabled", "true",
            "--out", str(OUT_APK),
            str(aligned_apk),
        ],
        check=True,
    )

    # 11. Verify signature of the resulting APK
    verify_res = subprocess.run(
        [str(java), "-jar", str(apksigner_jar), "verify", "--verbose", str(OUT_APK)],
        capture_output=True,
        text=True,
        check=True,
    )
    print("APK successfully built and signed:", OUT_APK, f"({OUT_APK.stat().st_size // 1024} KB)")
    for line in verify_res.stdout.splitlines()[:6]:
        print(" ", line)


if __name__ == "__main__":
    build()
