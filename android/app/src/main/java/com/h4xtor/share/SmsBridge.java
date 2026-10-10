package com.h4xtor.share;

import android.Manifest;
import android.content.ContentResolver;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.ContentObserver;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.provider.ContactsContract;
import android.provider.Telephony;
import android.telephony.SmsManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;

/**
 * SMS for the PC: lists threads and messages, sends texts and reports new incoming messages.
 * Reads the system SMS provider only; nothing is ever written to it.
 */
final class SmsBridge {
    private static final String[] COLUMNS = {
            Telephony.Sms._ID, Telephony.Sms.THREAD_ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY,
            Telephony.Sms.DATE, Telephony.Sms.TYPE, Telephony.Sms.READ};
    private static final int THREAD_SCAN_ROWS = 3000;

    private final Context context;
    private final AppIdentity identity;
    private final Handler main;
    private final ExecutorService worker;
    private final Map<String, String> names = new HashMap<>();
    private ContentObserver observer;
    private long lastSeenId = -1;

    SmsBridge(Context context, AppIdentity identity, Handler main, ExecutorService worker) {
        this.context = context;
        this.identity = identity;
        this.main = main;
        this.worker = worker;
    }

    boolean enabled() {
        return identity.flag("sms_enabled", false);
    }

    boolean canRead() {
        return granted(Manifest.permission.READ_SMS);
    }

    boolean canSend() {
        return granted(Manifest.permission.SEND_SMS);
    }

    private boolean granted(String permission) {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    private void require(boolean needsSend) throws H4xtorServer.HttpError {
        if (!enabled()) {
            throw new H4xtorServer.HttpError(403, "SMS er slået fra på telefonen.");
        }
        if (!canRead() || (needsSend && !canSend())) {
            throw new H4xtorServer.HttpError(403,
                    "SMS-adgang mangler på telefonen. Slå SMS til i h4xtor share og tillad adgangen.");
        }
    }

    // --------------------------------------------------------------- queries
    JSONObject threads(int requestedLimit) throws Exception {
        require(false);
        int limit = ShareLogic.limit(requestedLimit, 50, 200);
        Map<String, Object[]> byThread = new java.util.LinkedHashMap<>();
        Map<String, Integer> unread = new HashMap<>();
        try (Cursor cursor = context.getContentResolver().query(
                Telephony.Sms.CONTENT_URI, COLUMNS, null, null, "date DESC")) {
            int rows = 0;
            while (cursor != null && cursor.moveToNext() && rows++ < THREAD_SCAN_ROWS) {
                String thread = cursor.getString(1);
                if (thread == null || cursor.getInt(5) == ShareLogic.SMS_TYPE_DRAFT) {
                    continue;
                }
                if (cursor.getInt(5) == ShareLogic.SMS_TYPE_INBOX && cursor.getInt(6) == 0) {
                    unread.merge(thread, 1, Integer::sum);
                }
                if (!byThread.containsKey(thread) && byThread.size() < limit) {
                    byThread.put(thread, new Object[]{cursor.getString(2), cursor.getString(3), cursor.getLong(4)});
                }
            }
        }
        JSONArray array = new JSONArray();
        for (Map.Entry<String, Object[]> entry : byThread.entrySet()) {
            Object[] row = entry.getValue();
            String address = row[0] == null ? "" : (String) row[0];
            array.put(ShareLogic.smsThread(entry.getKey(), address, nameFor(address),
                    row[1] == null ? "" : (String) row[1], (Long) row[2],
                    unread.getOrDefault(entry.getKey(), 0)));
        }
        return new JSONObject().put("threads", array);
    }

    JSONObject messages(String threadId, int requestedLimit) throws Exception {
        require(false);
        if (threadId == null || !threadId.matches("[0-9]{1,18}")) {
            throw new H4xtorServer.HttpError(400, "Ugyldig samtale.");
        }
        int limit = ShareLogic.limit(requestedLimit, 100, 500);
        List<JSONObject> rows = new ArrayList<>();
        try (Cursor cursor = context.getContentResolver().query(
                Telephony.Sms.CONTENT_URI, COLUMNS, Telephony.Sms.THREAD_ID + " = ?",
                new String[]{threadId}, "date DESC")) {
            while (cursor != null && cursor.moveToNext() && rows.size() < limit) {
                int type = cursor.getInt(5);
                if (type == ShareLogic.SMS_TYPE_DRAFT) {
                    continue;
                }
                rows.add(ShareLogic.smsMessage(cursor.getString(0), cursor.getString(2), cursor.getString(3),
                        cursor.getLong(4), ShareLogic.isOutgoing(type)));
            }
        }
        Collections.reverse(rows); // oldest first
        JSONArray array = new JSONArray();
        for (JSONObject row : rows) {
            array.put(row);
        }
        return new JSONObject().put("messages", array);
    }

    // ------------------------------------------------------------------ send
    JSONObject send(String address, String text) throws Exception {
        require(true);
        String number = address == null ? "" : address.trim();
        if (!ShareLogic.validPhoneNumber(number)) {
            throw new H4xtorServer.HttpError(400, "Ugyldigt telefonnummer.");
        }
        if (text == null || text.trim().isEmpty() || text.length() > ShareLogic.SMS_MAX_CHARS) {
            throw new H4xtorServer.HttpError(400, "Beskeden er tom eller for lang.");
        }
        SmsManager manager = smsManager();
        if (manager == null) {
            throw new H4xtorServer.HttpError(400, "Telefonen kan ikke sende SMS.");
        }
        ArrayList<String> parts = manager.divideMessage(text);
        if (parts.size() > 1) {
            manager.sendMultipartTextMessage(number, null, parts, null, null);
        } else {
            manager.sendTextMessage(number, null, text, null, null);
        }
        return new JSONObject().put("ok", true);
    }

    @SuppressWarnings("deprecation")
    private SmsManager smsManager() {
        return Build.VERSION.SDK_INT >= 31
                ? context.getSystemService(SmsManager.class)
                : SmsManager.getDefault();
    }

    // ---------------------------------------------------------------- contacts
    private String nameFor(String address) {
        if (address == null || address.isEmpty() || !granted(Manifest.permission.READ_CONTACTS)) {
            return "";
        }
        synchronized (names) {
            String cached = names.get(address);
            if (cached != null) {
                return cached;
            }
        }
        String name = "";
        Uri lookup = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(address));
        try (Cursor cursor = context.getContentResolver().query(
                lookup, new String[]{ContactsContract.PhoneLookup.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) {
                name = cursor.getString(0);
            }
        } catch (Exception ignored) {
            // Contacts unavailable: the number is shown instead.
        }
        synchronized (names) {
            if (names.size() > 500) {
                names.clear();
            }
            names.put(address, name);
        }
        return name;
    }

    // ---------------------------------------------------------------- incoming
    /** Start or stop watching for new messages to match the flag and the permission. */
    synchronized void syncObserver() {
        boolean wanted = enabled() && canRead();
        if (wanted && observer == null) {
            lastSeenId = newestInboxId();
            observer = new ContentObserver(main) {
                @Override
                public void onChange(boolean selfChange) {
                    main.removeCallbacks(check);
                    main.postDelayed(check, 800);
                }
            };
            context.getContentResolver().registerContentObserver(Telephony.Sms.CONTENT_URI, true, observer);
        } else if (!wanted && observer != null) {
            stop();
        }
    }

    synchronized void stop() {
        if (observer != null) {
            context.getContentResolver().unregisterContentObserver(observer);
            observer = null;
            main.removeCallbacks(check);
        }
    }

    private final Runnable check = this::queueCheck;

    private void queueCheck() {
        worker.execute(this::reportNewMessages);
    }

    private long newestInboxId() {
        try (Cursor cursor = context.getContentResolver().query(Telephony.Sms.Inbox.CONTENT_URI,
                new String[]{Telephony.Sms._ID}, null, null, "_id DESC")) {
            return cursor != null && cursor.moveToFirst() ? cursor.getLong(0) : 0;
        } catch (Exception error) {
            return 0;
        }
    }

    private void reportNewMessages() {
        if (!enabled() || !canRead()) {
            return;
        }
        long after;
        synchronized (this) {
            after = lastSeenId;
        }
        List<JSONObject> fresh = new ArrayList<>();
        long newest = after;
        ContentResolver resolver = context.getContentResolver();
        try (Cursor cursor = resolver.query(Telephony.Sms.Inbox.CONTENT_URI, COLUMNS,
                Telephony.Sms._ID + " > ?", new String[]{Long.toString(after)}, "_id ASC")) {
            while (cursor != null && cursor.moveToNext() && fresh.size() < 20) {
                newest = Math.max(newest, cursor.getLong(0));
                String address = cursor.getString(2) == null ? "" : cursor.getString(2);
                fresh.add(ShareLogic.smsIncoming(cursor.getString(1), address, nameFor(address),
                        cursor.getString(3), cursor.getLong(4)));
            }
        } catch (Exception error) {
            return; // permission revoked or provider busy
        }
        synchronized (this) {
            lastSeenId = Math.max(lastSeenId, newest);
        }
        for (JSONObject payload : fresh) {
            ShareService.pushToPeers(context, "sms",
                    (client, peer) -> client.pushIncomingSms(peer, payload));
        }
    }

    /** Permissions the settings page asks for. */
    static String[] permissions() {
        return new String[]{Manifest.permission.READ_SMS, Manifest.permission.SEND_SMS,
                Manifest.permission.READ_CONTACTS};
    }
}
