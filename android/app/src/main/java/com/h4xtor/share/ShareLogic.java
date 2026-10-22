package com.h4xtor.share;

import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Small framework-free helpers for the v1.2 features (kept pure so JUnit can test them). */
final class ShareLogic {
    static final int ICON_MAX_BYTES = 48 * 1024;
    static final int SPEAK_MAX_CHARS = 1000;
    static final int SMS_MAX_CHARS = 1600;
    static final int SMS_TYPE_INBOX = 1;
    static final int SMS_TYPE_DRAFT = 3;
    private static final Pattern PHONE = Pattern.compile("[+0-9 ()*#./-]{1,32}");

    private ShareLogic() {
    }

    /** Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY (plain value: this class runs in JUnit). */
    static final int LAUNCHED_FROM_HISTORY = 0x00100000;

    /** False for a share Android hands over again: reopened from history, or rebuilt after it was sent. */
    static boolean shouldHandleShare(int intentFlags, boolean alreadyStarted) {
        return !alreadyStarted && (intentFlags & LAUNCHED_FROM_HISTORY) == 0;
    }

    static String clip(String value, int max) {
        if (value == null) {
            return "";
        }
        return value.length() > max ? value.substring(0, max) : value;
    }

    // ------------------------------------------------------- Wi-Fi Direct names
    /** Android only hosts groups named "DIRECT-xy…"; the user picks what comes after it. */
    static final String P2P_PREFIX = "DIRECT-h4-";
    private static final Pattern P2P_NAME = Pattern.compile("[A-Za-z0-9 _-]{1,22}");
    private static final Pattern P2P_PASS = Pattern.compile("[\\x20-\\x7E]{8,63}");

    /** Why the chosen name part cannot be used, or null when it is fine (max 32 bytes in total). */
    static String p2pNameError(String suffix) {
        if (suffix == null || suffix.trim().isEmpty()) {
            return "Skriv et navn.";
        }
        if (!P2P_NAME.matcher(suffix.trim()).matches()) {
            return "Navnet må højst være 22 tegn: bogstaver a–z, tal, mellemrum, - og _.";
        }
        return null;
    }

    /** Why the chosen code cannot be used, or null when it is a valid WPA2 passphrase. */
    static String p2pPassError(String pass) {
        if (pass == null || pass.length() < 8) {
            return "Koden skal være mindst 8 tegn.";
        }
        if (!P2P_PASS.matcher(pass).matches()) {
            return "Koden må højst være 63 tegn og kun bruge tegn fra et almindeligt tastatur (ikke æ, ø, å).";
        }
        return null;
    }

    // ----------------------------------------------------------- remote control
    static int clampPercent(int value) {
        return Math.max(0, Math.min(100, value));
    }

    static int volumeIndex(int percent, int maxIndex) {
        return Math.round(clampPercent(percent) * Math.max(0, maxIndex) / 100f);
    }

    static int volumePercent(int index, int maxIndex) {
        return maxIndex <= 0 ? 0 : clampPercent(Math.round(index * 100f / maxIndex));
    }

    // ------------------------------------------------------------ notifications
    /** Stored packages -> clean set. Blank, null and absurdly long entries are dropped. */
    static Set<String> parseAllowList(Collection<String> stored) {
        Set<String> result = new LinkedHashSet<>();
        if (stored == null) {
            return result;
        }
        for (String item : stored) {
            String value = item == null ? "" : item.trim();
            if (!value.isEmpty() && value.length() <= 200 && result.size() < 1000) {
                result.add(value);
            }
        }
        return result;
    }

    /** Empty allow-list means every app. */
    static boolean isAllowed(Set<String> allowList, String packageName) {
        return allowList == null || allowList.isEmpty() || allowList.contains(packageName);
    }

    static boolean shouldMirror(boolean ownPackage, boolean ongoing, boolean groupSummary,
                                String title, String text) {
        if (ownPackage || ongoing || groupSummary) {
            return false;
        }
        return !(isBlank(title) && isBlank(text));
    }

    static boolean iconFits(int pngBytes) {
        return pngBytes > 0 && pngBytes <= ICON_MAX_BYTES;
    }

    static JSONObject notificationPosted(String key, String packageName, String app, String title,
                                         String text, long time, String iconBase64,
                                         boolean canReply, boolean canDismiss) throws JSONException {
        return new JSONObject()
                .put("event", "posted")
                .put("key", clip(key, 512))
                .put("package", clip(packageName, 200))
                .put("app", clip(app, 80))
                .put("title", clip(title, 200))
                .put("text", clip(text, 4000))
                .put("time", time)
                .put("icon", iconBase64 == null ? "" : iconBase64)
                .put("can_reply", canReply)
                .put("can_dismiss", canDismiss);
    }

    static JSONObject notificationRemoved(String key) throws JSONException {
        return new JSONObject().put("event", "removed").put("key", clip(key, 512));
    }

    /** Drops the same title+text arriving again for one key within a short window. */
    static final class DuplicateGate {
        private final long windowMs;
        private final Map<String, String> signature = new HashMap<>();
        private final Map<String, Long> seenAt = new HashMap<>();

        DuplicateGate(long windowMs) {
            this.windowMs = windowMs;
        }

        synchronized boolean accept(String key, String title, String text, long now) {
            String sig = title + "\u0000" + text;
            Long last = seenAt.get(key);
            if (last != null && sig.equals(signature.get(key)) && now - last < windowMs) {
                return false;
            }
            if (seenAt.size() > 500) {
                seenAt.entrySet().removeIf(entry -> now - entry.getValue() > windowMs);
                signature.keySet().retainAll(seenAt.keySet());
            }
            signature.put(key, sig);
            seenAt.put(key, now);
            return true;
        }

        synchronized void forget(String key) {
            signature.remove(key);
            seenAt.remove(key);
        }
    }

    // --------------------------------------------------------------------- sms
    static boolean isOutgoing(int smsType) {
        return smsType != SMS_TYPE_INBOX;
    }

    static int limit(int requested, int fallback, int max) {
        if (requested <= 0) {
            return fallback;
        }
        return Math.min(requested, max);
    }

    static boolean validPhoneNumber(String address) {
        return address != null && PHONE.matcher(address.trim()).matches();
    }

    static JSONObject smsThread(String threadId, String address, String name, String snippet,
                                long time, int unread) throws JSONException {
        return new JSONObject()
                .put("thread_id", threadId)
                .put("address", clip(address, 64))
                .put("name", clip(name, 80))
                .put("snippet", clip(snippet, 200))
                .put("time", time)
                .put("unread", Math.max(0, unread));
    }

    static JSONObject smsMessage(String id, String address, String body, long time,
                                 boolean outgoing) throws JSONException {
        return new JSONObject()
                .put("id", id)
                .put("address", clip(address, 64))
                .put("body", clip(body, 4000))
                .put("time", time)
                .put("outgoing", outgoing);
    }

    static JSONObject smsIncoming(String threadId, String address, String name, String body,
                                  long time) throws JSONException {
        return new JSONObject()
                .put("thread_id", threadId)
                .put("address", clip(address, 64))
                .put("name", clip(name, 80))
                .put("body", clip(body, 4000))
                .put("time", time);
    }

    // -------------------------------------------------------------- screenshots
    static String screenshotName(long millis) {
        return "Skaermbillede-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT)
                .format(new Date(millis)) + ".png";
    }

    // ------------------------------------------------------------- send to all
    /** "Sendt til 2 af 3 – Bærbar fejlede: timeout". */
    static String allSummary(int total, List<String> failedNames, List<String> errors) {
        int ok = total - failedNames.size();
        StringBuilder text = new StringBuilder("Sendt til ").append(ok).append(" af ").append(total);
        List<String> parts = new ArrayList<>();
        for (int index = 0; index < failedNames.size(); index++) {
            String error = index < errors.size() ? errors.get(index) : "";
            parts.add(failedNames.get(index) + " fejlede" + (isBlank(error) ? "" : ": " + error.trim()));
        }
        if (!parts.isEmpty()) {
            text.append(" – ").append(String.join("; ", parts));
        }
        return text.toString();
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
