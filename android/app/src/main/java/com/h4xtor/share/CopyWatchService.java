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
 * It reads no screen content; only the tapped button's label. Window access is
 * declared only because Android otherwise drops clicks from popups, and the
 * text toolbar holding "Copy" is a popup window of its own.
 */
public final class CopyWatchService extends AccessibilityService {
    private static volatile CopyWatchService instance;
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
        instance = this;
        android.util.Log.i("h4xtor", "copy watcher connected");
    }

    @Override
    public boolean onUnbind(Intent intent) {
        if (instance == this) {
            instance = null;
        }
        return super.onUnbind(intent);
    }

    @Override
    public void onInterrupt() {
    }

    /**
     * Turn the accessibility service off from inside the app (used by Bank-tilstand). Banking apps
     * refuse to run while an accessibility service that can read other apps is enabled, so this
     * genuinely removes it – it is not a way to hide it. Returns false when the service is not
     * running, so the caller can send the user to the system settings instead.
     */
    static boolean disableNow() {
        CopyWatchService self = instance;
        if (self == null) {
            return false;
        }
        try {
            self.disableSelf();
        } catch (Exception ignored) {
            return false;
        }
        instance = null;
        return true;
    }

    /**
     * A tap, swipe, button or typed text from a PC that mirrors the screen ("Vis og styr skærmen
     * fra PC'en", off by default). x and y are fractions of the screen (0-1). Returns an error for
     * the PC, or null when done.
     */
    /** Running and able to tap for a PC (the user switched it on under Hjælpefunktioner). */
    static boolean running() {
        return instance != null;
    }

    static String perform(org.json.JSONObject input) {
        CopyWatchService self = instance;
        if (self == null) {
            return "Slå h4xtor share til under Indstillinger → Tilgængelighed for at styre telefonen.";
        }
        android.util.DisplayMetrics metrics = new android.util.DisplayMetrics();
        self.getSystemService(android.hardware.display.DisplayManager.class)
                .getDisplay(android.view.Display.DEFAULT_DISPLAY).getRealMetrics(metrics);
        float w = metrics.widthPixels;
        float h = metrics.heightPixels;
        switch (input.optString("type")) {
            case "tap":
            case "swipe": {
                boolean tap = "tap".equals(input.optString("type"));
                android.graphics.Path path = new android.graphics.Path();
                path.moveTo(clamp(input.optDouble("x", -1)) * w, clamp(input.optDouble("y", -1)) * h);
                if (!tap) {
                    path.lineTo(clamp(input.optDouble("x2", -1)) * w, clamp(input.optDouble("y2", -1)) * h);
                }
                long duration = tap ? 60 : Math.max(80, Math.min(3000, input.optLong("ms", 300)));
                android.accessibilityservice.GestureDescription gesture =
                        new android.accessibilityservice.GestureDescription.Builder()
                                .addStroke(new android.accessibilityservice.GestureDescription.StrokeDescription(
                                        path, 0, duration))
                                .build();
                return self.dispatchGesture(gesture, null, null) ? null : "Telefonen tog ikke imod trykket.";
            }
            case "back":
                return self.performGlobalAction(GLOBAL_ACTION_BACK) ? null : "Tilbage virkede ikke.";
            case "home":
                return self.performGlobalAction(GLOBAL_ACTION_HOME) ? null : "Hjem virkede ikke.";
            case "recents":
                return self.performGlobalAction(GLOBAL_ACTION_RECENTS) ? null : "Seneste apps virkede ikke.";
            case "text": {
                android.view.accessibility.AccessibilityNodeInfo field = self.findFocus(
                        android.view.accessibility.AccessibilityNodeInfo.FOCUS_INPUT);
                if (field == null || !field.isEditable()) {
                    return "Tryk først i et tekstfelt på telefonen.";
                }
                CharSequence before = field.getText();
                String now = (before == null || field.isShowingHintText() ? "" : before.toString())
                        + input.optString("text", "");
                android.os.Bundle args = new android.os.Bundle();
                args.putCharSequence(
                        android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, now);
                return field.performAction(
                        android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, args)
                        ? null : "Teksten kunne ikke skrives.";
            }
            default:
                return "Ukendt handling.";
        }
    }

    private static float clamp(double value) {
        if (value < 0 || value > 1 || Double.isNaN(value)) {
            throw new IllegalArgumentException("Uden for skærmen.");
        }
        return (float) value;
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
        ComponentName me = new ComponentName(context, CopyWatchService.class);
        return enabled != null && (enabled.contains(me.flattenToString())
                || enabled.contains(me.flattenToShortString()));
    }
}
