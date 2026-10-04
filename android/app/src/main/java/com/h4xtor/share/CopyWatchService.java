package com.h4xtor.share;

import android.accessibilityservice.AccessibilityService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.accessibility.AccessibilityEvent;

import java.util.Locale;

/**
 * Phone -> PC clipboard without opening the app. Android 10+ only lets the
 * focused app read the clipboard, so this accessibility service watches for a
 * tap on "Kopiér"/"Copy" in any app and then briefly opens the invisible
 * {@link ClipboardSendActivity}, which reads the clipboard and syncs it.
 * It reads no screen content; only the tapped button's label.
 */
public final class CopyWatchService extends AccessibilityService {
    private final Handler main = new Handler(Looper.getMainLooper());
    private long lastTrigger;

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getEventType() != AccessibilityEvent.TYPE_VIEW_CLICKED
                || getPackageName().equals(String.valueOf(event.getPackageName()))) {
            return;
        }
        CharSequence label = event.getContentDescription();
        if (label == null && !event.getText().isEmpty()) {
            label = event.getText().get(0);
        }
        if (android.util.Log.isLoggable("h4xtor", android.util.Log.DEBUG)) {  // adb: setprop log.tag.h4xtor DEBUG
            android.util.Log.d("h4xtor", "click in " + event.getPackageName() + ": " + label);
        }
        long now = SystemClock.elapsedRealtime();
        if (!isCopyLabel(label) || now - lastTrigger < 1000) {
            return;
        }
        lastTrigger = now;
        android.util.Log.i("h4xtor", "copy tapped in " + event.getPackageName());
        // Give the app a moment to actually put the text on the clipboard.
        main.postDelayed(() -> startActivity(new Intent(this, ClipboardSendActivity.class)
                .putExtra(ClipboardSendActivity.EXTRA_AUTO, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION)), 250);
    }

    @Override
    protected void onServiceConnected() {
        android.util.Log.i("h4xtor", "copy watcher connected");
    }

    @Override
    public void onInterrupt() {
    }

    /** "Kopiér", "Kopier link", "Copy", "Copy link" … but not long texts that merely mention copying. */
    static boolean isCopyLabel(CharSequence label) {
        if (label == null) {
            return false;
        }
        String text = label.toString().trim().toLowerCase(Locale.ROOT);
        return text.length() <= 30 && (text.startsWith("kopi") || text.startsWith("copy")
                || text.contains(" kopi") || text.contains(" copy"));
    }

    static boolean isEnabled(Context context) {
        String enabled = Settings.Secure.getString(context.getContentResolver(),
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        String me = new ComponentName(context, CopyWatchService.class).flattenToString();
        return enabled != null && enabled.contains(me);
    }
}
