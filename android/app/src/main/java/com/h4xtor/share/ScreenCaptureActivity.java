package com.h4xtor.share;

import android.app.Activity;
import android.content.Intent;
import android.media.projection.MediaProjectionManager;
import android.os.Bundle;
import android.widget.Toast;

/**
 * Transparent helper that asks the user for screen-capture consent when a PC requests a
 * screenshot, then hands the result to {@link ShareService}.
 */
public final class ScreenCaptureActivity extends Activity {
    private static final int REQUEST_CAPTURE = 7001;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ShareService service = ShareService.get();
        if (service == null || !service.hasScreenshotRequest()) {
            Toast.makeText(this, "Anmodningen om skærmbillede er udløbet", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        if (savedInstanceState == null) {
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            // Android 14+: ask for the whole screen directly, so the user only taps "Start"
            // instead of first picking between "one app" and "entire screen".
            startActivityForResult(android.os.Build.VERSION.SDK_INT >= 34
                            ? manager.createScreenCaptureIntent(
                                    android.media.projection.MediaProjectionConfig.createConfigForDefaultDisplay())
                            : manager.createScreenCaptureIntent(),
                    REQUEST_CAPTURE);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CAPTURE) {
            ShareService service = ShareService.get();
            if (service != null) {
                if (resultCode == RESULT_OK && data != null) {
                    service.startScreenCapture(resultCode, data);
                } else {
                    service.screenshotDeclined();
                }
            }
        }
        finish();
    }
}
