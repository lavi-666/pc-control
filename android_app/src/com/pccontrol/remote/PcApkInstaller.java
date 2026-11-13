package com.pccontrol.remote;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Установка скачанного PC_Control.apk через PackageInstaller (сессия, без FileProvider).
 * Итог установки приходит в {@link Receiver} (объявлен в манифесте, exported=false) и
 * передаётся в MainActivity → PcSettings.
 */
public final class PcApkInstaller {
    private PcApkInstaller() {}

    static final String ACTION_STATUS = "com.pccontrol.remote.APK_INSTALL_STATUS";

    /** API 26+: разрешено ли приложению устанавливать APK («Установка неизвестных приложений»). */
    static boolean canInstall(Context c) {
        return Build.VERSION.SDK_INT < 26 || c.getPackageManager().canRequestPackageInstalls();
    }

    /** Открывает системный экран разрешения для нашего пакета. */
    static boolean requestPermission(Activity a) {
        if (Build.VERSION.SDK_INT < 26) return false;
        try {
            a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.getPackageName())));
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** Блокирующая запись APK в сессию и commit — вызывать из рабочего потока. Бросает исключение при ошибке. */
    static void install(Context c, File apk) throws Exception {
        PackageInstaller pi = c.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(c.getPackageName());
        params.setSize(apk.length());
        int id = pi.createSession(params);
        PackageInstaller.Session s = pi.openSession(id);
        try {
            try (InputStream in = new FileInputStream(apk); OutputStream out = s.openWrite("PC_Control.apk", 0, apk.length())) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                s.fsync(out);
            }
            Intent cb = new Intent(ACTION_STATUS).setPackage(c.getPackageName()).setClass(c, Receiver.class);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            // API 31+: PackageInstaller дописывает в intent EXTRA_STATUS — PendingIntent обязан быть изменяемым
            if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
            PendingIntent pend = PendingIntent.getBroadcast(c, id, cb, flags);
            s.commit(pend.getIntentSender());
        } catch (Exception e) {
            s.abandon();
            throw e;
        } finally {
            s.close();
        }
    }

    /** Статус сессии PackageInstaller (в т.ч. STATUS_PENDING_USER_ACTION — показать системный запрос). */
    public static final class Receiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null || !ACTION_STATUS.equals(intent.getAction())) return;
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            MainActivity act = MainActivity.getInstance();
            if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                if (confirm == null) {
                    if (act != null) act.onApkInstallStatus(PackageInstaller.STATUS_FAILURE, msg);
                    return;
                }
                try {
                    if (act != null) {
                        act.startActivity(confirm);
                    } else {
                        confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        context.startActivity(confirm);
                    }
                    if (act != null) act.onApkInstallStatus(PackageInstaller.STATUS_PENDING_USER_ACTION, msg);
                } catch (Exception e) {
                    if (act != null) act.onApkInstallStatus(PackageInstaller.STATUS_FAILURE, String.valueOf(e.getMessage()));
                }
                return;
            }
            if (act != null) act.onApkInstallStatus(status, msg);
        }
    }
}
