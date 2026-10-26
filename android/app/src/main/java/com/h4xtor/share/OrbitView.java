package com.h4xtor.share;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/**
 * The mix design's device map: the monkey (this phone) in the middle, paired devices on an
 * orbit. A dashed ring turns, a ring pulses from the monkey, and lights travel along the
 * beam while something is being sent. The monkey blinks and hops when a send has landed.
 * Tap a device to send to it.
 */
public final class OrbitView extends View {
    public interface Listener {
        void onPick(String deviceId);
    }

    public static final class Node {
        final String id;
        final String name;
        final String sub;
        final boolean online;
        final boolean selected;
        final boolean sending;

        public Node(String id, String name, String sub, boolean online, boolean selected, boolean sending) {
            this.id = id;
            this.name = name;
            this.sub = sub;
            this.online = online;
            this.selected = selected;
            this.sending = sending;
        }
    }

    private static final int TEAL = Color.parseColor("#2DD4BF");
    private static final int SKY = Color.parseColor("#38BDF8");
    private final Paint ring = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint label = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint small = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Drawable monkey;
    private final float d;
    private final List<Node> nodes = new ArrayList<>();
    private final List<float[]> hits = new ArrayList<>();
    private Listener listener;
    private String caption = "";
    private long hopUntil;
    private final long born = System.currentTimeMillis();

    public OrbitView(Context context) {
        super(context);
        d = context.getResources().getDisplayMetrics().density;
        monkey = context.getDrawable(R.drawable.ic_monkey);
        ring.setStyle(Paint.Style.STROKE);
        stroke.setStyle(Paint.Style.STROKE);
        label.setColor(Color.parseColor("#EEF2FF"));
        label.setTextAlign(Paint.Align.CENTER);
        label.setTypeface(Typeface.create("sans-serif-medium", Typeface.BOLD));
        label.setTextSize(11.5f * d);
        small.setTextAlign(Paint.Align.CENTER);
        small.setTypeface(Typeface.MONOSPACE);
        small.setTextSize(10f * d);
        setContentDescription("Kort over dine enheder");
    }

    public void setListener(Listener listener) {
        this.listener = listener;
    }

    public void setNodes(List<Node> next, String caption) {
        nodes.clear();
        nodes.addAll(next);
        this.caption = caption;
        invalidate();
    }

    /** The monkey hops for a moment: something just landed. */
    public void celebrate() {
        hopUntil = System.currentTimeMillis() + 900;
        invalidate();
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        int width = MeasureSpec.getSize(widthSpec);
        setMeasuredDimension(width, Math.round(Math.min(width * 0.72f, 280 * d)));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        boolean moving = ValueAnimator.areAnimatorsEnabled();
        long now = System.currentTimeMillis();
        float t = moving ? (now - born) / 1000f : 0f;
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float orbit = Math.min(cx, cy) * 0.86f;

        ring.setColor(Color.argb(46, 203, 213, 225));
        ring.setStrokeWidth(1.2f * d);
        ring.setPathEffect(new DashPathEffect(new float[]{5 * d, 7 * d}, -t * 8 * d));
        canvas.drawCircle(cx, cy, orbit, ring);
        ring.setPathEffect(null);
        ring.setColor(Color.argb(22, 203, 213, 225));
        canvas.drawCircle(cx, cy, orbit * 0.58f, ring);

        float hub = 36 * d;
        float phase = (t % 3f) / 3f;
        stroke.setStrokeWidth(2 * d);
        stroke.setColor(Color.argb(Math.round(150 * (1 - phase)), 45, 212, 191));
        canvas.drawCircle(cx, cy, hub + phase * orbit * 0.5f, stroke);

        hits.clear();
        int count = nodes.size();
        boolean anySending = false;
        for (int i = 0; i < count; i++) {
            Node node = nodes.get(i);
            double angle = Math.toRadians(-40 + i * (360.0 / Math.max(count, 1)));
            float x = cx + (float) (orbit * Math.cos(angle));
            float y = cy + (float) (orbit * 0.92f * Math.sin(angle));
            boolean live = node.online && (node.selected || node.sending);
            stroke.setStrokeWidth((live ? 2f : 1f) * d);
            stroke.setColor(live ? TEAL : Color.argb(40, 203, 213, 225));
            stroke.setPathEffect(new DashPathEffect(new float[]{4 * d, 6 * d}, -t * 30 * d));
            canvas.drawLine(cx, cy, x, y, stroke);
            stroke.setPathEffect(null);
            if (node.sending && node.online) {
                anySending = true;
                for (int k = 0; k < 2; k++) {
                    float p = ((t * 1.1f) + k * 0.5f) % 1f;
                    fill.setColor(k == 0 ? TEAL : SKY);
                    canvas.drawCircle(cx + (x - cx) * p, cy + (y - cy) * p, (k == 0 ? 4.5f : 3.2f) * d, fill);
                }
            }
            float r = 31 * d;
            fill.setColor(node.online ? Color.parseColor("#E6141834") : Color.parseColor("#E60E1124"));
            canvas.drawCircle(x, y, r, fill);
            stroke.setStrokeWidth(2 * d);
            stroke.setColor(node.selected ? TEAL : node.sending ? SKY : Color.argb(60, 203, 213, 225));
            canvas.drawCircle(x, y, r, stroke);
            String name = node.name.length() > 10 ? node.name.substring(0, 9) + "…" : node.name;
            label.setColor(node.online ? Color.parseColor("#EEF2FF") : Color.parseColor("#A3ABC6"));
            canvas.drawText(name, x, y - 1 * d, label);
            small.setColor(node.online ? TEAL : Color.parseColor("#7C84A6"));
            canvas.drawText(node.sub, x, y + 13 * d, small);
            hits.add(new float[]{x, y, r * 1.3f});
        }

        fill.setColor(Color.parseColor("#F2141834"));
        canvas.drawCircle(cx, cy, hub, fill);
        stroke.setColor(TEAL);
        stroke.setStrokeWidth(2 * d);
        canvas.drawCircle(cx, cy, hub, stroke);
        float hop = 0;
        if (now < hopUntil) {
            float k = (hopUntil - now) / 900f;
            hop = (float) Math.abs(Math.sin(k * Math.PI * 2)) * 7 * d;
        }
        int m = Math.round(hub * 1.45f);
        if (monkey != null) {
            monkey.setBounds(Math.round(cx - m / 2f), Math.round(cy - m / 2f - hop),
                    Math.round(cx + m / 2f), Math.round(cy + m / 2f - hop));
            monkey.draw(canvas);
            // Blink: a quick lid over both eyes every few seconds.
            if (moving && (t % 4.6f) < 0.14f) {
                fill.setColor(Color.parseColor("#F2D3B1"));
                float s = m / 100f;
                float ox = cx - m / 2f;
                float oy = cy - m / 2f - hop;
                canvas.drawOval(new RectF(ox + 34 * s, oy + 40 * s, ox + 46 * s, oy + 50 * s), fill);
                canvas.drawOval(new RectF(ox + 54 * s, oy + 40 * s, ox + 66 * s, oy + 50 * s), fill);
            }
        }
        small.setColor(Color.parseColor("#A3ABC6"));
        canvas.drawText(caption, cx, cy + hub + 15 * d, small);

        if (moving && isShown()) {
            postInvalidateDelayed(anySending || now < hopUntil ? 16 : 40);
        }
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
            return true;
        }
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            for (int i = 0; i < hits.size() && i < nodes.size(); i++) {
                float[] hit = hits.get(i);
                float dx = event.getX() - hit[0];
                float dy = event.getY() - hit[1];
                if (dx * dx + dy * dy <= hit[2] * hit[2]) {
                    if (listener != null) {
                        listener.onPick(nodes.get(i).id);
                    }
                    performClick();
                    return true;
                }
            }
        }
        return super.onTouchEvent(event);
    }

    @Override
    public boolean performClick() {
        return super.performClick();
    }
}
