package com.h4xtor.share;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.View;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.EncodeHintType;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel;

import java.util.EnumMap;
import java.util.Map;

/** Crisp QR code drawn module by module (always dark on white for scanners). */
public final class QrCodeView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private BitMatrix matrix;

    public QrCodeView(Context context) {
        super(context);
        paint.setColor(Color.parseColor("#111111"));
        setBackgroundColor(Color.WHITE);
    }

    public void setContent(String text) {
        try {
            Map<EncodeHintType, Object> hints = new EnumMap<>(EncodeHintType.class);
            hints.put(EncodeHintType.MARGIN, 0);
            hints.put(EncodeHintType.CHARACTER_SET, "UTF-8");
            hints.put(EncodeHintType.ERROR_CORRECTION, ErrorCorrectionLevel.L);
            matrix = new QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0, hints);
        } catch (Exception error) {
            matrix = null;
        }
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (matrix == null) {
            return;
        }
        int modules = matrix.getWidth() + 8;
        float size = Math.min(getWidth(), getHeight());
        float cell = size / modules;
        float offset = 4 * cell;
        for (int y = 0; y < matrix.getHeight(); y++) {
            for (int x = 0; x < matrix.getWidth(); x++) {
                if (matrix.get(x, y)) {
                    float left = offset + x * cell;
                    float top = offset + y * cell;
                    canvas.drawRect(left, top, left + cell + 0.5f, top + cell + 0.5f, paint);
                }
            }
        }
    }
}
