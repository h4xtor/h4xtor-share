package com.h4xtor.share;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class MainActivity extends Activity implements ShareService.UiListener {
    private static final int REQUEST_PERMISSIONS = 2001;
    private static final int REQUEST_FILES = 2002;
    private static final int REQUEST_TREE = 2003;
    private static final int REQUEST_WIFI_PERMISSION = 2004;

    private static final String PAGE_DEVICES = "devices";
    private static final String PAGE_TRANSFERS = "transfers";
    private static final String PAGE_HISTORY = "history";
    private static final String PAGE_SETTINGS = "settings";

    private Ui ui;
    private ShareService service;
    private String page = PAGE_DEVICES;
    private String historyMode = "received";
    private String selectedId;
    private String pendingPeerId;
    private String pendingInvite;
    private boolean resumed;

    private ScrollView scroll;
    private LinearLayout content;
    private LinearLayout nav;
    private TextView toastView;
    private AlertDialog codeDialog;
    private AlertDialog qrDialog;

    // ---------------------------------------------------------------- lifecycle
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ui = new Ui(this);
        ui.styleWindow(this);
        if (savedInstanceState != null) {
            page = savedInstanceState.getString("page", PAGE_DEVICES);
        }
        setContentView(buildShell());
        handleIntent(getIntent());
        requestStartupPermissions();
        ShareService.with(this, svc -> {
            service = svc;
            selectedId = svc.identity().string("selected_peer", null);
            if (resumed) {
                svc.addListener(this);
            }
            if (pendingInvite != null) {
                svc.pairWithInvite(pendingInvite);
                pendingInvite = null;
            }
            render();
        });
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        outState.putString("page", page);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        Uri data = intent.getData();
        if (Intent.ACTION_VIEW.equals(intent.getAction()) && data != null
                && PairingInvite.SCHEME.equalsIgnoreCase(data.getScheme())) {
            String value = data.toString();
            if (service != null) {
                service.pairWithInvite(value);
            } else {
                pendingInvite = value;
            }
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        if (service != null) {
            service.addListener(this);
            render();
        }
    }

    @Override
    protected void onPause() {
        resumed = false;
        if (service != null) {
            service.removeListener(this);
        }
        super.onPause();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus && service != null) {
            // Android only lets the focused app read the clipboard: sync on focus.
            service.readClipboardAndSync();
        }
    }

    @Override
    protected void onDestroy() {
        if (service != null) {
            service.removeListener(this);
            service.revokeInvite();
            if (!service.identity().flag("run_in_background", true) && isFinishing()) {
                stopService(new Intent(this, ShareService.class));
            }
        }
        super.onDestroy();
    }

    private void requestStartupPermissions() {
        List<String> wanted = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                wanted.add(Manifest.permission.POST_NOTIFICATIONS);
            }
            if (checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) {
                wanted.add(Manifest.permission.NEARBY_WIFI_DEVICES);
            }
        }
        if (!wanted.isEmpty()) {
            requestPermissions(wanted.toArray(new String[0]), REQUEST_PERMISSIONS);
        }
    }

    private boolean hasWifiDirectPermission() {
        String permission = Build.VERSION.SDK_INT >= 33
                ? Manifest.permission.NEARBY_WIFI_DEVICES
                : Manifest.permission.ACCESS_FINE_LOCATION;
        if (checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED) {
            return true;
        }
        requestPermissions(new String[]{permission}, REQUEST_WIFI_PERMISSION);
        return false;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_WIFI_PERMISSION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && service != null) {
                service.startWifiDirect();
            } else {
                toast("Wi-Fi Direct kræver tilladelse til enheder i nærheden", true);
            }
        }
    }

    // ------------------------------------------------------------------- shell
    private View buildShell() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(ui.bg);

        LinearLayout column = ui.column();
        root.addView(column, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        scroll.setVerticalScrollBarEnabled(false);
        content = ui.column();
        content.setPadding(ui.dp(20), ui.dp(18), ui.dp(20), ui.dp(28));
        scroll.addView(content, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        column.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        View line = new View(this);
        line.setBackgroundColor(ui.border);
        column.addView(line, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, ui.dp(1))));
        nav = ui.row();
        nav.setBackgroundColor(ui.surface);
        nav.setPadding(ui.dp(6), ui.dp(6), ui.dp(6), ui.dp(8));
        column.addView(nav, ui.matchWrap());

        toastView = ui.text("", 14f, ui.bg, true);
        toastView.setPadding(ui.dp(18), ui.dp(13), ui.dp(18), ui.dp(13));
        toastView.setBackground(ui.rounded(ui.text, 0, 16));
        toastView.setVisibility(View.GONE);
        toastView.setElevation(ui.dp(6));
        FrameLayout.LayoutParams toastParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        toastParams.setMargins(ui.dp(20), 0, ui.dp(20), ui.dp(92));
        root.addView(toastView, toastParams);
        Ui.onInsets(root, (top, bottom) -> {
            column.setPadding(0, top, 0, 0);
            nav.setPadding(ui.dp(6), ui.dp(6), ui.dp(6), ui.dp(8) + bottom);
            FrameLayout.LayoutParams params = (FrameLayout.LayoutParams) toastView.getLayoutParams();
            params.bottomMargin = ui.dp(92) + bottom;
            toastView.setLayoutParams(params);
        });
        renderNav();
        renderLoading();
        return root;
    }

    private void renderNav() {
        nav.removeAllViews();
        addNav(PAGE_DEVICES, R.drawable.ic_nav_share, "Del");
        addNav(PAGE_TRANSFERS, R.drawable.ic_nav_transfers, "Overførsler");
        addNav(PAGE_HISTORY, R.drawable.ic_nav_history, "Historik");
        addNav(PAGE_SETTINGS, R.drawable.ic_nav_settings, "Indstillinger");
    }

    private void addNav(String key, int icon, String label) {
        boolean active = key.equals(page);
        LinearLayout item = ui.column();
        item.setGravity(Gravity.CENTER);
        item.setPadding(0, ui.dp(6), 0, ui.dp(4));
        item.setBackground(ui.ripple(ui.rounded(Color.TRANSPARENT, 0, 14), 14));
        item.setClickable(true);
        FrameLayout pillFrame = new FrameLayout(this);
        pillFrame.setBackground(ui.rounded(active ? ui.accentSoft : Color.TRANSPARENT, 0, 999));
        pillFrame.setPadding(ui.dp(18), ui.dp(4), ui.dp(18), ui.dp(4));
        pillFrame.addView(ui.icon(icon, active ? ui.accent : ui.muted, 22));
        if (PAGE_TRANSFERS.equals(key) && service != null && service.activeTransfers() > 0) {
            TextView badge = ui.text(String.valueOf(service.activeTransfers()), 10f, Color.WHITE, true);
            badge.setGravity(Gravity.CENTER);
            badge.setBackground(ui.rounded(ui.accent, 0, 999));
            badge.setPadding(ui.dp(5), 0, ui.dp(5), 0);
            FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ui.dp(16), Gravity.TOP | Gravity.END);
            badgeParams.setMargins(0, -ui.dp(2), -ui.dp(10), 0);
            pillFrame.addView(badge, badgeParams);
        }
        item.addView(pillFrame);
        TextView text = ui.text(label, 11.5f, active ? ui.text : ui.muted, active);
        text.setGravity(Gravity.CENTER);
        item.addView(text, ui.margins(0, 3, 0, 0));
        item.setOnClickListener(v -> {
            page = key;
            renderNav();
            render();
            scroll.scrollTo(0, 0);
        });
        nav.addView(item, ui.weight(1));
    }

    private void renderLoading() {
        content.removeAllViews();
        content.addView(header("h4xtor share", "Starter…", null));
    }

    // ------------------------------------------------------------------ render
    @Override
    public void onStateChanged() {
        if (!PAGE_SETTINGS.equals(page)) {
            render();
        } else {
            renderNav();
        }
    }

    private void render() {
        if (service == null) {
            return;
        }
        renderNav();
        content.removeAllViews();
        switch (page) {
            case PAGE_TRANSFERS: renderTransfers(); break;
            case PAGE_HISTORY: renderHistory(); break;
            case PAGE_SETTINGS: renderSettings(); break;
            default: renderDevices();
        }
    }

    private View header(String title, String subtitle, View action) {
        LinearLayout row = ui.row();
        row.setPadding(0, ui.dp(6), 0, ui.dp(18));
        LinearLayout texts = ui.column();
        texts.addView(ui.title(title, 27));
        if (subtitle != null) {
            LinearLayout status = ui.row();
            boolean ok = subtitle.startsWith("Online");
            TextView dot = ui.text("●", 11f, ok ? ui.success : ui.warning, false);
            status.addView(dot);
            TextView line = ui.text(subtitle, 13.5f, ui.muted, false);
            line.setSingleLine(true);
            line.setEllipsize(TextUtils.TruncateAt.END);
            status.addView(line, ui.margins(6, 0, 0, 0));
            texts.addView(status, ui.margins(0, 4, 0, 0));
        }
        row.addView(texts, ui.weight(1));
        if (action != null) {
            row.addView(action);
        }
        return row;
    }

    private String statusLine() {
        List<String> addresses = service.localAddresses();
        String status = service.status();
        if ("Online".equals(status)) {
            return addresses.isEmpty() ? "Online · intet netværk" : "Online · " + service.identity().deviceName()
                    + " · " + addresses.get(0);
        }
        return status;
    }

    private Peer selectedPeer() {
        Peer peer = service.peer(selectedId);
        if (peer != null && service.identity().isOutboundTrusted(peer.deviceId)) {
            return peer;
        }
        List<Peer> paired = service.pairedPeers();
        for (Peer candidate : paired) {
            if (service.isOnline(candidate.deviceId)) {
                return candidate;
            }
        }
        return paired.isEmpty() ? null : paired.get(0);
    }

    private void select(Peer peer) {
        selectedId = peer.deviceId;
        service.identity().setString("selected_peer", selectedId);
        render();
    }

    // ----------------------------------------------------------------- devices
    private void renderDevices() {
        TextView scan = ui.button("Scan QR", "soft");
        scan.setCompoundDrawablePadding(ui.dp(6));
        scan.setOnClickListener(v -> scanQr());
        content.addView(header("h4xtor share", statusLine(), scan));

        Peer target = selectedPeer();
        if (target != null) {
            content.addView(sendCard(target), ui.margins(0, 0, 0, 16));
        } else {
            content.addView(welcomeCard(), ui.margins(0, 0, 0, 16));
        }

        LinearLayout sectionRow = ui.row();
        sectionRow.addView(ui.label("Enheder"), ui.weight(1));
        TextView refresh = ui.text(service.isScanning()
                ? "Scanner " + Math.round(service.scanProgress() * 100) + "%"
                : "Scan netværk", 13.5f, ui.accent, true);
        refresh.setPadding(ui.dp(8), ui.dp(6), ui.dp(4), ui.dp(6));
        refresh.setOnClickListener(v -> {
            service.scanLan();
            service.restartDiscovery();
        });
        sectionRow.addView(refresh);
        content.addView(sectionRow, ui.margins(4, 8, 0, 8));

        List<Peer> peers = service.peers();
        if (peers.isEmpty()) {
            LinearLayout empty = ui.card();
            empty.addView(ui.text("Leder efter enheder…", 15.5f, ui.text, true));
            TextView hint = ui.text("Åbn h4xtor share på din PC eller en anden telefon på samme Wi-Fi. "
                    + "Den dukker op her af sig selv.", 13.5f, ui.muted, false);
            empty.addView(hint, ui.margins(0, 4, 0, 0));
            ProgressBar spinner = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
            spinner.setIndeterminate(true);
            spinner.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(ui.accent));
            empty.addView(spinner, ui.margins(0, 12, 0, 0));
            content.addView(empty);
        }
        for (Peer peer : peers) {
            content.addView(deviceCard(peer, target != null && target.deviceId.equals(peer.deviceId)),
                    ui.margins(0, 0, 0, 10));
        }

        content.addView(wifiDirectCard(), ui.margins(0, 14, 0, 0));
    }

    private View welcomeCard() {
        LinearLayout card = ui.card();
        card.setBackground(ui.rounded(ui.accentSoft, 0, 22));
        card.setPadding(ui.dp(20), ui.dp(20), ui.dp(20), ui.dp(20));
        card.addView(ui.title("Forbind din første enhed", 19));
        TextView text = ui.text("Åbn h4xtor share på PC'en, klik “Forbind ny enhed” og scan QR-koden. "
                + "Det tager fem sekunder – og kun første gang.", 14f, ui.muted, false);
        card.addView(text, ui.margins(0, 6, 0, 16));
        LinearLayout buttons = ui.row();
        TextView scan = ui.button("Scan QR-kode", "primary");
        scan.setOnClickListener(v -> scanQr());
        buttons.addView(scan, ui.weight(1));
        TextView mine = ui.button("Vis min kode", "secondary");
        mine.setOnClickListener(v -> showMyQr());
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(10), 0, 0, 0);
        buttons.addView(mine, params);
        card.addView(buttons);
        return card;
    }

    private View sendCard(Peer target) {
        LinearLayout card = ui.card();
        card.setPadding(ui.dp(18), ui.dp(18), ui.dp(18), ui.dp(18));
        LinearLayout top = ui.row();
        top.addView(ui.text("Send til", 13.5f, ui.muted, false));
        TextView chip = ui.text(target.name + "  ▾", 14.5f, ui.text, true);
        chip.setPadding(ui.dp(12), ui.dp(6), ui.dp(12), ui.dp(6));
        chip.setBackground(ui.ripple(ui.rounded(ui.surfaceAlt, 0, 999), 999));
        chip.setSingleLine(true);
        chip.setEllipsize(TextUtils.TruncateAt.END);
        chip.setOnClickListener(v -> choosePeer(this::select));
        LinearLayout.LayoutParams chipParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, 0f);
        chipParams.setMargins(ui.dp(8), 0, 0, 0);
        top.addView(chip, chipParams);
        View filler = new View(this);
        top.addView(filler, ui.weight(1));
        boolean online = service.isOnline(target.deviceId);
        top.addView(ui.pill(online ? "Online" : "Offline", online ? "success" : "neutral"));
        card.addView(top, ui.margins(0, 0, 0, 14));

        LinearLayout row1 = ui.row();
        row1.addView(actionTile(R.drawable.ic_file, "Filer", "Fotos, video, alt", v -> pickFiles(target)), ui.weight(1));
        LinearLayout.LayoutParams gap = ui.weight(1);
        gap.setMargins(ui.dp(10), 0, 0, 0);
        row1.addView(actionTile(R.drawable.ic_folder, "Mappe", "Hele mapper", v -> pickTree(target)), gap);
        card.addView(row1);
        LinearLayout row2 = ui.row();
        row2.addView(actionTile(R.drawable.ic_clipboard, "Udklipsholder", "Det du har kopieret",
                v -> sendClipboard(target)), ui.weight(1));
        LinearLayout.LayoutParams gap2 = ui.weight(1);
        gap2.setMargins(ui.dp(10), 0, 0, 0);
        row2.addView(actionTile(R.drawable.ic_link, "Tekst / link", "Åbner på PC'en",
                v -> composeText(target)), gap2);
        card.addView(row2, ui.margins(0, 10, 0, 0));
        return card;
    }

    private View actionTile(int icon, String title, String subtitle, View.OnClickListener click) {
        LinearLayout tile = ui.column();
        tile.setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(14));
        tile.setBackground(ui.ripple(ui.rounded(ui.surfaceAlt, 0, 16), 16));
        tile.setClickable(true);
        tile.setOnClickListener(click);
        tile.addView(ui.iconBadge(icon, 38, ui.accentSoft, ui.accent));
        tile.addView(ui.text(title, 15f, ui.text, true), ui.margins(0, 10, 0, 0));
        TextView sub = ui.text(subtitle, 12.5f, ui.muted, false);
        sub.setSingleLine(true);
        sub.setEllipsize(TextUtils.TruncateAt.END);
        tile.addView(sub, ui.margins(0, 1, 0, 0));
        return tile;
    }

    private View deviceCard(Peer peer, boolean selected) {
        boolean paired = service.identity().isOutboundTrusted(peer.deviceId);
        boolean online = service.isOnline(peer.deviceId);
        LinearLayout card = ui.card();
        card.setBackground(ui.ripple(ui.rounded(ui.surface, selected ? ui.accent : ui.border, 20), 20));
        card.setClickable(true);
        card.setOnClickListener(v -> {
            if (paired) {
                select(peer);
            } else {
                service.pair(peer);
                toast("Beder " + peer.name + " om en kode…", false);
            }
        });
        card.setOnLongClickListener(v -> {
            peerMenu(peer);
            return true;
        });
        LinearLayout row = ui.row();
        row.addView(ui.avatar(peer.platform, 44));
        LinearLayout texts = ui.column();
        TextView name = ui.text(peer.name, 16.5f, ui.text, true);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(name);
        String transport = "wifi-direct".equals(peer.transport) ? "Wi-Fi Direct" : "Wi-Fi";
        TextView meta = ui.text(Ui.platformLabel(peer.platform) + " · " + transport + " · " + peer.address,
                12.5f, ui.muted, false);
        meta.setSingleLine(true);
        meta.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(meta, ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams textParams = ui.weight(1);
        textParams.setMargins(ui.dp(14), 0, ui.dp(8), 0);
        row.addView(texts, textParams);
        if (online) {
            LinearLayout.LayoutParams barsParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ui.dp(16));
            barsParams.setMargins(0, 0, ui.dp(10), 0);
            row.addView(signalBars(service.rtt(peer.deviceId)), barsParams);
        }
        if (paired) {
            row.addView(ui.pill(online ? "Forbundet" : "Offline", online ? "success" : "neutral"));
        } else {
            TextView connect = ui.button("Forbind", "primary");
            connect.setMinHeight(ui.dp(38));
            connect.setTextSize(13.5f);
            connect.setOnClickListener(v -> {
                service.pair(peer);
                toast("Beder " + peer.name + " om en kode…", false);
            });
            row.addView(connect);
        }
        card.addView(row);
        return card;
    }

    private View signalBars(long rttMs) {
        int level = rttMs < 0 ? 0 : rttMs < 15 ? 4 : rttMs < 40 ? 3 : rttMs < 100 ? 2 : 1;
        LinearLayout bars = ui.row();
        bars.setGravity(Gravity.BOTTOM);
        for (int index = 0; index < 4; index++) {
            View bar = new View(this);
            bar.setBackground(ui.rounded(index < level ? ui.success : ui.track, 0, 1.5f));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ui.dp(3.5f), ui.dp(4 + index * 3.5f));
            params.setMargins(index == 0 ? 0 : ui.dp(2), 0, 0, 0);
            bars.addView(bar, params);
        }
        return bars;
    }

    private void peerMenu(Peer peer) {
        boolean paired = service.identity().isOutboundTrusted(peer.deviceId);
        List<String> labels = new ArrayList<>();
        List<Runnable> actions = new ArrayList<>();
        if (paired) {
            labels.add("Send filer");
            actions.add(() -> pickFiles(peer));
            labels.add("Send mappe");
            actions.add(() -> pickTree(peer));
            labels.add("Send tekst eller link");
            actions.add(() -> composeText(peer));
            if (service.wifiDirect().isActive() && peer.supports("wifi-direct-join")) {
                labels.add("Forbind direkte via Wi-Fi Direct");
                actions.add(() -> service.offerWifiDirect(peer));
            }
            labels.add("Glem enhed");
            actions.add(() -> confirmForget(peer));
        } else {
            labels.add("Forbind");
            actions.add(() -> service.pair(peer));
        }
        new AlertDialog.Builder(this)
                .setTitle(peer.name)
                .setItems(labels.toArray(new String[0]), (dialog, which) -> actions.get(which).run())
                .show();
    }

    private void confirmForget(Peer peer) {
        new AlertDialog.Builder(this)
                .setTitle("Glem " + peer.name + "?")
                .setMessage("I skal parre igen for at dele. Den anden enhed glemmer også denne telefon.")
                .setNegativeButton("Annullér", null)
                .setPositiveButton("Glem", (dialog, which) -> service.forget(peer))
                .show();
    }

    private View wifiDirectCard() {
        WifiDirectController direct = service.wifiDirect();
        LinearLayout card = ui.card();
        LinearLayout top = ui.row();
        top.addView(ui.iconBadge(R.drawable.ic_wifi, 40, direct.isActive() ? ui.successSoft : ui.accentSoft,
                direct.isActive() ? ui.success : ui.accent));
        LinearLayout texts = ui.column();
        texts.addView(ui.text(direct.isActive() ? "Wi-Fi Direct er aktiv" : "Ingen router? Brug Wi-Fi Direct",
                15.5f, ui.text, true));
        texts.addView(ui.text(direct.isActive()
                ? "Andre enheder kan forbinde direkte til denne telefon."
                : "Lynhurtig direkte forbindelse – også uden internet.", 12.5f, ui.muted, false));
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(14), 0, 0, 0);
        top.addView(texts, params);
        card.addView(top);
        if (!direct.isActive()) {
            TextView start = ui.button("Start Wi-Fi Direct", "secondary");
            start.setOnClickListener(v -> {
                if (hasWifiDirectPermission()) {
                    service.startWifiDirect();
                    toast("Starter Wi-Fi Direct…", false);
                }
            });
            card.addView(start, ui.margins(0, 14, 0, 0));
            return card;
        }
        LinearLayout info = ui.column();
        info.setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(12));
        info.setBackground(ui.rounded(ui.surfaceAlt, 0, 14));
        info.addView(ui.text("Netværk", 12f, ui.muted, false));
        TextView ssid = ui.text(direct.ssid(), 16f, ui.text, true);
        ssid.setTextIsSelectable(true);
        info.addView(ssid);
        info.addView(ui.text("Adgangskode", 12f, ui.muted, false), ui.margins(0, 8, 0, 0));
        TextView pass = ui.text(direct.passphrase(), 16f, ui.text, true);
        pass.setTextIsSelectable(true);
        pass.setTypeface(android.graphics.Typeface.MONOSPACE);
        info.addView(pass);
        card.addView(info, ui.margins(0, 14, 0, 0));

        List<Peer> desktops = new ArrayList<>();
        for (Peer peer : service.pairedPeers()) {
            if (peer.supports("wifi-direct-join")) {
                desktops.add(peer);
            }
        }
        for (Peer desktop : desktops) {
            TextView offer = ui.button("Forbind " + desktop.name + " automatisk", "primary");
            offer.setOnClickListener(v -> service.offerWifiDirect(desktop));
            card.addView(offer, ui.margins(0, 10, 0, 0));
        }
        LinearLayout buttons = ui.row();
        TextView qr = ui.button("Vis Wi-Fi QR", "secondary");
        qr.setOnClickListener(v -> showQrDialog("Forbind til Wi-Fi Direct",
                "Scan med en anden telefons kamera for at koble på netværket.", direct.wifiQrPayload(), null));
        buttons.addView(qr, ui.weight(1));
        TextView stop = ui.button("Stop", "ghost");
        stop.setOnClickListener(v -> service.stopWifiDirect());
        LinearLayout.LayoutParams stopParams = ui.weight(1);
        stopParams.setMargins(ui.dp(10), 0, 0, 0);
        buttons.addView(stop, stopParams);
        card.addView(buttons, ui.margins(0, 10, 0, 0));
        if (desktops.isEmpty()) {
            card.addView(ui.text("På PC'en: Indstillinger → Wi-Fi Direct → skriv netværk og kode.",
                    12.5f, ui.muted, false), ui.margins(0, 10, 0, 0));
        }
        return card;
    }

    // --------------------------------------------------------------- transfers
    private void renderTransfers() {
        TextView clear = ui.button("Ryd færdige", "ghost");
        clear.setOnClickListener(v -> service.clearFinished());
        content.addView(header("Overførsler", null, clear));
        List<ShareService.TransferItem> items = service.transfers();
        if (items.isEmpty()) {
            LinearLayout empty = ui.card();
            empty.addView(ui.text("Ingen overførsler endnu", 15.5f, ui.text, true));
            empty.addView(ui.text("Alt du sender og modtager vises her – live, og afbrudte overførsler "
                    + "fortsætter, hvor de slap.", 13.5f, ui.muted, false), ui.margins(0, 4, 0, 0));
            content.addView(empty);
            return;
        }
        for (ShareService.TransferItem item : items) {
            content.addView(transferCard(item), ui.margins(0, 0, 0, 10));
        }
    }

    private View transferCard(ShareService.TransferItem item) {
        LinearLayout card = ui.card();
        LinearLayout row = ui.row();
        row.addView(ui.iconBadge(item.folder ? R.drawable.ic_folder : R.drawable.ic_file, 40,
                item.outgoing ? ui.accentSoft : ui.successSoft, item.outgoing ? ui.accent : ui.success));
        LinearLayout texts = ui.column();
        TextView name = ui.text(item.name, 15f, ui.text, true);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        texts.addView(name);
        String direction = (item.outgoing ? "Til " : "Fra ") + item.peerName;
        String detail;
        switch (item.status) {
            case "done":
                detail = direction + " · Færdig · " + Ui.formatBytes(item.total);
                break;
            case "cancelled":
                detail = direction + " · Annulleret";
                break;
            case "failed":
                detail = direction + " · Mislykkedes";
                break;
            default:
                detail = direction + " · " + Math.round(item.fraction() * 100) + "% · "
                        + Ui.formatBytes(item.sent) + " af " + Ui.formatBytes(item.total);
                if (item.speed > 0) {
                    detail += " · " + Ui.formatBytes((long) item.speed) + "/s";
                    String eta = Ui.formatEta((item.total - item.sent) / item.speed);
                    if (!eta.isEmpty()) {
                        detail += " · " + eta;
                    }
                }
        }
        TextView meta = ui.text(detail, 12.5f, "failed".equals(item.status) ? ui.danger : ui.muted, false);
        texts.addView(meta, ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(14), 0, 0, 0);
        row.addView(texts, params);
        card.addView(row);
        if ("active".equals(item.status) || "failed".equals(item.status) || "cancelled".equals(item.status)) {
            ProgressBar bar = ui.progress();
            bar.setProgress((int) Math.round(item.fraction() * 1000));
            if (!"active".equals(item.status)) {
                bar.setProgressTintList(android.content.res.ColorStateList.valueOf(
                        "failed".equals(item.status) ? ui.danger : ui.faint));
            }
            card.addView(bar, ui.margins(0, 12, 0, 0));
        }
        LinearLayout actions = ui.row();
        actions.setGravity(Gravity.END);
        if ("active".equals(item.status) && item.outgoing) {
            TextView cancel = ui.button("Annullér", "ghost");
            cancel.setMinHeight(ui.dp(36));
            cancel.setOnClickListener(v -> service.cancel(item.id));
            actions.addView(cancel);
        }
        if (item.outgoing && ("failed".equals(item.status) || "cancelled".equals(item.status))) {
            TextView retry = ui.button("Fortsæt", "soft");
            retry.setMinHeight(ui.dp(36));
            retry.setOnClickListener(v -> service.retry(item.id));
            actions.addView(retry);
        }
        if ("done".equals(item.status) && !item.outgoing) {
            TextView open = ui.button(item.folder ? "Vis i Filer" : "Åbn", "soft");
            open.setMinHeight(ui.dp(36));
            open.setOnClickListener(v -> {
                if (item.folder || item.uri.isEmpty()) {
                    openDownloads();
                } else {
                    openFile(Uri.parse(item.uri), item.name);
                }
            });
            actions.addView(open);
        }
        if (actions.getChildCount() > 0) {
            card.addView(actions, ui.margins(0, 8, 0, 0));
        }
        return card;
    }

    // ----------------------------------------------------------------- history
    private void renderHistory() {
        content.addView(header("Historik", null, null));
        LinearLayout segments = ui.row();
        segments.setPadding(ui.dp(4), ui.dp(4), ui.dp(4), ui.dp(4));
        segments.setBackground(ui.rounded(ui.surfaceAlt, 0, 14));
        for (String[] option : new String[][]{{"received", "Modtaget"}, {"sent", "Sendt"}, {"devices", "Enheder"}}) {
            boolean active = option[0].equals(historyMode);
            TextView tab = ui.text(option[1], 14f, active ? ui.text : ui.muted, active);
            tab.setGravity(Gravity.CENTER);
            tab.setPadding(0, ui.dp(9), 0, ui.dp(9));
            tab.setBackground(active ? ui.rounded(ui.surface, ui.border, 11) : null);
            tab.setOnClickListener(v -> {
                historyMode = option[0];
                render();
            });
            segments.addView(tab, ui.weight(1));
        }
        content.addView(segments, ui.margins(0, 0, 0, 14));

        JSONArray list = service.identity().history(historyMode);
        if (list.length() == 0) {
            content.addView(ui.text("Intet endnu.", 14f, ui.muted, false), ui.margins(4, 8, 0, 0));
            return;
        }
        LinearLayout card = ui.card();
        card.setPadding(ui.dp(6), ui.dp(4), ui.dp(6), ui.dp(4));
        int shown = 0;
        for (int index = list.length() - 1; index >= 0 && shown < 120; index--, shown++) {
            JSONObject entry = list.optJSONObject(index);
            if (entry == null) {
                continue;
            }
            if (shown > 0) {
                View line = new View(this);
                line.setBackgroundColor(ui.border);
                card.addView(line, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                        Math.max(1, ui.dp(1))));
            }
            card.addView(historyRow(entry));
        }
        content.addView(card);
    }

    private View historyRow(JSONObject entry) {
        LinearLayout row = ui.row();
        row.setPadding(ui.dp(12), ui.dp(12), ui.dp(12), ui.dp(12));
        row.setBackground(ui.ripple(ui.rounded(Color.TRANSPARENT, 0, 12), 12));
        String kind = entry.optString("kind", "");
        int icon;
        if ("devices".equals(historyMode)) {
            row.addView(ui.avatar(entry.optString("os"), 34));
        } else {
            switch (kind) {
                case "folder": icon = R.drawable.ic_folder; break;
                case "link": icon = R.drawable.ic_link; break;
                case "clipboard": icon = R.drawable.ic_clipboard; break;
                default: icon = R.drawable.ic_file;
            }
            row.addView(ui.iconBadge(icon, 34, ui.surfaceAlt, ui.muted));
        }
        LinearLayout texts = ui.column();
        String title = "devices".equals(historyMode) ? entry.optString("name") : entry.optString("text");
        TextView main = ui.text(title.replace('\n', ' '), 14.5f, ui.text, true);
        main.setSingleLine(true);
        main.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(main);
        String subtitle = "devices".equals(historyMode)
                ? entry.optString("ip") + " · " + Ui.platformLabel(entry.optString("os")) + " · " + entry.optString("ts")
                : entry.optString("peer") + " · " + entry.optString("ts")
                + (entry.optLong("size", 0) > 0 ? " · " + Ui.formatBytes(entry.optLong("size")) : "");
        TextView sub = ui.text(subtitle, 12f, ui.muted, false);
        sub.setSingleLine(true);
        sub.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(sub, ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(12), 0, 0, 0);
        row.addView(texts, params);
        row.setOnClickListener(v -> {
            String text = entry.optString("text");
            if ("link".equals(kind)) {
                openUrl(text);
            } else if ("clipboard".equals(kind)) {
                copy(text);
            } else if ("file".equals(kind) && !entry.optString("uri").isEmpty()) {
                openFile(Uri.parse(entry.optString("uri")), text);
            } else if ("folder".equals(kind) || "file".equals(kind)) {
                openDownloads();
            }
        });
        return row;
    }

    // ---------------------------------------------------------------- settings
    private void renderSettings() {
        AppIdentity identity = service.identity();
        content.addView(header("Indstillinger", null, null));

        content.addView(ui.label("Denne telefon"), ui.margins(4, 0, 0, 8));
        LinearLayout device = ui.card();
        device.addView(ui.text("Navn som andre ser", 12.5f, ui.muted, false));
        LinearLayout nameRow = ui.row();
        EditText name = new EditText(this);
        name.setText(identity.deviceName());
        name.setSingleLine(true);
        name.setTextColor(ui.text);
        name.setTextSize(15.5f);
        name.setImeOptions(EditorInfo.IME_ACTION_DONE);
        name.setBackground(ui.rounded(ui.surfaceAlt, 0, 12));
        name.setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10));
        nameRow.addView(name, ui.weight(1));
        TextView save = ui.button("Gem", "soft");
        save.setOnClickListener(v -> {
            try {
                service.renameDevice(name.getText().toString());
                toast("Navnet er gemt", false);
            } catch (Exception error) {
                toast(H4xtorClient.safeMessage(error), true);
            }
        });
        LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        saveParams.setMargins(ui.dp(10), 0, 0, 0);
        nameRow.addView(save, saveParams);
        device.addView(nameRow, ui.margins(0, 6, 0, 0));
        TextView myQr = ui.button("Vis min QR-kode", "secondary");
        myQr.setOnClickListener(v -> showMyQr());
        device.addView(myQr, ui.margins(0, 12, 0, 0));
        content.addView(device, ui.margins(0, 0, 0, 18));

        content.addView(ui.label("Udklipsholder og links"), ui.margins(4, 0, 0, 8));
        LinearLayout sync = ui.card();
        sync.addView(toggleRow("Synkronisér udklipsholder",
                "Det du kopierer, sendes til dine enheder, når h4xtor share er åben.",
                identity.isClipboardSyncEnabled(), identity::setClipboardSyncEnabled));
        sync.addView(ui.divider());
        sync.addView(toggleRow("Indsæt modtaget tekst automatisk",
                "Tekst fra PC'en er klar til at indsætte med det samme.",
                identity.flag("apply_clipboard", true), value -> identity.setFlag("apply_clipboard", value)));
        sync.addView(ui.divider());
        sync.addView(toggleRow("Åbn modtagne links",
                "Links fra PC'en åbner direkte i browseren.",
                identity.flag("open_links", true), value -> identity.setFlag("open_links", value)));
        content.addView(sync, ui.margins(0, 0, 0, 18));

        content.addView(ui.label("Baggrund"), ui.margins(4, 0, 0, 8));
        LinearLayout background = ui.card();
        background.addView(toggleRow("Kør i baggrunden",
                "Modtag filer og links, selv når appen er lukket.",
                identity.flag("run_in_background", true), value -> {
                    identity.setFlag("run_in_background", value);
                    if (value) {
                        ShareService.start(this);
                    }
                }));
        background.addView(ui.divider());
        background.addView(toggleRow("Start når telefonen tænder",
                "h4xtor share er klar uden at du skal åbne den.",
                identity.flag("start_on_boot", false), value -> identity.setFlag("start_on_boot", value)));
        background.addView(ui.divider());
        TextView tileHint = ui.text("Tip: Tilføj “Send udklipsholder” til Kvikindstillinger – træk ned fra toppen, "
                + "tryk på blyanten og træk feltet op.", 12.5f, ui.muted, false);
        background.addView(tileHint);
        content.addView(background, ui.margins(0, 0, 0, 18));

        content.addView(ui.label("Forbundne enheder"), ui.margins(4, 0, 0, 8));
        LinearLayout paired = ui.card();
        List<Peer> peers = service.pairedPeers();
        if (peers.isEmpty()) {
            paired.addView(ui.text("Ingen endnu. Scan QR-koden på din PC for at komme i gang.", 13.5f, ui.muted, false));
        }
        for (int index = 0; index < peers.size(); index++) {
            Peer peer = peers.get(index);
            if (index > 0) {
                paired.addView(ui.divider());
            }
            LinearLayout row = ui.row();
            row.addView(ui.avatar(peer.platform, 34));
            TextView label = ui.text(peer.name, 15f, ui.text, true);
            LinearLayout.LayoutParams params = ui.weight(1);
            params.setMargins(ui.dp(12), 0, 0, 0);
            row.addView(label, params);
            TextView forget = ui.button("Glem", "danger");
            forget.setMinHeight(ui.dp(36));
            forget.setOnClickListener(v -> confirmForget(peer));
            row.addView(forget);
            paired.addView(row);
        }
        content.addView(paired, ui.margins(0, 0, 0, 18));

        content.addView(ui.label("Om"), ui.margins(4, 0, 0, 8));
        LinearLayout about = ui.card();
        about.addView(ui.text("h4xtor share " + AppIdentity.VERSION, 15f, ui.text, true));
        String fingerprint;
        try {
            fingerprint = identity.fingerprint().substring(0, 16);
        } catch (Exception error) {
            fingerprint = "?";
        }
        about.addView(ui.text("Helt lokalt – ingen konto, ingen sky. Alt krypteres og låses til hver enheds "
                + "certifikat.\nCertifikat " + fingerprint + "…", 12.5f, ui.muted, false), ui.margins(0, 4, 0, 0));
        TextView manual = ui.button("Tilføj enhed via IP-adresse", "ghost");
        manual.setOnClickListener(v -> addByIp());
        about.addView(manual, ui.margins(0, 10, 0, 0));
        content.addView(about);
    }

    private interface Toggled {
        void set(boolean value);
    }

    private View toggleRow(String title, String subtitle, boolean value, Toggled toggled) {
        LinearLayout row = ui.row();
        LinearLayout texts = ui.column();
        texts.addView(ui.text(title, 15f, ui.text, true));
        texts.addView(ui.text(subtitle, 12.5f, ui.muted, false), ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(0, 0, ui.dp(12), 0);
        row.addView(texts, params);
        Switch toggle = ui.toggle(value);
        toggle.setOnCheckedChangeListener((button, checked) -> toggled.set(checked));
        row.addView(toggle);
        row.setOnClickListener(v -> toggle.toggle());
        return row;
    }

    // ----------------------------------------------------------------- actions
    private interface PeerChosen {
        void chosen(Peer peer);
    }

    private void choosePeer(PeerChosen callback) {
        List<Peer> paired = service.pairedPeers();
        if (paired.isEmpty()) {
            scanQr();
            return;
        }
        String[] names = new String[paired.size()];
        for (int index = 0; index < paired.size(); index++) {
            Peer peer = paired.get(index);
            names[index] = peer.name + (service.isOnline(peer.deviceId) ? "  ·  online" : "  ·  offline");
        }
        new AlertDialog.Builder(this)
                .setTitle("Vælg enhed")
                .setItems(names, (dialog, which) -> callback.chosen(paired.get(which)))
                .show();
    }

    private void pickFiles(Peer peer) {
        pendingPeerId = peer.deviceId;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(intent, REQUEST_FILES);
    }

    private void pickTree(Peer peer) {
        if (!peer.supports("folders")) {
            toast(peer.name + " kan ikke modtage mapper", true);
            return;
        }
        pendingPeerId = peer.deviceId;
        startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), REQUEST_TREE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || service == null) {
            return;
        }
        Peer peer = service.peer(pendingPeerId);
        pendingPeerId = null;
        if (peer == null) {
            return;
        }
        if (requestCode == REQUEST_FILES) {
            List<Uri> uris = new ArrayList<>();
            ClipData clip = data.getClipData();
            if (clip != null) {
                for (int index = 0; index < clip.getItemCount(); index++) {
                    uris.add(clip.getItemAt(index).getUri());
                }
            } else if (data.getData() != null) {
                uris.add(data.getData());
            }
            if (!uris.isEmpty()) {
                service.sendUris(peer, uris);
                toast("Sender " + uris.size() + (uris.size() == 1 ? " fil" : " filer") + " til " + peer.name, false);
                page = PAGE_TRANSFERS;
                render();
            }
        } else if (requestCode == REQUEST_TREE && data.getData() != null) {
            service.sendTree(peer, data.getData());
            toast("Sender mappe til " + peer.name, false);
            page = PAGE_TRANSFERS;
            render();
        }
    }

    private void sendClipboard(Peer peer) {
        String text = service.currentClipboard();
        if (text == null || text.trim().isEmpty()) {
            toast("Udklipsholderen er tom", true);
            return;
        }
        service.sendText(peer, text);
    }

    private void composeText(Peer peer) {
        EditText input = new EditText(this);
        input.setHint("Skriv tekst eller indsæt et link");
        input.setMinLines(3);
        input.setGravity(Gravity.TOP);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        String clip = service.currentClipboard();
        if (clip != null && clip.length() < 4000) {
            input.setText(clip);
            input.selectAll();
        }
        FrameLayout wrapper = new FrameLayout(this);
        wrapper.setPadding(ui.dp(20), ui.dp(8), ui.dp(20), 0);
        wrapper.addView(input);
        new AlertDialog.Builder(this)
                .setTitle("Send til " + peer.name)
                .setMessage("Links åbner i browseren. Tekst lander i udklipsholderen.")
                .setView(wrapper)
                .setNegativeButton("Annullér", null)
                .setPositiveButton("Send", (dialog, which) -> service.sendText(peer, input.getText().toString()))
                .show();
    }

    private void addByIp() {
        EditText input = new EditText(this);
        input.setHint("192.168.1.20");
        input.setInputType(InputType.TYPE_CLASS_PHONE);
        FrameLayout wrapper = new FrameLayout(this);
        wrapper.setPadding(ui.dp(20), ui.dp(8), ui.dp(20), 0);
        wrapper.addView(input);
        new AlertDialog.Builder(this)
                .setTitle("Tilføj via IP-adresse")
                .setView(wrapper)
                .setNegativeButton("Annullér", null)
                .setPositiveButton("Tilføj", (dialog, which) -> {
                    String value = input.getText().toString().trim();
                    if (!value.isEmpty()) {
                        service.probe(value, AppIdentity.PORT, true);
                        page = PAGE_DEVICES;
                        render();
                    }
                })
                .show();
    }

    private void scanQr() {
        QrScanner.scan(this, new QrScanner.Result() {
            @Override
            public void onScanned(String value) {
                if (PairingInvite.looksLikeInvite(value)) {
                    service.pairWithInvite(value);
                } else if (Ui.isLink(value)) {
                    toast("Det er et almindeligt link – ikke en h4xtor share-kode", true);
                } else {
                    toast("Det er ikke en h4xtor share-kode", true);
                }
            }

            @Override
            public void onUnavailable(String reason) {
                toast(reason, true);
            }
        });
    }

    private void showMyQr() {
        PairingInvite invite = service.newInvite();
        if (invite == null || invite.addresses.isEmpty()) {
            toast("Forbind til Wi-Fi først", true);
            return;
        }
        String uri = invite.toUri();
        showQrDialog("Forbind til denne telefon", "Scan med h4xtor share på en anden telefon – eller del "
                + "linket til en computer.", uri, () -> {
            Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, uri);
            startActivity(Intent.createChooser(share, "Del parringslink"));
        });
    }

    private void showQrDialog(String title, String subtitle, String payload, Runnable share) {
        LinearLayout layout = ui.column();
        layout.setGravity(Gravity.CENTER_HORIZONTAL);
        layout.setPadding(ui.dp(24), ui.dp(8), ui.dp(24), ui.dp(4));
        TextView sub = ui.text(subtitle, 13.5f, ui.muted, false);
        sub.setGravity(Gravity.CENTER);
        layout.addView(sub, ui.margins(0, 0, 0, 16));
        FrameLayout frame = new FrameLayout(this);
        frame.setBackground(ui.rounded(Color.WHITE, ui.border, 18));
        frame.setPadding(ui.dp(10), ui.dp(10), ui.dp(10), ui.dp(10));
        QrCodeView qr = new QrCodeView(this);
        qr.setContent(payload);
        frame.addView(qr, new FrameLayout.LayoutParams(ui.dp(240), ui.dp(240)));
        layout.addView(frame, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(title)
                .setView(layout)
                .setPositiveButton("Luk", null);
        if (share != null) {
            builder.setNeutralButton("Del link", (dialog, which) -> share.run());
        }
        qrDialog = builder.show();
    }

    private void openFile(Uri uri, String name) {
        try {
            startActivity(Ui.openFileIntent(uri, name));
        } catch (ActivityNotFoundException error) {
            toast("Ingen app kan åbne " + name, true);
        } catch (Exception error) {
            toast("Filen findes ikke længere", true);
        }
    }

    private void openDownloads() {
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(MediaStore.Downloads.EXTERNAL_CONTENT_URI, "vnd.android.document/directory");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
        } catch (Exception error) {
            try {
                startActivity(new Intent(android.app.DownloadManager.ACTION_VIEW_DOWNLOADS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } catch (Exception ignored) {
                toast("Filerne ligger i Overførsler/h4xtor-share", false);
            }
        }
    }

    private void openUrl(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception error) {
            toast("Ingen browser fundet", true);
        }
    }

    private void copy(String text) {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        clipboard.setPrimaryClip(ClipData.newPlainText("h4xtor share", text));
        toast("Kopieret", false);
    }

    // ------------------------------------------------------------ UiListener
    @Override
    public void onMessage(String text, boolean error) {
        toast(text, error);
    }

    @Override
    public void onPairingCode(String peerName, String code, long expiresAt) {
        if (codeDialog != null && codeDialog.isShowing()) {
            codeDialog.dismiss();
        }
        LinearLayout layout = ui.column();
        layout.setGravity(Gravity.CENTER_HORIZONTAL);
        layout.setPadding(ui.dp(24), ui.dp(4), ui.dp(24), 0);
        TextView sub = ui.text("Skriv koden på " + peerName + ". Afvis, hvis det ikke var dig.", 14f, ui.muted, false);
        sub.setGravity(Gravity.CENTER);
        layout.addView(sub);
        TextView digits = ui.title(code.substring(0, 3) + " " + code.substring(3), 40);
        digits.setTextColor(ui.accent);
        digits.setTypeface(android.graphics.Typeface.create(android.graphics.Typeface.MONOSPACE,
                android.graphics.Typeface.BOLD));
        digits.setLetterSpacing(0.08f);
        layout.addView(digits, ui.margins(0, 18, 0, 6));
        codeDialog = new AlertDialog.Builder(this)
                .setTitle(peerName + " vil forbinde")
                .setView(layout)
                .setNegativeButton("Afvis", (dialog, which) -> service.rejectPairing(code))
                .setPositiveButton("OK", null)
                .show();
        content.postDelayed(() -> {
            if (codeDialog != null && codeDialog.isShowing()) {
                codeDialog.dismiss();
            }
        }, Math.max(1000, expiresAt - System.currentTimeMillis()));
    }

    @Override
    public void onNeedCode(Peer peer, String pairingId) {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_NUMBER);
        input.setHint("123456");
        input.setGravity(Gravity.CENTER);
        input.setTextSize(30f);
        input.setLetterSpacing(0.2f);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(6)});
        FrameLayout wrapper = new FrameLayout(this);
        wrapper.setPadding(ui.dp(24), ui.dp(8), ui.dp(24), 0);
        wrapper.addView(input);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Forbind med " + peer.name)
                .setMessage("Skriv den 6-cifrede kode, der står på " + peer.name + ".")
                .setView(wrapper)
                .setNegativeButton("Annullér", null)
                .setPositiveButton("Forbind", (d, which) -> {
                    String code = input.getText().toString().trim();
                    if (code.matches("\\d{6}")) {
                        service.confirmPairing(peer, pairingId, code);
                    } else {
                        toast("Koden har 6 cifre", true);
                    }
                })
                .create();
        input.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { }

            @Override
            public void afterTextChanged(android.text.Editable s) {
                if (s.length() == 6 && dialog.isShowing()) {
                    dialog.dismiss();
                    service.confirmPairing(peer, pairingId, s.toString());
                }
            }
        });
        dialog.show();
        input.requestFocus();
    }

    @Override
    public void onLinkReceived(String peerName, String url) {
        toast("Link fra " + peerName, false);
        openUrl(url);
    }

    private final Runnable hideToast = () -> toastView.animate().alpha(0f).setDuration(200)
            .withEndAction(() -> toastView.setVisibility(View.GONE)).start();

    private void toast(String text, boolean error) {
        if (toastView == null) {
            Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
            return;
        }
        toastView.removeCallbacks(hideToast);
        toastView.setText(text);
        GradientDrawable background = ui.rounded(error ? ui.danger : ui.text, 0, 16);
        toastView.setBackground(background);
        toastView.setTextColor(error ? Color.WHITE : ui.bg);
        toastView.setAlpha(0f);
        toastView.setVisibility(View.VISIBLE);
        toastView.animate().alpha(1f).setDuration(160).start();
        toastView.postDelayed(hideToast, error ? 4500 : 2600);
    }

    static String lower(String value) {
        return value.toLowerCase(Locale.ROOT);
    }
}
