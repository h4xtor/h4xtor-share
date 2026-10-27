package com.h4xtor.share;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;

import java.util.Random;

/**
 * The whole monkey on the Del page, alive (the same monkey and moves as the PC's
 * MonkeyActor in ui_kit.py). It strolls back and forth in its patch, stops now and then
 * and points at the devices, breathes and blinks. Hops while files move ({@link #setBusy}),
 * happy hops when a send lands ({@link #celebrate}), points at a new device ({@link #point})
 * and nods when one is ready ({@link #nod}). A tap does one of three things, never the
 * same twice in a row: a big grin, a stern "Lad være!" with a wagging finger, or a
 * somersault. With the phone's animations off it stands still and only reacts to taps.
 *
 * Drawn in its own 100 × 140 box (feet at y 140); time runs in 40 ms frames.
 */
public final class MonkeyView extends View {
    private static final int BROWN = Color.parseColor("#8B5A3C");
    private static final int FACE = Color.parseColor("#F2D3B1");
    private static final int INNER = Color.parseColor("#E9B98F");
    private static final int DARK = Color.parseColor("#3B2A20");
    private static final String BUBBLE = "Lad være!";
    private static final String[] REACTIONS = {"grin", "stop", "flip"};

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF box = new RectF();
    private final Random random = new Random();
    private final float density;

    private boolean busy;
    private long last;
    private int frame;
    private float x;  // -1 … 1 across the patch
    private float target;
    private int rest = 30;
    private String gesture = "";
    private int gestureFrame;
    private String lastReaction = "";
    private int blinkAt = 60;
    // The pose of this frame.
    private float step;
    private float stride;
    private int facing = 1;
    private float bob;
    private float rot;
    private float crouch;
    private float grin;
    private float point;
    private float wag;
    private float wagPhase;
    private boolean blink;

    public MonkeyView(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeCap(Paint.Cap.ROUND);
        line.setStrokeJoin(Paint.Join.ROUND);
        text.setColor(DARK);
        text.setTextSize(12 * density);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        text.setTextAlign(Paint.Align.CENTER);
        setContentDescription("H4xtor Share-aben – tryk for at hilse");
        setClickable(true);
        setOnClickListener(v -> tap());
    }

    public void setBusy(boolean busy) {
        this.busy = busy;
    }

    /** A device the phone had not seen before showed up: point at the tiles. */
    public void point() {
        play("point");
    }

    /** A paired device is online and ready: a friendly nod. */
    public void nod() {
        play("nod");
    }

    /** A send has landed: three happy hops. */
    public void celebrate() {
        play("hops");
    }

    /** Tapped: a reaction other than the last one (no somersault with animations off). */
    public String tap() {
        java.util.List<String> choices = new java.util.ArrayList<>();
        for (String reaction : REACTIONS) {
            if (!reaction.equals(lastReaction) && (moving() || !"flip".equals(reaction))) {
                choices.add(reaction);
            }
        }
        lastReaction = choices.get(random.nextInt(choices.size()));
        gesture = lastReaction;
        gestureFrame = 0;
        invalidate();
        return lastReaction;
    }

    private void play(String name) {
        if (moving()) {  // ambient gestures follow the phone's animation setting
            gesture = name;
            gestureFrame = 0;
            invalidate();
        }
    }

    private static boolean moving() {
        return ValueAnimator.areAnimatorsEnabled();
    }

    private static int length(String name) {
        switch (name) {
            case "point": return 36;
            case "nod": return 14;
            case "hops": return 26;
            case "grin": return 24;
            case "stop": return 50;
            default: return 30;  // flip
        }
    }

    // ------------------------------------------------------------------ frames
    private void tick() {
        frame++;
        boolean calm = !moving();
        bob = calm ? 0 : (float) Math.sin(frame / 14.0) * 0.8f;  // breathing
        rot = crouch = grin = point = wag = 0;
        boolean walking = false;
        if (!gesture.isEmpty()) {
            int length = length(gesture);
            act(gesture, gestureFrame / (float) (length - 1));  // ends at rest
            if (++gestureFrame >= length) {
                gesture = "";
            }
        } else if (busy && !calm) {
            bob -= Math.abs(Math.sin(frame * Math.PI / 13)) * 14;
        } else if (!calm) {
            walking = stroll();
        }
        if (walking) {
            step += 0.38f;
        }
        stride += ((walking ? 1 : 0) - stride) * 0.25f;
        if (frame >= blinkAt) {  // eyes shut for three frames now and then
            blink = frame - blinkAt < 3;
            if (!blink) {
                blinkAt = frame + 70 + (frame * 37) % 80;
            }
        }
    }

    private boolean stroll() {
        if (rest > 0) {
            rest--;
            return false;
        }
        float gap = target - x;
        if (Math.abs(gap) < 0.02f) {
            rest = 40 + random.nextInt(71);
            target = random.nextFloat() * 2 - 1;
            if (random.nextFloat() < 0.3f) {
                play("point");  // stops and shows you the devices
            }
            return false;
        }
        x += Math.max(-0.014f, Math.min(0.014f, gap));
        facing = gap > 0 ? 1 : -1;
        return true;
    }

    private void act(String name, float p) {
        float swell = Math.min(1f, Math.min(p / 0.2f, (1 - p) / 0.2f));  // in, hold, out
        switch (name) {
            case "point":
                point = swell;
                facing = -1;
                break;
            case "nod":
                bob += Math.abs(Math.sin(p * Math.PI * 2)) * 6;
                break;
            case "hops":
                bob -= Math.abs(Math.sin(p * 3 * Math.PI)) * 14 * (1 - p * 0.5f);
                break;
            case "grin":
                grin = swell;
                bob -= Math.sin(p * Math.PI) * 6;
                break;
            case "stop":
                wag = swell;
                wagPhase = p * 40;
                break;
            default:  // flip
                if (p < 0.2f) {
                    crouch = p / 0.2f;
                } else if (p < 0.85f) {
                    float q = (p - 0.2f) / 0.65f;
                    bob -= Math.sin(q * Math.PI) * 32;
                    rot = -360 * q * facing;
                } else {
                    crouch = (1 - p) / 0.15f * 0.6f;
                }
        }
    }

    // ----------------------------------------------------------------- drawing
    @Override
    protected void onDraw(Canvas canvas) {
        long now = System.currentTimeMillis();
        if (last == 0) {
            last = now;
        }
        int frames = (int) Math.min(3, (now - last) / 40);
        for (int i = 0; i < frames; i++) {
            tick();
        }
        last = frames > 0 ? now : last;
        float w = getWidth();
        float h = getHeight();
        float size = Math.min(w * 0.62f, h / 1.4f * 0.92f);
        float roam = (w - size) / 2;
        float s = size / 100;
        float ox = w / 2 + x * roam - 50 * s;
        float oy = h - 2 * density - 140 * s;
        canvas.save();
        canvas.translate(ox, oy);
        canvas.scale(s, s);
        canvas.translate(0, bob);
        canvas.rotate(rot, 50, 92);
        canvas.scale(1, 1 - 0.14f * crouch, 50, 140);
        drawMonkey(canvas);
        canvas.restore();
        if (wag > 0.3f) {  // the speech bubble over its head
            float bx = ox + 50 * s;
            float by = oy + 2 * s;
            float half = text.measureText(BUBBLE) / 2 + 7 * density;
            box.set(bx - half, by - 24 * density, bx + half, by);
            fill.setColor(Color.WHITE);
            canvas.drawRoundRect(box, 7 * density, 7 * density, fill);
            canvas.drawText(BUBBLE, bx, by - 8 * density, text);
        }
        if ((moving() || !gesture.isEmpty()) && isShown()) {
            postInvalidateDelayed(40);
        }
    }

    private void drawMonkey(Canvas c) {
        int side = -facing;  // the tail trails behind
        path.reset();
        path.moveTo(50 + side * 14, 114);
        path.cubicTo(50 + side * 30, 110, 50 + side * 37, 94, 50 + side * 30, 80);
        stroke(BROWN, 5);
        c.drawPath(path, line);
        float swing = (float) Math.sin(step) * stride * 8;
        float lift = (float) Math.sin(step) * stride * 4;
        leg(c, 43, 43 + swing, Math.max(0, lift));
        leg(c, 57, 57 - swing, Math.max(0, -lift));
        oval(c, 50, 92, 21, 25, BROWN);
        oval(c, 50, 97, 13, 17, FACE);
        float cheer = grin * 0.7f;
        float lx = mix(mix(27 - swing * 0.6f, 20, cheer), -8, point);
        float ly = mix(mix(104, 62, cheer), 120, point);
        float rx = mix(mix(73 + swing * 0.6f, 80, cheer), 79, wag);
        float ry = mix(mix(104, 62, cheer), 48, wag);
        arm(c, 34, 80, lx, ly);
        arm(c, 66, 80, rx, ry);
        if (wag > 0.2f) {  // the raised finger, wagging
            stroke(INNER, 3.2f);
            c.drawLine(rx, ry, rx + (float) Math.sin(wagPhase) * 5 * wag, ry - 10 * wag, line);
        }
        float ears = 1 + 0.35f * grin;
        for (int ex = 18; ex <= 82; ex += 64) {
            oval(c, ex, 40, 12, 12 * ears, BROWN);
            oval(c, ex, 40, 7, 7 * ears, INNER);
        }
        oval(c, 50, 40, 30, 30, BROWN);
        path.reset();
        path.moveTo(44, 12);
        path.quadTo(50, -2, 55, 11);
        stroke(BROWN, 4);
        c.drawPath(path, line);
        oval(c, 40, 36, 11, 11, FACE);
        oval(c, 60, 36, 11, 11, FACE);
        oval(c, 50, 53, 21, 14, FACE);
        float look = facing * 1.2f;
        for (int ex = 40; ex <= 60; ex += 20) {
            if (blink) {
                stroke(DARK, 2.2f);
                c.drawLine(ex - 4, 36, ex + 4, 36, line);
            } else {
                oval(c, ex + look, 36, 4.2f, 4.2f, DARK);
                oval(c, ex + look + 1.3f, 34.5f, 1.3f, 1.3f, Color.WHITE);
            }
        }
        stroke(DARK, 2.4f);
        if (wag > 0.3f) {  // stern brows
            c.drawLine(33, 27, 45, 30, line);
            c.drawLine(67, 27, 55, 30, line);
        }
        oval(c, 46, 50, 1.5f, 1.5f, DARK);
        oval(c, 54, 50, 1.5f, 1.5f, DARK);
        if (grin > 0.15f) {  // open mouth: the lower half of an oval
            float tall = 3 + 8 * grin;
            box.set(40, 56 - tall, 60, 56 + tall);
            fill.setColor(DARK);
            c.drawArc(box, 0, 180, true, fill);
        } else if (wag > 0.3f) {
            c.drawLine(44, 60, 56, 59, line);
        } else {
            box.set(41, 49, 59, 61);
            c.drawArc(box, 20, 140, false, line);  // a smile
        }
    }

    private void leg(Canvas c, float hip, float footX, float up) {
        stroke(BROWN, 9);
        c.drawLine(hip, 110, footX, 133 - up, line);
        oval(c, footX + facing * 2, 136 - up, 7.5f, 4.2f, INNER);
    }

    private void arm(Canvas c, float sx, float sy, float hx, float hy) {
        stroke(BROWN, 7);
        c.drawLine(sx, sy, hx, hy, line);
        oval(c, hx, hy, 5.2f, 5.2f, INNER);
    }

    private void oval(Canvas c, float cx, float cy, float rx, float ry, int color) {
        fill.setColor(color);
        box.set(cx - rx, cy - ry, cx + rx, cy + ry);
        c.drawOval(box, fill);
    }

    private void stroke(int color, float width) {
        line.setColor(color);
        line.setStrokeWidth(width);
    }

    private static float mix(float a, float b, float k) {
        return a + (b - a) * k;
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        last = 0;  // no catching up on frames missed while away
        invalidate();
    }
}
