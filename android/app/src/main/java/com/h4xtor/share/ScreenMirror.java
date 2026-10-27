package com.h4xtor.share;

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
import android.os.SystemClock;
import android.util.DisplayMetrics;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;

/**
 * The phone's screen, live, for a PC: a mirror of the display at most {@link #LONG_SIDE} pixels
 * on its long side, kept as the newest compressed frame (JPEG, or PNG for PCs that cannot read
 * JPEG). The PC asks for frames newer than the one it has ({@link #await}).
 */
final class ScreenMirror {
    static final int LONG_SIDE = 960;
    private static final long FRAME_GAP_MS = 110;  // at most ~9 frames a second
    private static final long NUDGE_MS = 1_500;

    final int width;
    final int height;
    final boolean png;
    private final MediaProjection projection;
    private final HandlerThread thread = new HandlerThread("h4xtor-mirror");
    private final Handler handler;
    private final ImageReader reader;
    private final VirtualDisplay display;
    private final Object lock = new Object();
    private byte[] frame;
    private int seq;
    private long lastFrameAt;
    private volatile boolean stopped;

    ScreenMirror(MediaProjection projection, boolean png, Runnable onStopped) {
        this.projection = projection;
        this.png = png;
        DisplayMetrics metrics = Resources.getSystem().getDisplayMetrics();
        float scale = Math.min(1f, LONG_SIDE / (float) Math.max(metrics.widthPixels, metrics.heightPixels));
        width = Math.max(2, Math.round(metrics.widthPixels * scale) & ~1);
        height = Math.max(2, Math.round(metrics.heightPixels * scale) & ~1);
        thread.start();
        handler = new Handler(thread.getLooper());
        reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        // Android 14+ requires a callback before the first virtual display; the user can also
        // stop sharing from the system's own controls, which ends up here.
        projection.registerCallback(new MediaProjection.Callback() {
            @Override
            public void onStop() {
                stop();
                onStopped.run();
            }
        }, handler);
        reader.setOnImageAvailableListener(this::onImage, handler);
        display = projection.createVirtualDisplay("h4xtor-mirror", width, height,
                Math.max(120, Math.round(metrics.densityDpi * scale)),
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, handler);
        handler.postDelayed(this::nudge, NUDGE_MS);
    }

    private void onImage(ImageReader source) {
        Image image = source.acquireLatestImage();
        if (image == null) {
            return;
        }
        try {
            long now = SystemClock.elapsedRealtime();
            if (stopped || now - lastFrameAt < FRAME_GAP_MS) {
                return;
            }
            lastFrameAt = now;
            byte[] bytes = compress(image);
            synchronized (lock) {
                frame = bytes;
                seq++;
                lock.notifyAll();
            }
        } catch (Exception ignored) {
            // A frame lost; the next one comes along.
        } finally {
            image.close();
        }
    }

    /** A still screen sends no frames: re-attaching the surface makes it send the current one. */
    private void nudge() {
        if (stopped) {
            return;
        }
        if (SystemClock.elapsedRealtime() - lastFrameAt > NUDGE_MS) {
            display.setSurface(null);
            display.setSurface(reader.getSurface());
        }
        handler.postDelayed(this::nudge, NUDGE_MS);
    }

    private byte[] compress(Image image) {
        Image.Plane plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer();
        int pixelStride = plane.getPixelStride();
        int rowPadding = plane.getRowStride() - pixelStride * width;
        Bitmap padded = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888);
        padded.copyPixelsFromBuffer(buffer);
        Bitmap bitmap = rowPadding == 0 ? padded : Bitmap.createBitmap(padded, 0, 0, width, height);
        ByteArrayOutputStream out = new ByteArrayOutputStream(64 * 1024);
        bitmap.compress(png ? Bitmap.CompressFormat.PNG : Bitmap.CompressFormat.JPEG, 62, out);
        if (bitmap != padded) {
            bitmap.recycle();
        }
        padded.recycle();
        return out.toByteArray();
    }

    /** {seq, frame}: the newest frame after {@code afterSeq}, waiting up to {@code timeoutMs}. */
    Object[] await(int afterSeq, long timeoutMs) throws InterruptedException {
        long deadline = SystemClock.elapsedRealtime() + timeoutMs;
        synchronized (lock) {
            while (!stopped && (frame == null || seq <= afterSeq)) {
                long left = deadline - SystemClock.elapsedRealtime();
                if (left <= 0) {
                    break;
                }
                lock.wait(left);
            }
            return new Object[] {seq, frame};
        }
    }

    boolean active() {
        return !stopped;
    }

    void stop() {
        if (stopped) {
            return;
        }
        stopped = true;
        synchronized (lock) {
            lock.notifyAll();
        }
        handler.post(() -> {
            try {
                display.release();
                reader.close();
                projection.stop();
            } catch (Exception ignored) {
                // Already gone.
            }
            thread.quitSafely();
        });
    }
}
