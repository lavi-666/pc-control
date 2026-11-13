package com.pccontrol.remote;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.util.LruCache;
import android.widget.ImageView;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Cover art / queue thumbnails: background download, downsampling, small LRU cache. */
final class PcImages {
    private static final LruCache<String, Bitmap> CACHE = new LruCache<String, Bitmap>(12 * 1024 * 1024) {
        @Override
        protected int sizeOf(String key, Bitmap value) {
            return value.getByteCount();
        }
    };
    private static final ExecutorService POOL = Executors.newFixedThreadPool(3);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private PcImages() {}

    interface Done {
        void done(boolean ok);
    }

    /** Loads url into iv (tagged so recycled rows never show a stale picture). */
    static void load(final ImageView iv, final String url, final int targetPx, final Done done) {
        if (url == null || url.isEmpty()) {
            iv.setTag(null);
            iv.setImageDrawable(null);
            if (done != null) done.done(false);
            return;
        }
        if (url.equals(iv.getTag()) && iv.getDrawable() != null) {
            if (done != null) done.done(true);
            return;
        }
        iv.setTag(url);
        Bitmap cached = CACHE.get(url);
        if (cached != null) {
            iv.setImageBitmap(cached);
            if (done != null) done.done(true);
            return;
        }
        iv.setImageDrawable(null);
        POOL.execute(new Runnable() {
            @Override
            public void run() {
                final Bitmap b = fetch(url, targetPx);
                if (b != null) CACHE.put(url, b);
                MAIN.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!url.equals(iv.getTag())) return;
                        if (b != null) iv.setImageBitmap(b);
                        if (done != null) done.done(b != null);
                    }
                });
            }
        });
    }

    private static Bitmap fetch(String url, int targetPx) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(8000);
            c.setInstanceFollowRedirects(true);
            if (c.getResponseCode() != 200) return null;
            byte[] data;
            try (InputStream in = c.getInputStream()) {
                data = PcHttp.readAll(in, 8 * 1024 * 1024);
            }
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(data, 0, data.length, o);
            int sample = 1;
            while (o.outWidth / (sample * 2) >= targetPx && o.outHeight / (sample * 2) >= targetPx) sample *= 2;
            BitmapFactory.Options d = new BitmapFactory.Options();
            d.inSampleSize = sample;
            return BitmapFactory.decodeByteArray(data, 0, data.length, d);
        } catch (Throwable e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }
}
