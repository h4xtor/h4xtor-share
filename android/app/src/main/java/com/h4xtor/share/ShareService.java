package com.h4xtor.share;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;

import org.json.JSONObject;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * The heart of the Android app. Runs as a foreground service so files, links
 * and clipboard text keep arriving while the app is in the background. The
 * activities are thin views on top of this service.
 */
public final class ShareService extends Service implements H4xtorServer.Listener,
        DiscoveryController.Listener, UdpDiscovery.Listener {

    public interface UiListener {
        void onStateChanged();
        void onMessage(String text, boolean error);
        void onPairingCode(String peerName, String code, long expiresAt);
        void onNeedCode(Peer peer, String pairingId);
        void onLinkReceived(String peerName, String url);
        void onStopped();
    }

    public interface ServiceAction {
        void run(ShareService service);
    }

    public static final String ACTION_STOP = "com.h4xtor.share.STOP";
    public static final String ACTION_START = "com.h4xtor.share.START";
    /** Carries shared URIs so their read grant lives as long as the service. */
    public static final String ACTION_HOLD = "com.h4xtor.share.HOLD";

    private static final String CHANNEL_SERVICE = "h4xtor_service";
    private static final String CHANNEL_TRANSFERS = "h4xtor_transfers";
    private static final String CHANNEL_EVENTS = "h4xtor_events";
    private static final int NOTIFICATION_SERVICE = 1;
    private static final int NOTIFICATION_TRANSFERS = 2;
    private static final int CLIPBOARD_SUPPRESS_MS = 3000;

    private static volatile ShareService instance;
    private static final List<ServiceAction> pending = new CopyOnWriteArrayList<>();

    public static final class TransferItem {
        public final String id;
        public final String name;
        public final boolean outgoing;
        public final boolean folder;
        public final String peerName;
        public volatile long sent;
        public volatile long total;
        public volatile double speed;
        public volatile String status = "active";
        public volatile String uri = "";
        public volatile String error = "";
        final long created = System.currentTimeMillis();
        long lastTime = SystemClock.elapsedRealtime();
        long lastSent;
        H4xtorClient.CancelToken cancel;
        Runnable retry;
        public volatile long startedAt = SystemClock.elapsedRealtime();
        public volatile long finishedAt;
        public volatile double peakSpeed;
        private final float[] ring = new float[48];
        private int ringCount;
        private int ringPos;

        synchronized void addSample(float value) {
            ring[ringPos] = value;
            ringPos = (ringPos + 1) % ring.length;
            ringCount = Math.min(ring.length, ringCount + 1);
        }

        /** Speed samples, oldest first (bytes per second). */
        public synchronized float[] samples() {
            float[] out = new float[ringCount];
            int start = ringCount < ring.length ? 0 : ringPos;
            for (int index = 0; index < ringCount; index++) {
                out[index] = ring[(start + index) % ring.length];
            }
            return out;
        }

        /** Seconds the transfer took (or has taken so far). */
        public double seconds() {
            long end = finishedAt > 0 ? finishedAt : SystemClock.elapsedRealtime();
            return Math.max(0.001, (end - startedAt) / 1000.0);
        }

        public double averageSpeed() {
            return total <= 0 ? 0 : (double) Math.min(sent, total) / seconds();
        }

        TransferItem(String id, String name, boolean outgoing, boolean folder, String peerName) {
            this.id = id;
            this.name = name;
            this.outgoing = outgoing;
            this.folder = folder;
            this.peerName = peerName;
        }

        public double fraction() {
            return total <= 0 ? 1.0 : Math.min(1.0, (double) sent / (double) total);
        }
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newFixedThreadPool(48);
    private final ExecutorService transfersExecutor = Executors.newFixedThreadPool(3);
    private final Map<String, Peer> peers = new ConcurrentHashMap<>();
    private final Map<String, Long> rtt = new ConcurrentHashMap<>();
    private final Map<String, Boolean> online = new ConcurrentHashMap<>();
    private final Map<String, Integer> misses = new ConcurrentHashMap<>();
    private final Map<String, TransferItem> transfers = Collections.synchronizedMap(new LinkedHashMap<>());
    private final List<UiListener> listeners = new CopyOnWriteArrayList<>();
    private final AtomicBoolean scanning = new AtomicBoolean(false);
    private final AtomicInteger scanDone = new AtomicInteger(0);
    private volatile int scanTotal = 0;

    private AppIdentity identity;
    private H4xtorClient client;
    private H4xtorServer server;
    private DiscoveryController discovery;
    private UdpDiscovery udp;
    private WifiDirectController wifiDirect;
    private NotificationManager notifications;
    private ClipboardManager clipboard;
    private ClipboardManager.OnPrimaryClipChangedListener clipListener;
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private String clipboardObserved = "";
    /** Copied while no PC was online: sent as soon as one shows up (for a short while). */
    private String pendingCopy;
    private long pendingCopyUntil = 0L;
    private String clipboardSuppress = "";
    private long clipboardSuppressUntil = 0L;
    private boolean foregroundUi = false;
    private long lastProgressNotify = 0L;
    private String status = "Starter…";
    private String qrSecret;

    // ------------------------------------------------------------- access
    public static ShareService get() {
        return instance;
    }

    /** Run {@code action} on the service, starting it first when needed. */
    public static void with(Context context, ServiceAction action) {
        ShareService current = instance;
        if (current != null) {
            current.main.post(() -> action.run(current));
            return;
        }
        pending.add(action);
        start(context);
    }

    public static void start(Context context) {
        Intent intent = new Intent(context, ShareService.class).setAction(ACTION_START);
        context.startForegroundService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        identity = new AppIdentity(this);
        client = new H4xtorClient(this, identity);
        server = new H4xtorServer(this, identity, this);
        discovery = new DiscoveryController(this, identity, this);
        udp = new UdpDiscovery(identity, this, this::knownAddresses);
        wifiDirect = new WifiDirectController(this, identity);
        notifications = getSystemService(NotificationManager.class);
        clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        createChannels();
        startForegroundCompat();
        for (Peer peer : identity.knownPeers()) {
            peers.put(peer.deviceId, peer);
        }
        instance = this;
        network.execute(() -> {
            try {
                server.start();
                status = "Online";
            } catch (Exception error) {
                status = "Kunne ikke starte: " + H4xtorClient.safeMessage(error);
            }
            main.post(() -> {
                discovery.start();
                udp.start();
                changed();
                updateServiceNotification();
            });
        });
        registerClipboard();
        try {
            startScreenshotWatcher();
        } catch (Exception ignored) {
            // Missing media permission: the setting shows how to fix it.
        }
        main.postDelayed(healthTick, 800);
        for (ServiceAction action : pending) {
            pending.remove(action);
            main.post(() -> action.run(this));
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForegroundCompat();
        if (intent != null) {
            identity.setFlag("stopped_by_user", ACTION_STOP.equals(intent.getAction()));
        }
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            for (UiListener listener : listeners) {
                listener.onStopped();
            }
            listeners.clear();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            return START_NOT_STICKY;
        }
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        instance = null;
        main.removeCallbacksAndMessages(null);
        if (screenshotObserver != null) {
            getContentResolver().unregisterContentObserver(screenshotObserver);
        }
        if (clipListener != null) {
            try {
                clipboard.removePrimaryClipChangedListener(clipListener);
            } catch (Exception ignored) {
                // Already removed.
            }
        }
        discovery.stop();
        udp.stop();
        server.stop();
        if (wifiDirect.isActive()) {
            wifiDirect.stop(new WifiDirectController.Callback() {
                @Override public void onGroupStarted(String ssid, String passphrase) { }
                @Override public void onGroupFailed(String reason) { }
                @Override public void onGroupStopped() { }
            });
        }
        releaseLocks();
        network.shutdownNow();
        transfersExecutor.shutdownNow();
        super.onDestroy();
    }

    // ---------------------------------------------------------- notifications
    private void createChannels() {
        NotificationChannel service = new NotificationChannel(
                CHANNEL_SERVICE, "Kører i baggrunden", NotificationManager.IMPORTANCE_MIN);
        service.setDescription("Holder h4xtor share klar til at modtage");
        service.setShowBadge(false);
        NotificationChannel transfer = new NotificationChannel(
                CHANNEL_TRANSFERS, "Overførsler", NotificationManager.IMPORTANCE_LOW);
        transfer.setShowBadge(false);
        NotificationChannel events = new NotificationChannel(
                CHANNEL_EVENTS, "Modtaget og parring", NotificationManager.IMPORTANCE_HIGH);
        events.setDescription("Filer, links og parringskoder fra dine enheder");
        notifications.createNotificationChannel(service);
        notifications.createNotificationChannel(transfer);
        notifications.createNotificationChannel(events);
    }

    private PendingIntent openAppIntent() {
        Intent intent = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(this, 1, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private Notification buildServiceNotification() {
        int count = 0;
        for (Peer peer : peers.values()) {
            if (identity.isOutboundTrusted(peer.deviceId) && Boolean.TRUE.equals(online.get(peer.deviceId))) {
                count++;
            }
        }
        String text = count == 0
                ? "Klar til at modtage fra dine enheder"
                : count == 1 ? "Forbundet til 1 enhed" : "Forbundet til " + count + " enheder";
        if (wifiDirect != null && wifiDirect.isActive()) {
            text = text + " · Wi-Fi Direct aktiv";
        }
        PendingIntent clip = PendingIntent.getActivity(this, 2,
                new Intent(this, ClipboardSendActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 3,
                new Intent(this, ShareService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL_SERVICE)
                .setSmallIcon(R.drawable.ic_stat_share)
                .setContentTitle("h4xtor share")
                .setContentText(text)
                .setOngoing(true)
                .setShowWhen(false)
                .setColor(Ui.ACCENT_LIGHT)
                .setContentIntent(openAppIntent())
                .addAction(new Notification.Action.Builder(null, "Send udklipsholder", clip).build())
                .addAction(new Notification.Action.Builder(null, "Stop", stop).build())
                .build();
    }

    private void startForegroundCompat() {
        Notification notification = buildServiceNotification();
        try {
            startForeground(NOTIFICATION_SERVICE, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        } catch (Exception error) {
            // Android refused a foreground start (e.g. from the background); keep running quietly.
        }
    }

    private void updateServiceNotification() {
        try {
            notifications.notify(NOTIFICATION_SERVICE, buildServiceNotification());
        } catch (Exception ignored) {
            // Notifications may be disabled.
        }
    }

    private void notifyEvent(int id, String title, String text, PendingIntent intent) {
        try {
            Notification.Builder builder = new Notification.Builder(this, CHANNEL_EVENTS)
                    .setSmallIcon(R.drawable.ic_stat_share)
                    .setContentTitle(title)
                    .setContentText(text)
                    .setStyle(new Notification.BigTextStyle().bigText(text))
                    .setColor(Ui.ACCENT_LIGHT)
                    .setAutoCancel(true)
                    .setContentIntent(intent == null ? openAppIntent() : intent);
            notifications.notify(id, builder.build());
        } catch (Exception ignored) {
            // Notifications may be disabled.
        }
    }

    private void updateTransferNotification(boolean force) {
        long now = SystemClock.elapsedRealtime();
        if (!force && now - lastProgressNotify < 700) {
            return;
        }
        lastProgressNotify = now;
        List<TransferItem> active = new ArrayList<>();
        synchronized (transfers) {
            for (TransferItem item : transfers.values()) {
                if ("active".equals(item.status)) {
                    active.add(item);
                }
            }
        }
        if (active.isEmpty()) {
            notifications.cancel(NOTIFICATION_TRANSFERS);
            releaseLocks();
            return;
        }
        acquireLocks();
        long sent = 0;
        long total = 0;
        for (TransferItem item : active) {
            sent += item.sent;
            total += item.total;
        }
        int percent = total <= 0 ? 0 : (int) Math.min(100, sent * 100 / total);
        TransferItem first = active.get(0);
        String title = active.size() == 1
                ? (first.outgoing ? "Sender " : "Modtager ") + first.name
                : active.size() + " overførsler i gang";
        String text = percent + "%  ·  " + Ui.formatBytes(sent) + " af " + Ui.formatBytes(total);
        try {
            notifications.notify(NOTIFICATION_TRANSFERS, new Notification.Builder(this, CHANNEL_TRANSFERS)
                    .setSmallIcon(R.drawable.ic_stat_share)
                    .setContentTitle(title)
                    .setContentText(text)
                    .setOngoing(true)
                    .setOnlyAlertOnce(true)
                    .setColor(Ui.ACCENT_LIGHT)
                    .setProgress(100, percent, total <= 0)
                    .setContentIntent(openAppIntent())
                    .build());
        } catch (Exception ignored) {
            // Notifications may be disabled.
        }
    }

    @SuppressWarnings("deprecation")
    private void acquireLocks() {
        try {
            if (wakeLock == null) {
                PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
                wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "h4xtor:transfer");
                wakeLock.setReferenceCounted(false);
            }
            if (!wakeLock.isHeld()) {
                wakeLock.acquire(60 * 60 * 1000L);
            }
            if (wifiLock == null) {
                WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "h4xtor:transfer");
                wifiLock.setReferenceCounted(false);
            }
            if (!wifiLock.isHeld()) {
                wifiLock.acquire();
            }
        } catch (Exception ignored) {
            // Locks are an optimisation only.
        }
    }

    private void releaseLocks() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
            if (wifiLock != null && wifiLock.isHeld()) {
                wifiLock.release();
            }
        } catch (Exception ignored) {
            // Already released.
        }
    }

    // ---------------------------------------------------------------- ui glue
    public void addListener(UiListener listener) {
        listeners.add(listener);
        foregroundUi = true;
        healthLoop();
    }

    public void removeListener(UiListener listener) {
        listeners.remove(listener);
        foregroundUi = !listeners.isEmpty();
    }

    private final Runnable notifyChanged = () -> {
        if (pendingCopy != null) {
            if (SystemClock.elapsedRealtime() > pendingCopyUntil || sendClipboardToOnline(pendingCopy) > 0) {
                pendingCopy = null;
            }
        }
        for (UiListener listener : listeners) {
            listener.onStateChanged();
        }
    };

    private void changed() {
        main.removeCallbacks(notifyChanged);
        main.postDelayed(notifyChanged, 120);
    }

    private void message(String text, boolean error) {
        main.post(() -> {
            if (listeners.isEmpty()) {
                return;
            }
            for (UiListener listener : listeners) {
                listener.onMessage(text, error);
            }
        });
    }

    public AppIdentity identity() {
        return identity;
    }

    public String status() {
        return status;
    }

    public boolean isScanning() {
        return scanning.get();
    }

    public float scanProgress() {
        return scanTotal <= 0 ? 0f : (float) scanDone.get() / (float) scanTotal;
    }

    public List<Peer> peers() {
        List<Peer> list = new ArrayList<>(peers.values());
        list.sort(Comparator
                .comparing((Peer peer) -> identity.isOutboundTrusted(peer.deviceId) ? 0 : 1)
                .thenComparing(peer -> isOnline(peer.deviceId) ? 0 : 1)
                .thenComparing(peer -> peer.name.toLowerCase(Locale.ROOT)));
        return list;
    }

    public List<Peer> pairedPeers() {
        List<Peer> result = new ArrayList<>();
        for (Peer peer : peers()) {
            if (identity.isOutboundTrusted(peer.deviceId)) {
                result.add(peer);
            }
        }
        return result;
    }

    public Peer peer(String id) {
        return id == null ? null : peers.get(id);
    }

    public boolean isOnline(String id) {
        return Boolean.TRUE.equals(online.get(id));
    }

    public long rtt(String id) {
        Long value = rtt.get(id);
        return value == null ? -1 : value;
    }

    public List<TransferItem> transfers() {
        List<TransferItem> list;
        synchronized (transfers) {
            list = new ArrayList<>(transfers.values());
        }
        Collections.reverse(list);
        return list;
    }

    public int activeTransfers() {
        int count = 0;
        synchronized (transfers) {
            for (TransferItem item : transfers.values()) {
                if ("active".equals(item.status)) {
                    count++;
                }
            }
        }
        return count;
    }

    public void clearFinished() {
        synchronized (transfers) {
            transfers.values().removeIf(item -> !"active".equals(item.status));
        }
        changed();
    }

    public WifiDirectController wifiDirect() {
        return wifiDirect;
    }

    public List<String> localAddresses() {
        List<String> result = new ArrayList<>();
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            if (interfaces == null) {
                return result;
            }
            for (NetworkInterface networkInterface : Collections.list(interfaces)) {
                if (!networkInterface.isUp() || networkInterface.isLoopback()) {
                    continue;
                }
                for (InetAddress address : Collections.list(networkInterface.getInetAddresses())) {
                    if (address instanceof Inet4Address && address.isSiteLocalAddress()) {
                        result.add(address.getHostAddress());
                    }
                }
            }
        } catch (Exception ignored) {
            // No network.
        }
        result.sort(Comparator.comparing(value -> value.startsWith("192.168.49.") ? 0
                : value.startsWith("192.168.") ? 1 : 2));
        return result;
    }

    private List<String> knownAddresses() {
        List<String> result = new ArrayList<>();
        for (Peer peer : identity.knownPeers()) {
            result.add(peer.address);
        }
        return result;
    }

    public PairingInvite newInvite() {
        server.revokeQrSecret(qrSecret);
        qrSecret = server.createQrSecret();
        List<String> addresses = localAddresses();
        if (addresses.size() > 3) {
            addresses = addresses.subList(0, 3);
        }
        try {
            return new PairingInvite(identity.deviceId(), identity.deviceName(), identity.fingerprint(),
                    AppIdentity.PORT, addresses, qrSecret, "android");
        } catch (Exception error) {
            return null;
        }
    }

    public void revokeInvite() {
        server.revokeQrSecret(qrSecret);
        qrSecret = null;
    }

    // ------------------------------------------------------------- discovery
    private final Runnable healthTick = this::healthLoop;

    private void healthLoop() {
        checkHealth();
        main.removeCallbacks(healthTick);
        main.postDelayed(healthTick, foregroundUi ? 4_000 : 30_000);
    }

    private void checkHealth() {
        for (Peer peer : new ArrayList<>(peers.values())) {
            network.execute(() -> {
                boolean isUp;
                long time;
                try {
                    time = client.ping(peer, 2_000);
                    isUp = true;
                } catch (Exception error) {
                    time = -1;
                    isUp = false;
                }
                if (!peers.containsKey(peer.deviceId)) {
                    return;
                }
                if (isUp) {
                    misses.remove(peer.deviceId);
                } else if (!identity.isOutboundTrusted(peer.deviceId)) {
                    int count = misses.getOrDefault(peer.deviceId, 0) + 1;
                    misses.put(peer.deviceId, count);
                    if (count >= 3) {
                        // Unpaired devices that stopped answering simply disappear.
                        dropPeer(peer.deviceId);
                        changed();
                        return;
                    }
                }
                Boolean previous = online.put(peer.deviceId, isUp);
                rtt.put(peer.deviceId, time);
                if (previous == null || previous != isUp) {
                    if (isUp) {
                        recordDevice(peer);
                    }
                    main.post(this::updateServiceNotification);
                }
                changed();
            });
        }
    }

    private void recordDevice(Peer peer) {
        try {
            identity.appendHistory("devices", new JSONObject()
                    .put("name", peer.name)
                    .put("ip", peer.address)
                    .put("os", peer.platform)
                    .put("online", true)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    private void dropPeer(String peerId) {
        peers.remove(peerId);
        online.remove(peerId);
        rtt.remove(peerId);
        misses.remove(peerId);
    }

    private void upsert(Peer peer) {
        upsert(peer, false);
    }

    private synchronized void upsert(Peer peer, boolean explicit) {
        if (peer == null || identity.deviceId().equals(peer.deviceId)) {
            return;
        }
        boolean trusted = identity.isOutboundTrusted(peer.deviceId);
        if (explicit) {
            identity.unhidePeer(peer.deviceId);
        } else if (!trusted && identity.hiddenPeers().contains(peer.deviceId)) {
            return;
        }
        // One address = one device: drop stale records (reinstalled app, old cache).
        for (Peer other : new ArrayList<>(peers.values())) {
            if (other.deviceId.equals(peer.deviceId) || !other.address.equals(peer.address)
                    || other.port != peer.port) {
                continue;
            }
            if (!identity.isOutboundTrusted(other.deviceId)) {
                dropPeer(other.deviceId);
            } else if (!trusted && isOnline(other.deviceId)) {
                return;
            }
        }
        Peer existing = peers.get(peer.deviceId);
        final Peer merged = existing != null && !existing.address.equals(peer.address)
                && isOnline(peer.deviceId) && "wifi-direct".equals(existing.transport)
                ? existing
                : existing == null ? peer : existing.mergedWith(peer);
        peers.put(peer.deviceId, merged);
        if (identity.isOutboundTrusted(peer.deviceId)) {
            identity.remember(merged);
        }
        if (existing == null || !existing.address.equals(merged.address)) {
            network.execute(() -> {
                try {
                    long time = client.ping(merged, 2_000);
                    online.put(merged.deviceId, true);
                    rtt.put(merged.deviceId, time);
                } catch (Exception ignored) {
                    online.put(merged.deviceId, false);
                }
                changed();
            });
        }
        changed();
    }

    public void probe(String address, int port, boolean reportErrors) {
        network.execute(() -> {
            try {
                upsert(client.getInfo(address, port, 2_500), reportErrors);
            } catch (Exception error) {
                if (reportErrors) {
                    message("Fandt ingen h4xtor share på " + address, true);
                }
            }
        });
    }

    public void restartDiscovery() {
        discovery.stop();
        discovery.start();
        udp.announceNow();
    }

    public void scanLan() {
        if (!scanning.compareAndSet(false, true)) {
            return;
        }
        network.execute(() -> {
            Set<String> targets = new LinkedHashSet<>();
            for (String own : localAddresses()) {
                String[] parts = own.split("\\.");
                if (parts.length != 4) {
                    continue;
                }
                String prefix = parts[0] + "." + parts[1] + "." + parts[2] + ".";
                for (int host = 1; host <= 254; host++) {
                    String candidate = prefix + host;
                    if (!candidate.equals(own)) {
                        targets.add(candidate);
                    }
                }
            }
            if (targets.isEmpty()) {
                scanning.set(false);
                message("Ingen Wi-Fi-forbindelse at scanne", true);
                return;
            }
            scanTotal = targets.size();
            scanDone.set(0);
            changed();
            for (String address : targets) {
                network.execute(() -> {
                    try {
                        upsert(client.getInfo(address, AppIdentity.PORT, 650));
                    } catch (Exception ignored) {
                        // Most addresses are not h4xtor share.
                    } finally {
                        int done = scanDone.incrementAndGet();
                        if (done >= scanTotal) {
                            scanning.set(false);
                            message("Scanning færdig", false);
                        }
                        if (done % 20 == 0 || done >= scanTotal) {
                            changed();
                        }
                    }
                });
            }
        });
    }

    @Override
    public void onPeerAddress(String address, int port) {
        probe(address, port, false);
    }

    @Override
    public void onAnnouncement(Peer peer) {
        upsert(peer);
    }

    @Override
    public void onStatus(String text) {
        status = text;
        changed();
    }

    // ---------------------------------------------------------------- pairing
    public void pair(Peer peer) {
        network.execute(() -> {
            try {
                JSONObject response = client.requestPairing(peer);
                String pairingId = response.getString("pairing_id");
                main.post(() -> {
                    for (UiListener listener : listeners) {
                        listener.onNeedCode(peer, pairingId);
                    }
                });
            } catch (Exception error) {
                message("Kunne ikke forbinde: " + H4xtorClient.safeMessage(error), true);
            }
        });
    }

    public void confirmPairing(Peer peer, String pairingId, String code) {
        network.execute(() -> {
            try {
                client.confirmPairing(peer, pairingId, code);
                upsert(peer, true);
                message("Forbundet med " + peer.name, false);
                main.post(this::updateServiceNotification);
            } catch (Exception error) {
                message("Parring fejlede: " + H4xtorClient.safeMessage(error), true);
            }
        });
    }

    public void pairWithInvite(String text) {
        final PairingInvite invite;
        try {
            invite = PairingInvite.parse(text);
        } catch (Exception error) {
            message(H4xtorClient.safeMessage(error), true);
            return;
        }
        message("Forbinder til " + invite.name + "…", false);
        network.execute(() -> {
            try {
                Peer peer = client.pairWithInvite(invite);
                upsert(peer, true);
                message("Forbundet med " + peer.name + " ✓", false);
                main.post(this::updateServiceNotification);
            } catch (Exception error) {
                message(H4xtorClient.safeMessage(error), true);
            }
        });
    }

    public void rejectPairing(String code) {
        server.rejectPairing(code);
    }

    /** Remove a device from the list. Paired devices are unpaired on both sides. */
    public void remove(Peer peer) {
        if (identity.isOutboundTrusted(peer.deviceId)) {
            forget(peer);
            return;
        }
        identity.hidePeer(peer.deviceId);
        dropPeer(peer.deviceId);
        message(peer.name + " er fjernet fra listen", false);
        changed();
    }

    public void forget(Peer peer) {
        network.execute(() -> {
            client.unpair(peer);
            dropPeer(peer.deviceId);
            message(peer.name + " er glemt", false);
            changed();
            main.post(this::updateServiceNotification);
        });
    }

    @Override
    public void onPairingCode(String peerName, String code, long expiresAt) {
        main.post(() -> {
            if (!listeners.isEmpty()) {
                for (UiListener listener : listeners) {
                    listener.onPairingCode(peerName, code, expiresAt);
                }
            } else {
                notifyEvent(100, peerName + " vil forbinde",
                        "Kode: " + code.substring(0, 3) + " " + code.substring(3)
                                + " – skriv den på " + peerName + ".", null);
            }
        });
    }

    @Override
    public void onPeerPaired(Peer peer) {
        upsert(peer, true);
        notifications.cancel(100);
        message("Forbundet med " + peer.name + " ✓", false);
        main.post(() -> {
            updateServiceNotification();
            for (UiListener listener : listeners) {
                listener.onStateChanged();
            }
        });
    }

    @Override
    public void onPeerForgotten(String peerId, String peerName) {
        peers.remove(peerId);
        online.remove(peerId);
        message(peerName + " har afbrudt forbindelsen", false);
        changed();
    }

    // ------------------------------------------------------------ nerd stats
    private void finished(TransferItem item) {
        item.finishedAt = SystemClock.elapsedRealtime();
        if (item.total > 0) {
            addStat(item.outgoing ? "stat_sent_bytes" : "stat_received_bytes", item.total);
            addStat(item.outgoing ? "stat_sent_count" : "stat_received_count", 1);
            double average = item.averageSpeed();
            double best = Math.max(item.peakSpeed, average);
            if (best > stat("stat_top_speed")) {
                identity.setString("stat_top_speed", Long.toString((long) best));
            }
            addStat("stat_seconds_ms", (long) (item.seconds() * 1000));
        }
        if (identity.flag("vibrate_done", true)) {
            main.post(this::buzz);
        }
    }

    private void addStat(String key, long delta) {
        identity.setString(key, Long.toString(stat(key) + delta));
    }

    public long stat(String key) {
        try {
            return Long.parseLong(identity.string(key, "0"));
        } catch (NumberFormatException error) {
            return 0;
        }
    }

    public void resetStats() {
        for (String key : new String[]{"stat_sent_bytes", "stat_received_bytes", "stat_sent_count",
                "stat_received_count", "stat_top_speed", "stat_seconds_ms"}) {
            identity.setString(key, "0");
        }
        changed();
    }

    private void buzz() {
        try {
            android.os.Vibrator vibrator = getSystemService(android.os.Vibrator.class);
            if (vibrator != null && vibrator.hasVibrator()) {
                vibrator.vibrate(android.os.VibrationEffect.createWaveform(new long[]{0, 35, 70, 35}, -1));
            }
        } catch (Exception ignored) {
            // Vibration is a nicety only.
        }
    }

    public interface SpeedTestListener {
        void onProgress(long sent, long total, double bytesPerSecond);

        void onDone(double uploadBytesPerSecond, long pingMs);

        void onFailed(String reason);
    }

    /** Ping + upload 32 MB of throw-away data to the PC; nothing is saved there. */
    public H4xtorClient.CancelToken speedTest(Peer peer, SpeedTestListener listener) {
        H4xtorClient.CancelToken cancel = new H4xtorClient.CancelToken();
        network.execute(() -> {
            try {
                long best = Long.MAX_VALUE;
                for (int round = 0; round < 3; round++) {
                    best = Math.min(best, client.ping(peer, 3000));
                }
                final long ping = best;
                long started = SystemClock.elapsedRealtime();
                double speed = client.speedTest(peer, 32L * 1024 * 1024, (sent, total) -> {
                    double seconds = Math.max(0.001, (SystemClock.elapsedRealtime() - started) / 1000.0);
                    main.post(() -> listener.onProgress(sent, total, sent / seconds));
                }, cancel);
                if (speed > stat("stat_top_speed")) {
                    identity.setString("stat_top_speed", Long.toString((long) speed));
                }
                main.post(() -> listener.onDone(speed, ping));
            } catch (H4xtorClient.CancelledException error) {
                main.post(() -> listener.onFailed("Annulleret"));
            } catch (Exception error) {
                String reason = H4xtorClient.safeMessage(error);
                main.post(() -> listener.onFailed(reason));
            }
        });
        return cancel;
    }

    // ------------------------------------------------------ auto screenshots
    private android.database.ContentObserver screenshotObserver;
    private long lastScreenshotId = -1;

    public static String[] mediaPermissions() {
        return Build.VERSION.SDK_INT >= 33
                ? new String[]{"android.permission.READ_MEDIA_IMAGES"}
                : new String[]{"android.permission.READ_EXTERNAL_STORAGE"};
    }

    public void setAutoScreenshots(boolean enabled) {
        identity.setFlag("auto_screenshots", enabled);
        if (enabled) {
            startScreenshotWatcher();
        } else if (screenshotObserver != null) {
            getContentResolver().unregisterContentObserver(screenshotObserver);
            screenshotObserver = null;
        }
    }

    private void startScreenshotWatcher() {
        if (screenshotObserver != null || !identity.flag("auto_screenshots", false)) {
            return;
        }
        lastScreenshotId = latestScreenshotId();
        screenshotObserver = new android.database.ContentObserver(main) {
            @Override
            public void onChange(boolean selfChange) {
                main.removeCallbacks(checkScreenshots);
                main.postDelayed(checkScreenshots, 1200); // let the file finish writing
            }
        };
        getContentResolver().registerContentObserver(
                android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true, screenshotObserver);
    }

    private final Runnable checkScreenshots = () -> network.execute(this::sendNewScreenshots);

    private long latestScreenshotId() {
        try (android.database.Cursor cursor = queryScreenshots(-1)) {
            return cursor != null && cursor.moveToFirst() ? cursor.getLong(0) : -1;
        } catch (Exception error) {
            return -1;
        }
    }

    private android.database.Cursor queryScreenshots(long afterId) {
        String where = android.provider.MediaStore.Images.Media.RELATIVE_PATH + " LIKE ?"
                + (afterId >= 0 ? " AND " + android.provider.MediaStore.Images.Media._ID + " > " + afterId : "");
        return getContentResolver().query(
                android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                new String[]{android.provider.MediaStore.Images.Media._ID},
                where, new String[]{"%Screenshots%"},
                android.provider.MediaStore.Images.Media._ID + " DESC");
    }

    private void sendNewScreenshots() {
        Peer target = preferredOnlinePeer();
        List<Uri> uris = new ArrayList<>();
        long newest = lastScreenshotId;
        try (android.database.Cursor cursor = queryScreenshots(lastScreenshotId)) {
            while (cursor != null && cursor.moveToNext() && uris.size() < 5) {
                long id = cursor.getLong(0);
                newest = Math.max(newest, id);
                uris.add(android.content.ContentUris.withAppendedId(
                        android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id));
            }
        } catch (Exception error) {
            return; // permission revoked or provider busy
        }
        lastScreenshotId = newest;
        if (target != null && !uris.isEmpty()) {
            main.post(() -> {
                sendUris(target, uris);
                message("Skærmbillede sendt til " + target.name, false);
            });
        }
    }

    /** The device the user picked in the app, else the first paired device that is online. */
    public Peer preferredOnlinePeer() {
        Peer chosen = peer(identity.string("selected_peer", ""));
        if (chosen != null && isOnline(chosen.deviceId) && identity.isOutboundTrusted(chosen.deviceId)) {
            return chosen;
        }
        for (Peer candidate : pairedPeers()) {
            if (isOnline(candidate.deviceId)) {
                return candidate;
            }
        }
        return null;
    }

    // ---------------------------------------------------------------- sending
    private TransferItem newTransfer(String name, boolean folder, Peer peer) {
        TransferItem item = new TransferItem(
                java.util.UUID.randomUUID().toString(), name, true, folder, peer.name);
        item.cancel = new H4xtorClient.CancelToken();
        transfers.put(item.id, item);
        changed();
        return item;
    }

    private void progress(TransferItem item, long sent, long total) {
        long now = SystemClock.elapsedRealtime();
        long elapsed = now - item.lastTime;
        if (elapsed >= 300) {
            double instant = (sent - item.lastSent) * 1000.0 / elapsed;
            item.speed = item.speed <= 0 ? instant : item.speed * 0.7 + instant * 0.3;
            item.peakSpeed = Math.max(item.peakSpeed, item.speed);
            item.addSample((float) item.speed);
            item.lastTime = now;
            item.lastSent = sent;
        }
        item.sent = sent;
        item.total = total;
        changed();
        main.post(() -> updateTransferNotification(false));
    }

    private void runTransfer(TransferItem item, TransferJob job) {
        item.startedAt = SystemClock.elapsedRealtime();
        item.finishedAt = 0;
        item.status = "active";
        item.error = "";
        item.cancel = new H4xtorClient.CancelToken();
        item.retry = () -> runTransfer(item, job);
        changed();
        transfersExecutor.execute(() -> {
            try {
                job.run(item);
                item.status = "done";
                item.sent = item.total;
                finished(item);
            } catch (H4xtorClient.CancelledException error) {
                item.status = "cancelled";
            } catch (Exception error) {
                item.status = item.cancel.isCancelled() ? "cancelled" : "failed";
                item.error = H4xtorClient.safeMessage(error);
                android.util.Log.w("h4xtor", "transfer " + item.name + " failed", error);
                if (!item.cancel.isCancelled()) {
                    message("Overførsel fejlede: " + item.error, true);
                }
            }
            changed();
            main.post(() -> updateTransferNotification(true));
        });
    }

    private interface TransferJob {
        void run(TransferItem item) throws Exception;
    }

    public List<String> sendUris(Peer peer, List<Uri> uris) {
        List<String> ids = new ArrayList<>();
        for (Uri uri : uris) {
            H4xtorClient.SourceInfo info = client.describe(uri);
            TransferItem item = newTransfer(info.name, false, peer);
            item.total = Math.max(0, info.size);
            item.uri = uri.toString(); // the phone's own copy: lets "Åbn" open what was sent
            runTransfer(item, current -> {
                client.sendFile(peer, uri, (name, sent, total) -> progress(current, sent, total), current.cancel);
                recordSent(peer, "file", info.name, info.size, uri.toString());
            });
            ids.add(item.id);
        }
        return ids;
    }

    public TransferItem transfer(String id) {
        return id == null ? null : transfers.get(id);
    }

    public void sendTree(Peer peer, Uri tree) {
        String name = client.treeName(tree);
        TransferItem item = newTransfer(name, true, peer);
        runTransfer(item, current -> {
            client.sendFolder(peer, tree, (folder, sent, total) -> progress(current, sent, total), current.cancel);
            recordSent(peer, "folder", name, current.total);
        });
    }

    public void sendText(Peer peer, String text) {
        if (text == null || text.trim().isEmpty()) {
            return;
        }
        final String value = text.trim();
        clipboardObserved = value;
        network.execute(() -> {
            try {
                if (Ui.isLink(value)) {
                    client.sendLink(peer, value);
                    recordSent(peer, "link", value, 0);
                } else {
                    client.sendClipboard(peer, value);
                    recordSent(peer, "clipboard", value, 0);
                }
                message("Sendt til " + peer.name + " ✓", false);
            } catch (Exception error) {
                message("Kunne ikke sende: " + H4xtorClient.safeMessage(error), true);
            }
        });
    }

    /** Broadcast text to every paired, online device. Returns how many got it queued. */
    public int sendTextToAll(String text) {
        int count = 0;
        for (Peer peer : pairedPeers()) {
            if (isOnline(peer.deviceId)) {
                sendText(peer, text);
                count++;
            }
        }
        return count;
    }

    public void cancel(String id) {
        TransferItem item = transfers.get(id);
        if (item != null && item.cancel != null) {
            item.cancel.cancel();
            item.status = "cancelled";
            changed();
            updateTransferNotification(true);
        }
    }

    public void retry(String id) {
        TransferItem item = transfers.get(id);
        if (item != null && item.retry != null && !"active".equals(item.status)) {
            item.retry.run();
        }
    }

    private void recordSent(Peer peer, String kind, String text, long size) {
        recordSent(peer, kind, text, size, "");
    }

    private void recordSent(Peer peer, String kind, String text, long size, String uri) {
        try {
            identity.appendHistory("sent", new JSONObject()
                    .put("kind", kind)
                    .put("text", text.length() > 1000 ? text.substring(0, 1000) : text)
                    .put("size", size)
                    .put("uri", uri)
                    .put("peer", peer.name)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    private void recordReceived(String kind, String text, long size, String uri, String peerName) {
        try {
            identity.appendHistory("received", new JSONObject()
                    .put("kind", kind)
                    .put("text", text.length() > 1000 ? text.substring(0, 1000) : text)
                    .put("size", size)
                    .put("uri", uri)
                    .put("peer", peerName)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    // -------------------------------------------------------------- receiving
    @Override
    public void onReceiveProgress(String transferId, String name, String peerName, long received, long total) {
        TransferItem item = transfers.get(transferId);
        if (item == null) {
            item = new TransferItem(transferId, name, false, false, peerName);
            item.lastSent = received;
            transfers.put(transferId, item);
        }
        if (!"done".equals(item.status)) {
            item.status = "active";
        }
        progress(item, received, total);
    }

    @Override
    public void onFileReceived(String transferId, String peerName, String fileName, String uri, long size) {
        TransferItem item = transfers.get(transferId);
        if (item == null) {
            item = new TransferItem(transferId, fileName, false, false, peerName);
            transfers.put(transferId, item);
        }
        item.status = "done";
        item.sent = size;
        item.total = size;
        item.uri = uri;
        finished(item);
        recordReceived("file", fileName, size, uri, peerName);
        changed();
        main.post(() -> updateTransferNotification(true));
        PendingIntent open = null;
        if (!uri.isEmpty()) {
            Intent view = Ui.openFileIntent(Uri.parse(uri), fileName);
            open = PendingIntent.getActivity(this, transferId.hashCode(), view,
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        }
        notifyEvent(transferId.hashCode(), "Modtaget fra " + peerName, fileName + " · " + Ui.formatBytes(size)
                + " – tryk for at åbne", open);
    }

    @Override
    public void onFolderReceived(String transferId, String peerName, String folderName, int files, long size) {
        TransferItem item = transfers.get(transferId);
        if (item == null) {
            item = new TransferItem(transferId, folderName, false, true, peerName);
            transfers.put(transferId, item);
        }
        item.status = "done";
        item.sent = size;
        item.total = size;
        item.uri = "folder:" + folderName;
        finished(item);
        recordReceived("folder", folderName, size, "", peerName);
        changed();
        main.post(() -> updateTransferNotification(true));
        notifyEvent(transferId.hashCode(), "Mappe modtaget fra " + peerName,
                folderName + " · " + files + " filer · " + Ui.formatBytes(size) + " – i Overførsler/h4xtor-share",
                null);
    }

    @Override
    public void onClipboardReceived(String peerId, String peerName, String text) {
        recordReceived(Ui.isLink(text) ? "link" : "clipboard", text, 0, "", peerName);
        main.post(() -> {
            if (identity.flag("apply_clipboard", true)) {
                try {
                    clipboardObserved = text;
                    markClipboardShared(text);
                    clipboardSuppress = text;
                    clipboardSuppressUntil = SystemClock.elapsedRealtime() + CLIPBOARD_SUPPRESS_MS;
                    clipboard.setPrimaryClip(ClipData.newPlainText("h4xtor share", text));
                } catch (Exception ignored) {
                    // Clipboard may be unavailable.
                }
            }
            if (Ui.isLink(text) && identity.flag("open_links", true)) {
                onLinkReceived(peerId, peerName, text.trim());
                return;
            }
            if (listeners.isEmpty()) {
                if (Build.VERSION.SDK_INT < 33) {
                    notifyEvent(200, "Udklipsholder fra " + peerName, text, null);
                }
            } else {
                message("Udklipsholder fra " + peerName + " – klar til indsæt", false);
            }
            changed();
        });
    }

    @Override
    public void onLinkReceived(String peerId, String peerName, String url) {
        recordReceived("link", url, 0, "", peerName);
        main.post(() -> {
            if (!listeners.isEmpty() && identity.flag("open_links", true)) {
                for (UiListener listener : listeners) {
                    listener.onLinkReceived(peerName, url);
                }
            } else {
                Intent view = new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                PendingIntent open = PendingIntent.getActivity(this, url.hashCode(), view,
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
                notifyEvent(url.hashCode(), "Link fra " + peerName, url + "\nTryk for at åbne", open);
            }
            changed();
        });
    }

    // -------------------------------------------------------------- clipboard
    private void registerClipboard() {
        clipListener = () -> main.post(this::readClipboardAndSync);
        try {
            clipboard.addPrimaryClipChangedListener(clipListener);
        } catch (Exception ignored) {
            clipListener = null;
        }
    }

    /** Called when the clipboard may be readable (app in the foreground). */
    public void readClipboardAndSync() {
        syncClipboard(false);
    }

    /** The user just tapped "Kopiér" somewhere ({@link CopyWatchService}): always send new text. */
    public int syncCopiedText() {
        return syncClipboard(true);
    }

    private int syncClipboard(boolean justCopied) {
        if (!identity.isClipboardSyncEnabled()) {
            return 0;
        }
        String text = currentClipboard();
        if (text == null || text.isEmpty() || text.equals(clipboardObserved)) {
            return 0;
        }
        boolean first = clipboardObserved.isEmpty();
        clipboardObserved = text;
        if (text.equals(clipboardSuppress) && SystemClock.elapsedRealtime() < clipboardSuppressUntil) {
            return 0;
        }
        if (first && !justCopied && identity.flag("clipboard_seen", false)) {
            return 0;
        }
        identity.setFlag("clipboard_seen", true);
        int count = sendClipboardToOnline(text);
        if (count == 0 && justCopied) {
            pendingCopy = text;
            pendingCopyUntil = SystemClock.elapsedRealtime() + 120_000;
        }
        return count;
    }

    private int sendClipboardToOnline(String text) {
        int count = 0;
        for (Peer peer : pairedPeers()) {
            if (isOnline(peer.deviceId)) {
                final Peer target = peer;
                count++;
                network.execute(() -> {
                    try {
                        client.sendClipboard(target, text);
                        recordSent(target, Ui.isLink(text) ? "link" : "clipboard", text, 0);
                    } catch (Exception ignored) {
                        // One offline peer must not stop the sync.
                    }
                });
            }
        }
        if (count > 0) {
            markClipboardShared(text);
            message("Udklipsholder synkroniseret til " + count + (count == 1 ? " enhed" : " enheder"), false);
        }
        return count;
    }

    /** Text already on the other devices: came from them or was synced to them. */
    private volatile String lastSharedClipboard;

    public boolean isClipboardShared(String text) {
        if (lastSharedClipboard == null) {
            lastSharedClipboard = identity.string("last_shared_clipboard", "");
        }
        return text != null && text.trim().equals(lastSharedClipboard.trim());
    }

    public void markClipboardShared(String text) {
        lastSharedClipboard = text == null ? "" : text;
        identity.setString("last_shared_clipboard",
                lastSharedClipboard.length() > 4000 ? lastSharedClipboard.substring(0, 4000) : lastSharedClipboard);
    }

    public String currentClipboard() {
        try {
            ClipData clip = clipboard.getPrimaryClip();
            if (clip == null || clip.getItemCount() == 0) {
                return null;
            }
            CharSequence value = clip.getItemAt(0).coerceToText(this);
            return value == null ? null : value.toString();
        } catch (Exception error) {
            return null;
        }
    }

    // ----------------------------------------------------------- Wi-Fi Direct
    public void startWifiDirect() {
        wifiDirect.start(new WifiDirectController.Callback() {
            @Override
            public void onGroupStarted(String ssid, String passphrase) {
                message("Wi-Fi Direct er klar: " + ssid, false);
                udp.announceNow();
                updateServiceNotification();
                changed();
            }

            @Override
            public void onGroupFailed(String reason) {
                message(reason, true);
                changed();
            }

            @Override
            public void onGroupStopped() {
                changed();
            }
        });
    }

    public void stopWifiDirect() {
        wifiDirect.stop(new WifiDirectController.Callback() {
            @Override public void onGroupStarted(String ssid, String passphrase) { }
            @Override public void onGroupFailed(String reason) { }

            @Override
            public void onGroupStopped() {
                message("Wi-Fi Direct er slået fra", false);
                updateServiceNotification();
                changed();
            }
        });
    }

    public void offerWifiDirect(Peer peer) {
        if (!wifiDirect.isActive()) {
            message("Start Wi-Fi Direct først", true);
            return;
        }
        network.execute(() -> {
            try {
                client.sendWifiDirectOffer(peer, wifiDirect.ssid(), wifiDirect.passphrase());
                message("Sendt til " + peer.name + " – godkend på PC'en", false);
            } catch (Exception error) {
                message("Kunne ikke sende til " + peer.name + ": " + H4xtorClient.safeMessage(error), true);
            }
        });
    }

    public void renameDevice(String name) {
        identity.setDeviceName(name);
        restartDiscovery();
        changed();
    }
}
