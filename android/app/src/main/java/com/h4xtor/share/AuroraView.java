package com.h4xtor.share;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.View;

/**
 * The mix design's background: three soft colour blobs (teal, sky, orange) that drift
 * slowly behind the glass cards, plus a faint dot grid. Stands still when the user has
 * turned animations off in Android.
 */
public final class AuroraView extends View {
    private static final int BASE = Color.parseColor("#0E1022");
    private final Paint blob = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float density;
    private long started = System.currentTimeMillis();

    public AuroraView(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        dot.setColor(Color.argb(14, 255, 255, 255));
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int w = getWidth();
        int h = getHeight();
        canvas.drawColor(BASE);
        boolean moving = ValueAnimator.areAnimatorsEnabled();
        double t = moving ? (System.currentTimeMillis() - started) / 1000.0 : 0;
        drawBlob(canvas, w * (0.15f + 0.12f * (float) Math.sin(t / 7)), h * (0.08f + 0.05f * (float) Math.cos(t / 9)),
                w * 0.95f, Color.argb(70, 45, 212, 191));
        drawBlob(canvas, w * (0.95f + 0.10f * (float) Math.cos(t / 8)), h * (0.52f + 0.06f * (float) Math.sin(t / 10)),
                w * 0.9f, Color.argb(56, 56, 189, 248));
        drawBlob(canvas, w * (0.05f + 0.08f * (float) Math.sin(t / 11)), h * (0.92f + 0.03f * (float) Math.cos(t / 7)),
                w * 0.7f, Color.argb(40, 251, 146, 60));
        float step = 22 * density;
        float radius = 0.9f * density;
        for (float y = step / 2; y < h; y += step) {
            for (float x = step / 2; x < w; x += step) {
                canvas.drawCircle(x, y, radius, dot);
            }
        }
        if (moving && isShown()) {
            postInvalidateDelayed(66); // ~15 fps is plenty for a slow drift
        }
    }

    private void drawBlob(Canvas canvas, float cx, float cy, float radius, int color) {
        blob.setShader(new RadialGradient(cx, cy, radius, color, Color.TRANSPARENT, Shader.TileMode.CLAMP));
        canvas.drawCircle(cx, cy, radius, blob);
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        started = System.currentTimeMillis() - 2_000;
        invalidate();
    }
}
