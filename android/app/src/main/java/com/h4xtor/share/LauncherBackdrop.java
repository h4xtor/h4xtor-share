package com.h4xtor.share;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.View;

import java.util.Random;

/**
 * The Battle.net-style backdrop behind every page: a near-black launcher with blue light
 * falling in from the top right, three slow light beams and embers drifting up through the
 * light. Stands still when the user has turned animations off in Android.
 */
public final class LauncherBackdrop extends View {
    private static final int BASE = Color.parseColor("#111318");
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint beam = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ember = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float density;
    /** Per ember: x (0..1), start height (0..1), speed, twinkle phase. */
    private final float[][] embers = new float[26][4];
    private long started = System.currentTimeMillis();
    // Built once per size: drawing only moves them (no allocations while animating).
    private RadialGradient glowRight;
    private RadialGradient glowLeft;
    private LinearGradient beamShade;

    public LauncherBackdrop(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        beam.setStrokeCap(Paint.Cap.ROUND);
        Random random = new Random(7);
        for (float[] e : embers) {
            e[0] = random.nextFloat();
            e[1] = random.nextFloat();
            e[2] = 0.006f + random.nextFloat() * 0.014f;
            e[3] = random.nextFloat() * 6.3f;
        }
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldWidth, int oldHeight) {
        super.onSizeChanged(w, h, oldWidth, oldHeight);
        if (w == 0 || h == 0) {
            return;
        }
        glowRight = new RadialGradient(0, 0, w * 1.05f, Color.argb(92, 20, 142, 255), Color.TRANSPARENT,
                Shader.TileMode.CLAMP);
        glowLeft = new RadialGradient(0, 0, w * 0.7f, Color.argb(54, 11, 95, 200), Color.TRANSPARENT,
                Shader.TileMode.CLAMP);
        // One beam, drawn from (0, 0) along the x axis; each frame rotates and moves it.
        beamShade = new LinearGradient(0, 0, h * 0.5f, 0, Color.argb(30, 140, 200, 255), Color.TRANSPARENT,
                Shader.TileMode.CLAMP);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int w = getWidth();
        int h = getHeight();
        canvas.drawColor(BASE);
        if (glowRight == null) {
            return;
        }
        boolean moving = ValueAnimator.areAnimatorsEnabled();
        double t = moving ? (System.currentTimeMillis() - started) / 1000.0 : 0;
        float sway = (float) Math.sin(t / 9) * w * 0.03f;
        drawGlow(canvas, w * 0.9f + sway, -h * 0.05f, w * 1.05f, glowRight);
        drawGlow(canvas, w * 0.08f - sway, -h * 0.03f, w * 0.7f, glowLeft);
        float band = h * 0.45f;
        beam.setShader(beamShade);
        beam.setStrokeWidth(w * 0.07f);
        for (int i = 0; i < 3; i++) {  // light beams falling down-left from the top right
            float x = w * (0.55f + i * 0.17f) + (float) Math.sin(t / 6 + i * 1.7) * w * 0.02f;
            float length = band * (0.85f + 0.15f * (float) Math.sin(t / 5 + i)) * 1.15f;
            canvas.save();
            canvas.translate(x, -h * 0.02f);
            canvas.rotate(122);  // pointing down and to the left
            canvas.scale(length / (h * 0.5f), 1);
            canvas.drawLine(0, 0, h * 0.5f, 0, beam);
            canvas.restore();
        }
        for (float[] e : embers) {  // rise through the light, fade out as they go
            float rise = (float) ((e[1] + t * e[2]) % 1.0);
            float y = band * (1 - rise);
            float x = w * e[0] + (float) Math.sin(t / 3 + e[3]) * 6 * density;
            float twinkle = 0.5f + 0.5f * (float) Math.sin(t * 1.6 + e[3]);
            int alpha = Math.round((40 + 120 * twinkle) * Math.min(1f, rise * 3) * (1 - rise * 0.6f));
            ember.setColor(Color.argb(alpha, 120, 196, 255));
            canvas.drawCircle(x, y, (1.0f + 1.2f * twinkle) * density, ember);
        }
        if (moving && isShown()) {
            postInvalidateDelayed(40);
        }
    }

    private void drawGlow(Canvas canvas, float cx, float cy, float radius, RadialGradient shader) {
        glow.setShader(shader);
        canvas.save();
        canvas.translate(cx, cy);
        canvas.drawCircle(0, 0, radius, glow);
        canvas.restore();
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        started = System.currentTimeMillis() - 2_000;
        invalidate();
    }
}
