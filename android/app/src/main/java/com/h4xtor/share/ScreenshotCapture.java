package com.h4xtor.share;

import android.content.Context;
import android.content.res.Resources;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.DisplayMetrics;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicBoolean;

/** Grabs exactly one frame from a MediaProjection and writes it as a PNG in the app cache. */
final class ScreenshotCapture {
    interface Callback {
        /** Exactly one of {@code file} and {@code error} is set. */
        void done(File file, String error);
    }

    private static final long TIMEOUT_MS = 6_000L;

    private ScreenshotCapture() {
    }

    static void capture(Context context, MediaProjection projection, Callback callback) {
        DisplayMetrics metrics = Resources.getSystem().getDisplayMetrics();
        int width = metrics.widthPixels;
        int height = metrics.heightPixels;
        HandlerThread thread = new HandlerThread("h4xtor-capture");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        ImageReader reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        AtomicBoolean finished = new AtomicBoolean(false);
        VirtualDisplay[] display = new VirtualDisplay[1];

        Runnable[] timeout = new Runnable[1];
        java.util.function.BiConsumer<File, String> finish = (file, error) -> {
            if (!finished.compareAndSet(false, true)) {
                return;
            }
            handler.removeCallbacks(timeout[0]);
            if (display[0] != null) {
                display[0].release();
            }
            reader.close();
            projection.stop();
            thread.quitSafely();
            callback.done(file, error);
        };
        timeout[0] = () -> finish.accept(null, "Intet billede fra skærmen");

        try {
            // Android 14+ requires a callback before the first virtual display.
            projection.registerCallback(new MediaProjection.Callback() { }, handler);
            reader.setOnImageAvailableListener(source -> {
                Image image = source.acquireLatestImage();
                if (image == null || finished.get()) {
                    if (image != null) {
                        image.close();
                    }
                    return;
                }
                try {
                    File file = save(context, image, width, height);
                    finish.accept(file, null);
                } catch (Exception error) {
                    finish.accept(null, H4xtorClient.safeMessage(error));
                } finally {
                    image.close();
                }
            }, handler);
            display[0] = projection.createVirtualDisplay("h4xtor-screenshot", width, height,
                    metrics.densityDpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    reader.getSurface(), null, handler);
            handler.postDelayed(timeout[0], TIMEOUT_MS);
        } catch (Exception error) {
            finish.accept(null, H4xtorClient.safeMessage(error));
        }
    }

    private static File save(Context context, Image image, int width, int height) throws Exception {
        Image.Plane plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer();
        int pixelStride = plane.getPixelStride();
        int rowPadding = plane.getRowStride() - pixelStride * width;
        Bitmap padded = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888);
        padded.copyPixelsFromBuffer(buffer);
        Bitmap bitmap = Bitmap.createBitmap(padded, 0, 0, width, height);
        File folder = new File(context.getCacheDir(), "screens");
        if (!folder.isDirectory() && !folder.mkdirs()) {
            throw new IllegalStateException("Kan ikke gemme skærmbilledet");
        }
        File[] old = folder.listFiles();
        if (old != null) {
            for (File stale : old) {
                //noinspection ResultOfMethodCallIgnored
                stale.delete();
            }
        }
        File file = new File(folder, ShareLogic.screenshotName(System.currentTimeMillis()));
        try (FileOutputStream out = new FileOutputStream(file)) {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out);
        } finally {
            padded.recycle();
            if (bitmap != padded) {
                bitmap.recycle();
            }
        }
        return file;
    }
}
