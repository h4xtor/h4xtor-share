package com.h4xtor.share;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.View;

import java.util.Random;

/**
 * The key art behind the Del page's hero card, like a game page on Battle.net: deep-blue
 * light, a big glow where the monkey stands (the right), darker on the left so the words
 * read, embers rising through it, and a ring of sparks when a send lands ({@link #burst}).
 */
public final class HeroArt extends View {
    private static final int TOP = Color.parseColor("#0A1D3A");
    private static final int BOTTOM = Color.parseColor("#151922");
    private static final int EDGE = Color.parseColor("#272B34");
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path clip = new Path();
    private final RectF box = new RectF();
    private final float density;
    private final float[][] embers = new float[18][4];
    private long burstAt;
    private long started = System.currentTimeMillis();
    // Built once per size: drawing only moves and scales them (no allocations while animating).
    private LinearGradient background;
    private LinearGradient leftShade;
    private RadialGradient monkeyGlow;
    private RadialGradient cornerGlow;

    public HeroArt(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeWidth(Math.max(1, density));
        stroke.setColor(EDGE);
        Random random = new Random(11);
        for (float[] e : embers) {
            e[0] = 0.45f + random.nextFloat() * 0.55f;
            e[1] = random.nextFloat();
            e[2] = 0.05f + random.nextFloat() * 0.08f;
            e[3] = random.nextFloat() * 6.3f;
        }
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    /** A ring of sparks flies out from the monkey. */
    public void burst() {
        burstAt = System.currentTimeMillis();
        invalidate();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldWidth, int oldHeight) {
        super.onSizeChanged(w, h, oldWidth, oldHeight);
        if (w == 0 || h == 0) {
            return;
        }
        background = new LinearGradient(0, 0, 0, h, TOP, BOTTOM, Shader.TileMode.CLAMP);
        leftShade = new LinearGradient(0, 0, w * 0.62f, 0, Color.argb(120, 5, 8, 14), Color.TRANSPARENT,
                Shader.TileMode.CLAMP);
        monkeyGlow = new RadialGradient(0, 0, Math.max(w, h) * 0.55f, Color.argb(165, 20, 142, 255),
                Color.TRANSPARENT, Shader.TileMode.CLAMP);
        cornerGlow = new RadialGradient(0, 0, w * 0.45f, Color.argb(95, 69, 182, 255), Color.TRANSPARENT,
                Shader.TileMode.CLAMP);
        float r = 10 * density;
        box.set(0, 0, w, h);
        clip.reset();
        clip.addRoundRect(box, r, r, Path.Direction.CW);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int w = getWidth();
        int h = getHeight();
        if (background == null) {
            return;
        }
        float r = 10 * density;
        box.set(0, 0, w, h);
        canvas.save();
        canvas.clipPath(clip);
        boolean moving = ValueAnimator.areAnimatorsEnabled();
        long now = System.currentTimeMillis();
        double t = moving ? (now - started) / 1000.0 : 0;

        paint.setShader(background);
        canvas.drawRect(box, paint);
        float mx = w * 0.8f;
        float my = h * 0.5f;
        float pulse = 1 + 0.04f * (float) Math.sin(t * 1.3);
        glow(canvas, mx, my, Math.max(w, h) * 0.55f, pulse, monkeyGlow);
        glow(canvas, w * 1.02f, 0, w * 0.45f, 1, cornerGlow);
        paint.setShader(leftShade);
        canvas.drawRect(box, paint);  // darker on the left, under the words
        paint.setShader(null);
        for (float[] e : embers) {
            float rise = (float) ((e[1] + t * e[2]) % 1.0);
            float y = h * (1 - rise);
            float x = w * e[0] + (float) Math.sin(t * 0.8 + e[3]) * 5 * density;
            float twinkle = 0.5f + 0.5f * (float) Math.sin(t * 2 + e[3]);
            int alpha = Math.round((70 + 150 * twinkle) * Math.min(1f, rise * 4) * (1 - rise * 0.7f));
            dot.setColor(Color.argb(alpha, 140, 205, 255));
            canvas.drawCircle(x, y, (1.0f + 1.3f * twinkle) * density, dot);
        }
        float spark = (now - burstAt) / 900f;
        if (spark >= 0 && spark < 1) {
            float reach = (0.2f + spark) * 70 * density;
            int alpha = Math.round(255 * (1 - spark));
            dot.setColor(Color.argb(alpha, 200, 235, 255));
            for (int i = 0; i < 16; i++) {
                double angle = i * Math.PI * 2 / 16;
                canvas.drawCircle(mx + (float) Math.cos(angle) * reach, my + (float) Math.sin(angle) * reach,
                        (3.2f - 2f * spark) * density, dot);
            }
        }
        canvas.restore();
        float half = stroke.getStrokeWidth() / 2;
        box.inset(half, half);
        canvas.drawRoundRect(box, r, r, stroke);
        if ((moving || (spark >= 0 && spark < 1)) && isShown()) {
            postInvalidateDelayed(40);
        }
    }

    private void glow(Canvas canvas, float cx, float cy, float radius, float scale, RadialGradient shader) {
        paint.setShader(shader);
        canvas.save();
        canvas.translate(cx, cy);
        canvas.scale(scale, scale);
        canvas.drawCircle(0, 0, radius, paint);
        canvas.restore();
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        invalidate();
    }
}
