package com.h4xtor.share;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Shader;
import android.view.View;

/** A small live speed chart: area + line, newest sample on the right. */
public final class SpeedGraph extends View {
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint grid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int color;
    private float[] samples = new float[0];

    public SpeedGraph(Context context, int color, int gridColor) {
        super(context);
        this.color = color;
        float density = context.getResources().getDisplayMetrics().density;
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeWidth(2f * density);
        line.setStrokeJoin(Paint.Join.ROUND);
        line.setStrokeCap(Paint.Cap.ROUND);
        line.setColor(color);
        fill.setStyle(Paint.Style.FILL);
        grid.setStyle(Paint.Style.STROKE);
        grid.setStrokeWidth(Math.max(1f, density * 0.7f));
        grid.setColor(gridColor);
        dot.setStyle(Paint.Style.FILL);
        dot.setColor(color);
    }

    public void setSamples(float[] values) {
        samples = values == null ? new float[0] : values;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float width = getWidth();
        float height = getHeight();
        float pad = line.getStrokeWidth() * 2;
        for (int index = 1; index <= 2; index++) {
            float y = height * index / 3f;
            canvas.drawLine(0, y, width, y, grid);
        }
        if (samples.length < 2) {
            return;
        }
        float max = 1f;
        for (float value : samples) {
            max = Math.max(max, value);
        }
        Path path = new Path();
        Path area = new Path();
        float step = (width - pad) / (samples.length - 1);
        float lastX = 0;
        float lastY = 0;
        for (int index = 0; index < samples.length; index++) {
            float x = index * step;
            float y = height - pad - (samples[index] / max) * (height - pad * 2);
            if (index == 0) {
                path.moveTo(x, y);
                area.moveTo(x, height);
                area.lineTo(x, y);
            } else {
                path.lineTo(x, y);
                area.lineTo(x, y);
            }
            lastX = x;
            lastY = y;
        }
        area.lineTo(lastX, height);
        area.close();
        fill.setShader(new LinearGradient(0, 0, 0, height,
                Color.argb(90, Color.red(color), Color.green(color), Color.blue(color)),
                Color.argb(0, Color.red(color), Color.green(color), Color.blue(color)),
                Shader.TileMode.CLAMP));
        canvas.drawPath(area, fill);
        canvas.drawPath(path, line);
        canvas.drawCircle(lastX, lastY, line.getStrokeWidth() * 1.6f, dot);
    }
}
