package com.h4xtor.share;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.Icon;
import android.os.Bundle;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Mirrors the phone's notifications to paired PCs (opt-in, see the settings page) and carries out
 * "reply" and "dismiss" taps coming back from the PC.
 */
public final class NotificationMirrorService extends NotificationListenerService {
    private static final int ICON_PIXELS = 64;
    private static final int MAX_TRACKED = 200;

    /** Notifications that were sent to a PC, by key – needed to reply to or dismiss them later. */
    private static final Map<String, StatusBarNotification> TRACKED = Collections.synchronizedMap(
            new LinkedHashMap<String, StatusBarNotification>() {
                @Override
                protected boolean removeEldestEntry(Entry<String, StatusBarNotification> eldest) {
                    return size() > MAX_TRACKED;
                }
            });
    private static final ShareLogic.DuplicateGate GATE = new ShareLogic.DuplicateGate(2_000L);
    private static final Map<String, String> ICONS = new java.util.concurrent.ConcurrentHashMap<>();
    private static volatile NotificationMirrorService instance;

    /** True when the user has given h4xtor share notification access in system settings. */
    public static boolean hasAccess(Context context) {
        String enabled = Settings.Secure.getString(context.getContentResolver(), "enabled_notification_listeners");
        if (enabled == null || enabled.isEmpty()) {
            return false;
        }
        for (String entry : enabled.split(":")) {
            ComponentName component = ComponentName.unflattenFromString(entry);
            if (component != null && context.getPackageName().equals(component.getPackageName())) {
                return true;
            }
        }
        return false;
    }

    @Override
    public void onListenerConnected() {
        instance = this;
    }

    @Override
    public void onListenerDisconnected() {
        if (instance == this) {
            instance = null;
        }
        TRACKED.clear();
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            handlePosted(sbn);
        } catch (Exception ignored) {
            // A broken notification must never take the listener down.
        }
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn == null) {
            return;
        }
        String key = sbn.getKey();
        GATE.forget(key);
        if (TRACKED.remove(key) == null) {
            return;
        }
        try {
            ShareService.pushToPeers(this, "notifications",
                    (client, peer) -> client.pushNotification(peer, ShareLogic.notificationRemoved(key)));
        } catch (Exception ignored) {
            // Best effort.
        }
    }

    private void handlePosted(StatusBarNotification sbn) throws Exception {
        if (sbn == null) {
            return;
        }
        AppIdentity identity = new AppIdentity(this);
        if (!identity.flag("mirror_notifications", false)) {
            return;
        }
        Notification notification = sbn.getNotification();
        String packageName = sbn.getPackageName();
        Bundle extras = notification.extras;
        String title = text(extras.getCharSequence(Notification.EXTRA_TITLE));
        CharSequence big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT);
        String body = text(big != null ? big : extras.getCharSequence(Notification.EXTRA_TEXT));
        int flags = notification.flags;
        boolean ongoing = (flags & Notification.FLAG_ONGOING_EVENT) != 0
                || (flags & Notification.FLAG_FOREGROUND_SERVICE) != 0;
        boolean summary = (flags & Notification.FLAG_GROUP_SUMMARY) != 0;
        if (!ShareLogic.shouldMirror(getPackageName().equals(packageName), ongoing, summary, title, body)
                || !ShareLogic.isAllowed(identity.mirrorApps(), packageName)
                || !GATE.accept(sbn.getKey(), title, body, System.currentTimeMillis())) {
            return;
        }
        boolean canReply = findReplyAction(notification) != null;
        JSONObject payload = ShareLogic.notificationPosted(
                sbn.getKey(), packageName, appLabel(packageName), title, body,
                sbn.getPostTime(), iconFor(packageName, notification), canReply, sbn.isClearable());
        TRACKED.put(sbn.getKey(), sbn);
        ShareService.pushToPeers(this, "notifications",
                (client, peer) -> client.pushNotification(peer, payload));
    }

    private static String text(CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }

    private String appLabel(String packageName) {
        try {
            PackageManager manager = getPackageManager();
            return manager.getApplicationLabel(manager.getApplicationInfo(packageName, 0)).toString();
        } catch (Exception error) {
            return packageName;
        }
    }

    /** Small icon as base64 PNG (64 px, at most 48 KB), or "" when it cannot be rendered. */
    private String iconFor(String packageName, Notification notification) {
        String cached = ICONS.get(packageName);
        if (cached != null) {
            return cached;
        }
        String result = "";
        try {
            Icon icon = notification.getSmallIcon();
            Drawable drawable = icon == null ? null : icon.loadDrawable(this);
            if (drawable != null) {
                Bitmap bitmap = Bitmap.createBitmap(ICON_PIXELS, ICON_PIXELS, Bitmap.Config.ARGB_8888);
                Canvas canvas = new Canvas(bitmap);
                drawable.setBounds(0, 0, ICON_PIXELS, ICON_PIXELS);
                drawable.draw(canvas);
                ByteArrayOutputStream png = new ByteArrayOutputStream();
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, png);
                bitmap.recycle();
                if (ShareLogic.iconFits(png.size())) {
                    result = Base64.encodeToString(png.toByteArray(), Base64.NO_WRAP);
                }
            }
        } catch (Exception ignored) {
            // No icon is fine; the PC shows a placeholder.
        }
        ICONS.put(packageName, result);
        return result;
    }

    private static Notification.Action findReplyAction(Notification notification) {
        if (notification.actions == null) {
            return null;
        }
        for (Notification.Action action : notification.actions) {
            RemoteInput[] inputs = action.getRemoteInputs();
            if (action.actionIntent != null && inputs != null && inputs.length > 0) {
                return action;
            }
        }
        return null;
    }

    // ------------------------------------------------------------ PC -> phone
    /** Reply to or dismiss a notification the PC saw. Throws HttpError 404/400 with a Danish reason. */
    static void perform(String key, String action, String reply) throws H4xtorServer.HttpError {
        NotificationMirrorService service = instance;
        StatusBarNotification sbn = key == null ? null : TRACKED.get(key);
        if (service == null || sbn == null) {
            throw new H4xtorServer.HttpError(404, "Notifikationen findes ikke længere på telefonen.");
        }
        if ("dismiss".equals(action)) {
            if (!sbn.isClearable()) {
                throw new H4xtorServer.HttpError(400, "Notifikationen kan ikke fjernes.");
            }
            service.cancelNotification(key);
            return;
        }
        if (!"reply".equals(action)) {
            throw new H4xtorServer.HttpError(400, "Ukendt handling.");
        }
        Notification.Action target = findReplyAction(sbn.getNotification());
        if (target == null) {
            throw new H4xtorServer.HttpError(400, "Man kan ikke svare på den notifikation.");
        }
        if (reply == null || reply.trim().isEmpty()) {
            throw new H4xtorServer.HttpError(400, "Skriv et svar først.");
        }
        RemoteInput[] inputs = target.getRemoteInputs();
        Bundle results = new Bundle();
        for (RemoteInput input : inputs) {
            results.putCharSequence(input.getResultKey(), reply);
        }
        Intent fill = new Intent();
        RemoteInput.addResultsToIntent(inputs, fill, results);
        try {
            target.actionIntent.send(service, 0, fill);
        } catch (PendingIntent.CanceledException error) {
            throw new H4xtorServer.HttpError(404, "Notifikationen kan ikke længere besvares.");
        }
    }
}
