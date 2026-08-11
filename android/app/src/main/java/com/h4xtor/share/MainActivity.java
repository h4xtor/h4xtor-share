package com.h4xtor.share;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
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
        Button settings = button("Settings", false);
        settings.setOnClickListener(v -> showSettings());
        header.addView(settings, new LinearLayout.LayoutParams(dp(105), dp(46)));

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
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(13), dp(11), dp(13), dp(11));
        card.setBackground(rounded(selected ? Color.rgb(17, 67, 77) : PANEL_ALT, selected ? ACCENT : BORDER, 12));
        card.setOnClickListener(v -> {
            selectedPeer = peer;
            renderPeers();
            statusText.setText("Selected " + peer.name + (trusted ? " • paired" : " • pairing required"));
        });

        LinearLayout first = new LinearLayout(this);
        first.setOrientation(LinearLayout.HORIZONTAL);
        first.setGravity(Gravity.CENTER_VERTICAL);
        card.addView(first, matchWrap());
        TextView name = text(peer.name, 16, TEXT, true);
        first.addView(name, new LinearLayout.LayoutParams(0, dp(34), 1f));
        TextView state = text(trusted ? "● Paired" : "● Discovered", 12, trusted ? ACCENT : WARNING, true);
        first.addView(state);

        TextView details = text(
                peer.address + ":" + peer.port + "  •  " + peer.platform,
                12,
                MUTED,
                false);
        card.addView(details, marginParams(0, dp(2), 0, dp(8)));

        if (!trusted) {
            Button pair = button("Pair", true);
            pair.setOnClickListener(v -> pair(peer));
            card.addView(pair, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        }
        return card;
    }

    private void pair(Peer peer) {
        status("Requesting pairing with " + peer.name + "…");
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
        EditText input = new EditText(this);
        input.setText(identity.deviceName());
        input.setSelectAllOnFocus(true);
        new AlertDialog.Builder(this)
                .setTitle("Device name")
                .setMessage("This name is advertised to h4xtor-share peers on your LAN.")
                .setView(input)
                .setNeutralButton("App settings", (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                })
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Save", (dialog, which) -> {
                    try {
                        identity.setDeviceName(input.getText().toString());
                        restartDiscovery();
                        status("Device name saved");
                    } catch (Exception error) {
                        toast(safeMessage(error));
                    }
                })
                .show();
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
            statusText.setText("Clipboard received from " + peerName);
        });
        appendActivity("Clipboard received from " + peerName);
    }

    @Override
    public void onFileReceived(String peerName, String fileName) {
        status("Received " + fileName + " from " + peerName + " • saved in Downloads/h4xtor-share");
        appendActivity("Received " + fileName + " from " + peerName);
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
        discovery.stop();
        server.stop();
        networkExecutor.shutdownNow();
        super.onDestroy();
    }
}
