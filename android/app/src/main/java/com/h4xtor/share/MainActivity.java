package com.h4xtor.share;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ClipboardManager.OnPrimaryClipChangedListener;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.MimeTypeMap;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

public final class MainActivity extends Activity
        implements H4xtorServer.Listener, DiscoveryController.Listener {

    private static final int REQUEST_NEARBY = 2001;
    private static final int REQUEST_FILE = 2002;

    private static final int HEALTH_INTERVAL_MS = 4000;
    private static final int CLIPBOARD_SUPPRESS_MS = 3000;
    private static final int CLIPBOARD_DEBOUNCE_MS = 800;

    private static final int BG = Color.rgb(8, 17, 29);
    private static final int PANEL = Color.rgb(16, 28, 43);
    private static final int PANEL_ALT = Color.rgb(20, 35, 53);
    private static final int BORDER = Color.rgb(36, 55, 77);
    private static final int TEXT = Color.rgb(238, 246, 255);
    private static final int MUTED = Color.rgb(145, 162, 183);
    private static final int ACCENT = Color.rgb(22, 212, 178);
    private static final int ACCENT_DARK = Color.rgb(11, 128, 111);
    private static final int WARNING = Color.rgb(245, 189, 79);

    private final ExecutorService networkExecutor = Executors.newFixedThreadPool(48);
    private final Map<String, Peer> peers = Collections.synchronizedMap(new LinkedHashMap<>());
    private final AtomicBoolean scanRunning = new AtomicBoolean(false);
    private final Map<String, PeerHealth> peerHealth = Collections.synchronizedMap(new HashMap<>());
    private final Map<String, Boolean> peerLastOnline = Collections.synchronizedMap(new HashMap<>());
    private final Map<String, Integer> peerConnections = Collections.synchronizedMap(new HashMap<>());
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private String clipboardObserved = "";
    private String clipboardSuppressText = "";
    private long clipboardSuppressUntil = 0L;
    private String pendingClipboardBroadcast = null;
    private OnPrimaryClipChangedListener clipboardSyncListener;

    private AppIdentity identity;
    private H4xtorClient client;
    private H4xtorServer server;
    private DiscoveryController discovery;

    private TextView statusText;
    private TextView discoveryText;
    private TextView activityText;
    private LinearLayout devicesContainer;
    private ProgressBar scanProgress;
    private Button scanButton;
    private Peer selectedPeer;
    private Peer pendingFilePeer;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        identity = new AppIdentity(this);
        client = new H4xtorClient(this, identity);
        server = new H4xtorServer(this, identity, this);
        discovery = new DiscoveryController(this, identity, this);
        setContentView(buildUi());
        requestLanAccessAndStart();
        registerClipboardSync();
        mainHandler.postDelayed(this::scheduleHealthChecks, HEALTH_INTERVAL_MS);
    }

    private static final class PeerHealth {
        final boolean online;
        final long rttMs;

        PeerHealth(boolean online, long rttMs) {
            this.online = online;
            this.rttMs = rttMs;
        }
    }

    private void registerClipboardSync() {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        clipboardSyncListener = () -> {
            if (identity.isClipboardSyncEnabled()) {
                runOnUiThread(() -> handleClipboardChanged(clipboard));
            }
        };
        clipboard.addPrimaryClipChangedListener(clipboardSyncListener);
    }

    private void handleClipboardChanged(ClipboardManager clipboard) {
        ClipData clip = clipboard.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) {
            return;
        }
        CharSequence value = clip.getItemAt(0).coerceToText(this);
        String text = value == null ? "" : value.toString();
        if (text.isEmpty() || text.equals(clipboardObserved)) {
            return;
        }
        clipboardObserved = text;
        long now = SystemClock.elapsedRealtime();
        if (text.equals(clipboardSuppressText) && now < clipboardSuppressUntil) {
            return;
        }
        pendingClipboardBroadcast = text;
        mainHandler.removeCallbacks(broadcastPendingClipboard);
        mainHandler.postDelayed(broadcastPendingClipboard, CLIPBOARD_DEBOUNCE_MS);
    }

    private final Runnable broadcastPendingClipboard = () -> {
        final String text = pendingClipboardBroadcast;
        pendingClipboardBroadcast = null;
        if (text == null) {
            return;
        }
        networkExecutor.execute(() -> {
            List<Peer> targets = trustedPeers();
            int delivered = 0;
            for (Peer peer : targets) {
                try {
                    client.sendClipboard(peer, text);
                    delivered++;
                    recordSentText(peer, text);
                } catch (Exception ignored) {
                    // A single unreachable peer must not stop the clipboard sync.
                }
            }
            if (delivered > 0) {
                status("Clipboard synced to " + delivered + " device(s)");
            }
        });
    };

    private void recordSentText(Peer peer, String text) {
        try {
            identity.appendHistory("sent", new JSONObject()
                    .put("kind", isLink(text) ? "link" : "clipboard")
                    .put("text", text.length() > 1000 ? text.substring(0, 1000) : text)
                    .put("peer", peer.name)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    private void scheduleHealthChecks() {
        if (isFinishing() || isDestroyed()) {
            return;
        }
        checkPeerHealth();
        mainHandler.postDelayed(this::scheduleHealthChecks, HEALTH_INTERVAL_MS);
    }

    private void checkPeerHealth() {
        List<Peer> snapshot;
        synchronized (peers) {
            snapshot = new ArrayList<>(peers.values());
        }
        for (Peer peer : snapshot) {
            networkExecutor.execute(() -> {
                boolean online;
                long rtt;
                try {
                    rtt = client.ping(peer, 2000);
                    online = true;
                } catch (Exception ignored) {
                    online = false;
                    rtt = 0L;
                }
                peerHealth.put(peer.deviceId, new PeerHealth(online, rtt));
                Boolean previous = peerLastOnline.get(peer.deviceId);
                if (previous == null || previous != online) {
                    peerLastOnline.put(peer.deviceId, online);
                    if (online) {
                        int count = peerConnections.getOrDefault(peer.deviceId, 0) + 1;
                        peerConnections.put(peer.deviceId, count);
                    }
                    recordDevice(peer, online, rtt);
                }
                runOnUiThread(this::renderPeers);
            });
        }
    }

    private void recordDevice(Peer peer, boolean online, long rttMs) {
        try {
            identity.appendHistory("devices", new JSONObject()
                    .put("name", peer.name)
                    .put("ip", peer.address)
                    .put("os", peer.platform)
                    .put("online", online)
                    .put("rtt_ms", rttMs)
                    .put("connections", peerConnections.getOrDefault(peer.deviceId, 0))
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    private List<Peer> trustedPeers() {
        List<Peer> result = new ArrayList<>();
        synchronized (peers) {
            for (Peer peer : peers.values()) {
                if (identity.isOutboundTrusted(peer.deviceId)) {
                    result.add(peer);
                }
            }
        }
        return result;
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(16), dp(18), dp(24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(header, matchWrap());

        TextView title = text("h4xtor-share", 27, TEXT, true);
        header.addView(title, new LinearLayout.LayoutParams(0, dp(58), 1f));
        Button history = button("History", false);
        history.setOnClickListener(v -> showHistory());
        header.addView(history, new LinearLayout.LayoutParams(dp(92), dp(46)));
        Button settings = button("Settings", false);
        settings.setOnClickListener(v -> showSettings());
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(dp(105), dp(46));
        settingsParams.setMargins(dp(8), 0, 0, 0);
        header.addView(settings, settingsParams);

        statusText = text("Starting local services…", 13, ACCENT, true);
        root.addView(statusText, marginParams(dp(0), dp(2), dp(0), dp(14)));

        LinearLayout discoveryCard = panel();
        root.addView(discoveryCard, marginParams(0, 0, 0, dp(12)));
        discoveryCard.addView(text("LAN Discovery", 18, TEXT, true));
        discoveryText = text("Auto-discovery via mDNS is starting…", 12, MUTED, false);
        discoveryCard.addView(discoveryText, marginParams(0, dp(3), 0, dp(12)));

        LinearLayout scanRow = new LinearLayout(this);
        scanRow.setOrientation(LinearLayout.HORIZONTAL);
        scanRow.setGravity(Gravity.CENTER_VERTICAL);
        discoveryCard.addView(scanRow, matchWrap());
        scanButton = button("Scan LAN", true);
        scanButton.setOnClickListener(v -> scanLan());
        scanRow.addView(scanButton, new LinearLayout.LayoutParams(0, dp(52), 1f));
        Button refresh = button("Refresh mDNS", false);
        refresh.setOnClickListener(v -> restartDiscovery());
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(0, dp(52), 1f);
        refreshParams.setMargins(dp(8), 0, 0, 0);
        scanRow.addView(refresh, refreshParams);

        scanProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        scanProgress.setMax(254);
        scanProgress.setProgress(0);
        scanProgress.getProgressDrawable().setTint(ACCENT);
        discoveryCard.addView(scanProgress, marginParams(0, dp(10), 0, 0));

        LinearLayout devicesCard = panel();
        root.addView(devicesCard, marginParams(0, 0, 0, dp(12)));
        TextView devicesTitle = text("Discovered devices", 18, TEXT, true);
        devicesCard.addView(devicesTitle);
        TextView hint = text(
                "Tap a device to select it. Pair once, then send files or clipboard securely.",
                12,
                MUTED,
                false);
        devicesCard.addView(hint, marginParams(0, dp(3), 0, dp(10)));
        devicesContainer = new LinearLayout(this);
        devicesContainer.setOrientation(LinearLayout.VERTICAL);
        devicesCard.addView(devicesContainer, matchWrap());
        renderPeers();

        LinearLayout quick = panel();
        root.addView(quick, marginParams(0, 0, 0, dp(12)));
        quick.addView(text("Quick Send", 18, TEXT, true));
        TextView selected = text("Select a paired device above first.", 12, MUTED, false);
        selected.setId(View.generateViewId());
        quick.addView(selected, marginParams(0, dp(3), 0, dp(10)));

        LinearLayout quickRow = new LinearLayout(this);
        quickRow.setOrientation(LinearLayout.HORIZONTAL);
        quick.addView(quickRow, matchWrap());
        Button sendFiles = button("Send files", true);
        sendFiles.setOnClickListener(v -> chooseFile());
        quickRow.addView(sendFiles, new LinearLayout.LayoutParams(0, dp(54), 1f));
        Button sendClipboard = button("Send clipboard", false);
        sendClipboard.setOnClickListener(v -> sendClipboard());
        LinearLayout.LayoutParams clipboardParams = new LinearLayout.LayoutParams(0, dp(54), 1f);
        clipboardParams.setMargins(dp(8), 0, 0, 0);
        quickRow.addView(sendClipboard, clipboardParams);

        LinearLayout activity = panel();
        root.addView(activity, matchWrap());
        activity.addView(text("Activity", 18, TEXT, true));
        activityText = text("Ready.", 12, MUTED, false);
        activity.setMinimumHeight(dp(110));
        activity.addView(activityText, marginParams(0, dp(8), 0, 0));
        return scroll;
    }

    private void requestLanAccessAndStart() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.NEARBY_WIFI_DEVICES}, REQUEST_NEARBY);
            return;
        }
        startNetworking();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_NEARBY) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startNetworking();
            } else {
                status("Nearby devices permission denied. Manual Add/scan may be limited.");
                startNetworking();
            }
        }
    }

    private void startNetworking() {
        networkExecutor.execute(() -> {
            try {
                server.start();
                runOnUiThread(() -> {
                    discovery.start();
                    discoveryText.setText("Auto-discovery is ON • local port " + AppIdentity.PORT);
                });
            } catch (Exception error) {
                status("Could not start P2P server: " + safeMessage(error));
            }
        });
    }

    private void restartDiscovery() {
        discovery.stop();
        discovery.start();
        discoveryText.setText("Auto-discovery restarted");
    }

    private void scanLan() {
        if (!scanRunning.compareAndSet(false, true)) {
            return;
        }
        scanButton.setEnabled(false);
        scanProgress.setProgress(0);
        status("Scanning local /24 network…");
        networkExecutor.execute(() -> {
            try {
                Set<String> targets = lanTargets();
                if (targets.isEmpty()) {
                    throw new IllegalStateException("No active private IPv4 LAN interface found");
                }
                AtomicInteger completed = new AtomicInteger(0);
                int total = targets.size();
                runOnUiThread(() -> scanProgress.setMax(Math.max(1, total)));
                for (String address : targets) {
                    networkExecutor.execute(() -> {
                        try {
                            Peer peer = client.getInfo(address, AppIdentity.PORT, 650);
                            addPeer(peer);
                        } catch (Exception ignored) {
                            // Most addresses are expected to have no h4xtor-share endpoint.
                        } finally {
                            int done = completed.incrementAndGet();
                            if (done == total || done % Math.max(1, total / 50) == 0) {
                                runOnUiThread(() -> scanProgress.setProgress(done));
                            }
                            if (done == total) {
                                scanRunning.set(false);
                                runOnUiThread(() -> {
                                    scanButton.setEnabled(true);
                                    statusText.setText("LAN scan complete • " + peers.size() + " peer(s) known");
                                    appendActivity("LAN scan complete");
                                });
                            }
                        }
                    });
                }
            } catch (Exception error) {
                scanRunning.set(false);
                runOnUiThread(() -> scanButton.setEnabled(true));
                status("LAN scan failed: " + safeMessage(error));
            }
        });
    }

    private Set<String> lanTargets() throws Exception {
        Set<String> targets = new LinkedHashSet<>();
        Set<String> own = new LinkedHashSet<>();
        Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
        while (interfaces.hasMoreElements()) {
            NetworkInterface networkInterface = interfaces.nextElement();
            if (!networkInterface.isUp() || networkInterface.isLoopback()) {
                continue;
            }
            Enumeration<java.net.InetAddress> addresses = networkInterface.getInetAddresses();
            while (addresses.hasMoreElements()) {
                java.net.InetAddress address = addresses.nextElement();
                if (address instanceof Inet4Address && !address.isLoopbackAddress() && address.isSiteLocalAddress()) {
                    own.add(address.getHostAddress());
                }
            }
        }
        for (String address : own) {
            String[] parts = address.split("\\.");
            if (parts.length != 4) {
                continue;
            }
            String prefix = parts[0] + "." + parts[1] + "." + parts[2] + ".";
            for (int host = 1; host <= 254; host++) {
                String candidate = prefix + host;
                if (!own.contains(candidate)) {
                    targets.add(candidate);
                }
            }
        }
        return targets;
    }

    private void probePeer(String address, int port) {
        networkExecutor.execute(() -> {
            try {
                addPeer(client.getInfo(address, port, 2_000));
            } catch (Exception ignored) {
                // mDNS can race with a peer leaving the network.
            }
        });
    }

    private void addPeer(Peer peer) {
        if (peer == null || identity.deviceId().equals(peer.deviceId)) {
            return;
        }
        peers.put(peer.deviceId, peer);
        runOnUiThread(this::renderPeers);
    }

    private void renderPeers() {
        if (devicesContainer == null) {
            return;
        }
        devicesContainer.removeAllViews();
        List<Peer> snapshot;
        synchronized (peers) {
            snapshot = new ArrayList<>(peers.values());
        }
        snapshot.sort(Comparator.comparing(peer -> peer.name.toLowerCase(java.util.Locale.ROOT)));
        if (snapshot.isEmpty()) {
            TextView empty = text("No peers yet. Auto-discovery is running; use Scan LAN as fallback.", 13, MUTED, false);
            devicesContainer.addView(empty, marginParams(dp(2), dp(12), dp(2), dp(12)));
            return;
        }
        for (Peer peer : snapshot) {
            devicesContainer.addView(deviceCard(peer), marginParams(0, 0, 0, dp(8)));
        }
    }

    private View deviceCard(Peer peer) {
        boolean selected = selectedPeer != null && selectedPeer.deviceId.equals(peer.deviceId);
        boolean trusted = identity.isOutboundTrusted(peer.deviceId);
        PeerHealth health = peerHealth.get(peer.deviceId);
        boolean online = health != null && health.online;
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(13), dp(11), dp(13), dp(11));
        card.setBackground(rounded(selected ? Color.rgb(17, 67, 77) : PANEL_ALT, selected ? ACCENT : BORDER, 12));
        card.setOnClickListener(v -> {
            selectedPeer = peer;
            renderPeers();
            statusText.setText("Selected " + peer.name + (trusted ? " • connected" : " • connect to pair"));
        });

        LinearLayout first = new LinearLayout(this);
        first.setOrientation(LinearLayout.HORIZONTAL);
        first.setGravity(Gravity.CENTER_VERTICAL);
        card.addView(first, matchWrap());
        TextView name = text(peer.name, 16, TEXT, true);
        first.addView(name, new LinearLayout.LayoutParams(0, dp(34), 1f));
        int ledColor = online ? ACCENT : (trusted ? WARNING : Color.rgb(120, 133, 150));
        String ledLabel;
        if (online) {
            ledLabel = "● Online " + signalBars(health.rttMs);
        } else if (trusted) {
            ledLabel = "● Paired";
        } else {
            ledLabel = "○ Discovered";
        }
        TextView state = text(ledLabel, 12, ledColor, true);
        first.addView(state);

        TextView details = text(
                peer.address + ":" + peer.port + "  •  " + peer.platform,
                12,
                MUTED,
                false);
        card.addView(details, marginParams(0, dp(2), 0, dp(8)));

        if (!trusted) {
            Button connect = button("Connect", true);
            connect.setOnClickListener(v -> pair(peer));
            card.addView(connect, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        }
        return card;
    }

    private static String signalBars(long rttMs) {
        if (rttMs < 15) {
            return "▂▄▆█";
        }
        if (rttMs < 40) {
            return "▂▄▆";
        }
        if (rttMs < 100) {
            return "▂▄";
        }
        return "▂";
    }

    private void pair(Peer peer) {
        status("Connecting to " + peer.name + "…");
        networkExecutor.execute(() -> {
            try {
                org.json.JSONObject response = client.requestPairing(peer);
                String pairingId = response.getString("pairing_id");
                runOnUiThread(() -> promptPairCode(peer, pairingId));
            } catch (Exception error) {
                status("Pairing request failed: " + safeMessage(error));
            }
        });
    }

    private void promptPairCode(Peer peer, String pairingId) {
        EditText input = new EditText(this);
        input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        input.setHint("6-digit code");
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setBackgroundColor(PANEL_ALT);
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
        new AlertDialog.Builder(this)
                .setTitle("Pair with " + peer.name)
                .setMessage("Enter the six-digit code shown on the other device.")
                .setView(input)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Pair", (dialog, which) -> {
                    String code = input.getText().toString().trim();
                    if (!code.matches("\\d{6}")) {
                        toast("Pairing code must contain six digits");
                        return;
                    }
                    networkExecutor.execute(() -> {
                        try {
                            client.confirmPairing(peer, pairingId, code);
                            selectedPeer = peer;
                            runOnUiThread(this::renderPeers);
                            status("Paired with " + peer.name);
                            appendActivity("Paired with " + peer.name);
                        } catch (Exception error) {
                            status("Pairing failed: " + safeMessage(error));
                        }
                    });
                })
                .show();
    }

    private void sendClipboard() {
        Peer peer = selectedTrustedPeer();
        if (peer == null) {
            return;
        }
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData clip = clipboard.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) {
            toast("Clipboard is empty");
            return;
        }
        CharSequence value = clip.getItemAt(0).coerceToText(this);
        String text = value == null ? "" : value.toString();
        networkExecutor.execute(() -> {
            try {
                client.sendClipboard(peer, text);
                recordSentText(peer, text);
                status("Clipboard sent to " + peer.name);
                appendActivity("Clipboard sent to " + peer.name);
            } catch (Exception error) {
                status("Clipboard send failed: " + safeMessage(error));
            }
        });
    }

    private void chooseFile() {
        Peer peer = selectedTrustedPeer();
        if (peer == null) {
            return;
        }
        pendingFilePeer = peer;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        startActivityForResult(intent, REQUEST_FILE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_FILE || resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        Peer peer = pendingFilePeer;
        pendingFilePeer = null;
        if (peer == null) {
            return;
        }
        networkExecutor.execute(() -> {
            try {
                client.sendFile(peer, uri, (fileName, sent, total) -> {
                    int percent = total <= 0 ? 100 : (int) Math.min(100, sent * 100 / total);
                    status("Sending " + fileName + " to " + peer.name + " • " + percent + "%");
                });
                status("File sent to " + peer.name);
                appendActivity("File sent to " + peer.name);
            } catch (Exception error) {
                status("File send failed: " + safeMessage(error));
            }
        });
    }

    private Peer selectedTrustedPeer() {
        if (selectedPeer == null) {
            toast("Select a device first");
            return null;
        }
        if (!identity.isOutboundTrusted(selectedPeer.deviceId)) {
            toast("Pair with this device first");
            return null;
        }
        return selectedPeer;
    }

    private void showSettings() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(dp(6), dp(6), dp(6), dp(6));

        EditText input = new EditText(this);
        input.setText(identity.deviceName());
        input.setSelectAllOnFocus(true);
        container.addView(input, matchWrap());

        android.widget.CheckBox syncClipboard = new android.widget.CheckBox(this);
        syncClipboard.setText("Broadcast clipboard text to paired devices");
        syncClipboard.setTextColor(TEXT);
        syncClipboard.setChecked(identity.isClipboardSyncEnabled());
        container.addView(syncClipboard, marginParams(0, dp(10), 0, 0));

        new AlertDialog.Builder(this)
                .setTitle("Device name")
                .setMessage("This name is advertised to h4xtor-share peers on your LAN.")
                .setView(container)
                .setNeutralButton("App settings", (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                })
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Save", (dialog, which) -> {
                    try {
                        identity.setDeviceName(input.getText().toString());
                        identity.setClipboardSyncEnabled(syncClipboard.isChecked());
                        restartDiscovery();
                        status("Settings saved");
                    } catch (Exception error) {
                        toast(safeMessage(error));
                    }
                })
                .show();
    }

    private void showHistory() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(8), dp(6), dp(8), dp(6));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        addHistorySection(root, "SENT", historyText("sent"));
        addHistorySection(root, "RECEIVED", historyText("received"));
        addHistorySection(root, "DEVICES", historyText("devices"));
        new AlertDialog.Builder(this)
                .setTitle("History")
                .setView(scroll)
                .setNegativeButton("Close", null)
                .show();
    }

    private void addHistorySection(LinearLayout root, String title, String body) {
        root.addView(text(title, 13, ACCENT, true), marginParams(0, dp(8), 0, dp(4)));
        root.addView(text(body, 12, TEXT, false), marginParams(0, 0, 0, dp(10)));
    }

    private String historyText(String bucket) {
        JSONArray list = identity.history(bucket);
        if (list.length() == 0) {
            return "Nothing yet.";
        }
        StringBuilder builder = new StringBuilder();
        for (int index = list.length() - 1; index >= 0; index--) {
            try {
                JSONObject entry = list.getJSONObject(index);
                if ("devices".equals(bucket)) {
                    builder.append(entry.optString("ts"))
                            .append("  ")
                            .append(entry.optBoolean("online", false) ? "● " : "○ ")
                            .append(entry.optString("name"))
                            .append(" (")
                            .append(entry.optString("ip"))
                            .append(", ")
                            .append(entry.optString("os"))
                            .append(", rtt ")
                            .append(entry.optLong("rtt_ms", 0))
                            .append("ms, connects ")
                            .append(entry.optInt("connections", 0))
                            .append(")\n");
                } else {
                    builder.append(entry.optString("ts"))
                            .append("  ")
                            .append(entry.optString("kind").toUpperCase(Locale.ROOT))
                            .append("  ")
                            .append(entry.optString("text"))
                            .append("  ·  ")
                            .append(entry.optString("peer"))
                            .append('\n');
                }
            } catch (Exception ignored) {
                // Skip malformed entries.
            }
        }
        return builder.toString();
    }

    private static boolean isLink(String text) {
        return text != null && text.trim().matches("(?i)^https?://\\S+$");
    }

    @Override
    public void onPairingCode(String peerName, String code) {
        runOnUiThread(() -> new AlertDialog.Builder(this)
                .setTitle("Pair request from " + peerName)
                .setMessage("Pairing code: " + code + "\n\nEnter this code on the sending device.")
                .setPositiveButton("OK", null)
                .show());
        appendActivity("Pair request from " + peerName);
    }

    @Override
    public void onClipboardReceived(String peerName, String text) {
        runOnUiThread(() -> {
            ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            clipboard.setPrimaryClip(ClipData.newPlainText("h4xtor-share", text));
            clipboardObserved = text;
            clipboardSuppressText = text;
            clipboardSuppressUntil = SystemClock.elapsedRealtime() + CLIPBOARD_SUPPRESS_MS;
            statusText.setText("Clipboard received from " + peerName);
        });
        appendActivity("Clipboard received from " + peerName);
        try {
            identity.appendHistory("received", new JSONObject()
                    .put("kind", isLink(text) ? "link" : "clipboard")
                    .put("text", text.length() > 1000 ? text.substring(0, 1000) : text)
                    .put("peer", peerName)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
    }

    @Override
    public void onFileReceived(String peerName, String fileName, String uri, long size) {
        status("Received " + fileName + " from " + peerName);
        appendActivity("Received " + fileName + " from " + peerName);
        try {
            identity.appendHistory("received", new JSONObject()
                    .put("kind", "file")
                    .put("text", fileName)
                    .put("size", size)
                    .put("uri", uri)
                    .put("peer", peerName)
                    .put("ts", AppIdentity.timestamp()));
        } catch (Exception ignored) {
            // History is best-effort.
        }
        runOnUiThread(() -> promptOpenReceived(fileName, uri));
    }

    private void promptOpenReceived(String fileName, String uri) {
        if (uri == null || uri.isEmpty()) {
            return;
        }
        boolean apk = fileName.toLowerCase(Locale.ROOT).endsWith(".apk");
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle("Received: " + fileName)
                .setMessage("Saved to Downloads/h4xtor-share");
        builder.setPositiveButton(apk ? "Install" : "Open", (dialog, which) -> openReceived(fileName, uri));
        builder.setNeutralButton("Show in Files", (dialog, which) -> revealDownloadsFolder());
        builder.setNegativeButton("Later", null);
        builder.show();
    }

    private void openReceived(String fileName, String uri) {
        boolean apk = fileName.toLowerCase(Locale.ROOT).endsWith(".apk");
        Intent intent = apk
                ? new Intent(Intent.ACTION_INSTALL_PACKAGE)
                : new Intent(Intent.ACTION_VIEW);
        if (apk) {
            intent.setData(Uri.parse(uri));
        } else {
            intent.setDataAndType(Uri.parse(uri), mimeFor(fileName));
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(intent);
        } catch (Exception error) {
            toast("No app can open " + fileName);
        }
    }

    private static String mimeFor(String fileName) {
        String lower = fileName.toLowerCase(Locale.ROOT);
        int dot = lower.lastIndexOf('.');
        if (dot < 0 || dot == lower.length() - 1) {
            return "application/octet-stream";
        }
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(lower.substring(dot + 1));
        return mime == null ? "application/octet-stream" : mime;
    }

    private void revealDownloadsFolder() {
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(
                MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY),
                "vnd.android.document/directory");
        try {
            startActivity(intent);
        } catch (Exception error) {
            toast("No file manager is available");
        }
    }

    @Override
    public void onStatus(String text) {
        status(text);
    }

    @Override
    public void onPeerAddress(String address, int port) {
        probePeer(address, port);
    }

    private void status(String text) {
        runOnUiThread(() -> {
            if (!isFinishing() && !isDestroyed()) {
                statusText.setText(text);
            }
        });
    }

    private void appendActivity(String text) {
        runOnUiThread(() -> {
            if (!isFinishing() && !isDestroyed()) {
                String current = activityText.getText().toString();
                String next = "• " + text + "\n" + current;
                String[] lines = next.split("\\n");
                StringBuilder builder = new StringBuilder();
                for (int index = 0; index < Math.min(lines.length, 8); index++) {
                    if (index > 0) builder.append('\n');
                    builder.append(lines[index]);
                }
                activityText.setText(builder.toString());
            }
        });
    }

    private void toast(String text) {
        runOnUiThread(() -> Toast.makeText(this, text, Toast.LENGTH_SHORT).show());
    }

    private LinearLayout panel() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(14), dp(14), dp(14), dp(14));
        layout.setBackground(rounded(PANEL, BORDER, 14));
        return layout;
    }

    private Button button(String label, boolean primary) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(TEXT);
        button.setTextSize(13);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setPadding(dp(12), 0, dp(12), 0);
        button.setBackground(rounded(primary ? ACCENT_DARK : PANEL_ALT, primary ? ACCENT : BORDER, 10));
        return button;
    }

    private TextView text(String value, int sizeSp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        view.setTypeface(Typeface.DEFAULT, bold ? Typeface.BOLD : Typeface.NORMAL);
        view.setGravity(Gravity.CENTER_VERTICAL);
        return view;
    }

    private GradientDrawable rounded(int fill, int stroke, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), stroke);
        return drawable;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams marginParams(int left, int top, int right, int bottom) {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(left, top, right, bottom);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? error.getClass().getSimpleName() : message;
    }

    @Override
    protected void onDestroy() {
        if (clipboardSyncListener != null) {
            ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            try {
                clipboard.removePrimaryClipChangedListener(clipboardSyncListener);
            } catch (Exception ignored) {
                // Listener may already be unregistered.
            }
        }
        mainHandler.removeCallbacks(broadcastPendingClipboard);
        discovery.stop();
        server.stop();
        networkExecutor.shutdownNow();
        super.onDestroy();
    }
}
