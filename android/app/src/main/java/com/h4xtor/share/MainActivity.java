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
    private static final int REQUEST_MEDIA_PERMISSION = 2005;

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
    private EditText composerInput;
    private android.widget.ImageView sendButton;
    private String dismissedClip;
    private boolean renderPending;

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
            if (PAGE_DEVICES.equals(page)) {
                render();
            }
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
        String[] permissions = Build.VERSION.SDK_INT >= 33
                ? new String[]{Manifest.permission.NEARBY_WIFI_DEVICES}
                : new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION};
        if (checkSelfPermission(permissions[0]) == PackageManager.PERMISSION_GRANTED) {
            return true;
        }
        requestPermissions(permissions, REQUEST_WIFI_PERMISSION);
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
        if (requestCode == REQUEST_MEDIA_PERMISSION && service != null) {
            boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (granted) {
                service.setAutoScreenshots(true);
                toast("Nye skærmbilleder sendes automatisk", false);
            } else {
                toast("Kræver adgang til billeder – kun for at finde nye skærmbilleder", true);
            }
            render();
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
        if (composerInput != null && composerInput.hasFocus() && PAGE_DEVICES.equals(page)) {
            // Never rebuild the screen under the user's fingers while typing.
            renderPending = true;
            renderNav();
            return;
        }
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
        if (service.identity().flag("keep_screen_on", true) && service.activeTransfers() > 0) {
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        } else {
            getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
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
            status.addView(line, ui.wrap(6, 0, 0, 0));
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
        content.addView(topBar(), ui.matchWrap());
        Peer target = selectedPeer();
        content.addView(greeting(target), ui.margins(2, 22, 0, 18));
        View live = liveTransfersCard();
        if (live != null) {
            content.addView(live, ui.margins(0, 0, 0, 12));
        }
        if (target != null) {
            content.addView(composer(target), ui.margins(0, 0, 0, 12));
            View suggestion = clipboardSuggestion(target);
            if (suggestion != null) {
                content.addView(suggestion, ui.margins(0, 0, 0, 12));
            }
        } else {
            content.addView(welcomeCard(), ui.margins(0, 0, 0, 12));
        }

        List<Peer> peers = service.peers();
        List<Peer> paired = new ArrayList<>();
        List<Peer> lan = new ArrayList<>();
        for (Peer peer : peers) {
            (service.identity().isOutboundTrusted(peer.deviceId) ? paired : lan).add(peer);
        }

        LinearLayout sectionRow = ui.row();
        sectionRow.addView(ui.label("Dine enheder"), ui.weight(1));
        TextView refresh = ui.text(service.isScanning()
                ? "Scanner " + Math.round(service.scanProgress() * 100) + "%"
                : "Opdatér", 13.5f, ui.accent, true);
        refresh.setPadding(ui.dp(10), ui.dp(6), ui.dp(4), ui.dp(6));
        refresh.setOnClickListener(v -> {
            service.scanLan();
            service.restartDiscovery();
        });
        sectionRow.addView(refresh);
        content.addView(sectionRow, ui.margins(6, 14, 0, 6));

        if (paired.isEmpty()) {
            LinearLayout empty = ui.card();
            LinearLayout line = ui.row();
            ProgressBar spinner = new ProgressBar(this);
            spinner.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(ui.accent));
            line.addView(spinner, new LinearLayout.LayoutParams(ui.dp(20), ui.dp(20)));
            LinearLayout texts = ui.column();
            texts.addView(ui.text(lan.isEmpty() ? "Leder efter enheder…" : "Ingen forbundne enheder endnu",
                    15f, ui.text, true));
            texts.addView(ui.text(lan.isEmpty()
                    ? "Åbn h4xtor share på din PC på samme Wi-Fi."
                    : "Tryk Forbind herunder – eller scan QR-koden på PC'en.", 13f, ui.muted, false));
            LinearLayout.LayoutParams textParams = ui.weight(1);
            textParams.setMargins(ui.dp(14), 0, 0, 0);
            line.addView(texts, textParams);
            empty.addView(line);
            content.addView(empty);
        } else {
            content.addView(deviceGroup(paired, target));
        }

        if (!lan.isEmpty()) {
            content.addView(ui.label("Fundet på netværket · ikke forbundet"), ui.margins(6, 20, 0, 6));
            content.addView(deviceGroup(lan, null));
        }

        content.addView(wifiDirectCard(), ui.margins(0, 20, 0, 0));
    }

    /** "Overfører nu" with live progress, right on the home screen. */
    private View liveTransfersCard() {
        List<ShareService.TransferItem> active = new ArrayList<>();
        for (ShareService.TransferItem item : service.transfers()) {
            if ("active".equals(item.status)) {
                active.add(item);
            }
        }
        if (active.isEmpty()) {
            return null;
        }
        LinearLayout card = ui.card();
        card.setBackground(ui.ripple(ui.rounded(ui.surface, ui.accent, 20), 20));
        card.setClickable(true);
        card.setOnClickListener(v -> {
            page = PAGE_TRANSFERS;
            render();
        });
        LinearLayout head = ui.row();
        head.addView(ui.label("Overfører nu · " + active.size()), ui.weight(1));
        double total = 0;
        for (ShareService.TransferItem item : active) {
            total += item.speed;
        }
        TextView speed = ui.text(Ui.formatSpeed(total), 13f, ui.accent, true);
        speed.setFontFeatureSettings("tnum");
        head.addView(speed);
        card.addView(head);
        for (int index = 0; index < Math.min(3, active.size()); index++) {
            ShareService.TransferItem item = active.get(index);
            LinearLayout line = ui.row();
            TextView name = ui.text((item.outgoing ? "↑ " : "↓ ") + item.name, 14f, ui.text, true);
            name.setSingleLine(true);
            name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            line.addView(name, ui.weight(1));
            TextView pct = ui.text(Math.round(item.fraction() * 100) + "%", 14f, ui.text, true);
            pct.setFontFeatureSettings("tnum");
            line.addView(pct, ui.wrap(8, 0, 0, 0));
            card.addView(line, ui.margins(0, 10, 0, 0));
            ProgressBar bar = ui.progress();
            bar.setProgress((int) Math.round(item.fraction() * 1000));
            card.addView(bar, ui.margins(0, 6, 0, 0));
            String eta = item.speed > 0 ? Ui.formatEta((item.total - item.sent) / item.speed) : "";
            TextView sub = ui.text(Ui.formatBytes(item.sent) + " af " + Ui.formatBytes(item.total)
                    + (item.speed > 0 ? " · " + Ui.formatSpeed(item.speed) : "")
                    + (eta.isEmpty() ? "" : " · " + eta), 12f, ui.muted, false);
            sub.setFontFeatureSettings("tnum");
            card.addView(sub, ui.margins(0, 4, 0, 0));
        }
        SpeedGraph graph = new SpeedGraph(this, ui.accent, ui.border);
        graph.setSamples(active.get(0).samples());
        card.addView(graph, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(44)));
        return card;
    }

    private View topBar() {
        LinearLayout bar = ui.row();
        TextView mark = ui.text("✻", 22f, ui.accent, true);
        bar.addView(mark);
        LinearLayout.LayoutParams nameParams = ui.weight(1);
        nameParams.setMargins(ui.dp(8), 0, ui.dp(8), 0);
        bar.addView(ui.text("h4xtor share", 16.5f, ui.text, true), nameParams);

        boolean online = "Online".equals(service.status());
        LinearLayout status = ui.row();
        status.setPadding(ui.dp(10), ui.dp(5), ui.dp(12), ui.dp(5));
        status.setBackground(ui.rounded(online ? ui.successSoft : ui.warningSoft, 0, 999));
        View dot = new View(this);
        dot.setBackground(ui.rounded(online ? ui.success : ui.warning, 0, 999));
        status.addView(dot, new LinearLayout.LayoutParams(ui.dp(7), ui.dp(7)));
        List<String> addresses = service.localAddresses();
        String label = online ? (addresses.isEmpty() ? "Intet netværk" : "Online") : service.status();
        status.addView(ui.text(label, 12.5f, online ? ui.success : ui.warning, true), ui.wrap(6, 0, 0, 0));
        status.setOnClickListener(v -> toast(statusLine(), false));
        bar.addView(status);

        android.widget.ImageView scan = ui.icon(R.drawable.ic_scan, ui.text, 20);
        scan.setScaleType(android.widget.ImageView.ScaleType.CENTER);
        scan.setBackground(ui.ripple(ui.rounded(ui.surface, ui.border, 999), 999));
        scan.setContentDescription("Scan QR-kode");
        scan.setOnClickListener(v -> scanQr());
        LinearLayout.LayoutParams scanParams = new LinearLayout.LayoutParams(ui.dp(40), ui.dp(40));
        scanParams.setMargins(ui.dp(10), 0, 0, 0);
        bar.addView(scan, scanParams);
        return bar;
    }

    private View greeting(Peer target) {
        LinearLayout box = ui.column();
        LinearLayout headline = ui.row();
        headline.addView(ui.title("Velkommen til\nH4xtor Share", 31), ui.weight(1));
        android.widget.ImageView monkey = new android.widget.ImageView(this);
        monkey.setImageResource(R.drawable.ic_monkey);
        monkey.setContentDescription("H4xtor Share-aben");
        LinearLayout.LayoutParams monkeyParams = new LinearLayout.LayoutParams(ui.dp(84), ui.dp(84));
        monkeyParams.setMargins(ui.dp(12), 0, 0, 0);
        headline.addView(monkey, monkeyParams);
        box.addView(headline);
        if (target != null) {
            boolean online = service.isOnline(target.deviceId);
            box.addView(ui.text(online
                    ? "Alt du sender, lander med det samme på " + target.name + "."
                    : target.name + " er offline – åbn h4xtor share på den.", 14f, ui.muted, false),
                    ui.margins(0, 8, 0, 0));
        }
        return box;
    }

    private EditText composerInput() {
        if (composerInput == null) {
            composerInput = new EditText(this);
            composerInput.setHint("Skriv tekst eller indsæt et link…");
            composerInput.setTextSize(16.5f);
            composerInput.setTextColor(ui.text);
            composerInput.setHintTextColor(ui.faint);
            composerInput.setBackground(null);
            composerInput.setPadding(ui.dp(2), ui.dp(4), ui.dp(2), ui.dp(4));
            composerInput.setMinLines(2);
            composerInput.setMaxLines(7);
            composerInput.setGravity(Gravity.TOP | Gravity.START);
            composerInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                    | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            composerInput.addTextChangedListener(new android.text.TextWatcher() {
                @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
                @Override public void onTextChanged(CharSequence s, int start, int before, int count) { }
                @Override public void afterTextChanged(android.text.Editable s) {
                    styleSendButton();
                }
            });
            composerInput.setOnFocusChangeListener((v, focused) -> {
                if (!focused && renderPending) {
                    renderPending = false;
                    render();
                }
            });
        }
        ViewGroup parent = (ViewGroup) composerInput.getParent();
        if (parent != null) {
            parent.removeView(composerInput);
        }
        return composerInput;
    }

    private View composer(Peer target) {
        LinearLayout card = ui.column();
        card.setPadding(ui.dp(16), ui.dp(12), ui.dp(12), ui.dp(12));
        GradientDrawable shape = ui.rounded(ui.surface, ui.border, 24);
        card.setBackground(shape);
        card.setElevation(ui.dp(1.5f));

        LinearLayout to = ui.row();
        to.addView(ui.text("Til", 13.5f, ui.muted, false));
        LinearLayout chip = ui.row();
        chip.setPadding(ui.dp(10), ui.dp(5), ui.dp(10), ui.dp(5));
        chip.setBackground(ui.ripple(ui.rounded(ui.surfaceAlt, 0, 999), 999));
        View dot = new View(this);
        boolean online = service.isOnline(target.deviceId);
        dot.setBackground(ui.rounded(online ? ui.success : ui.faint, 0, 999));
        chip.addView(dot, new LinearLayout.LayoutParams(ui.dp(7), ui.dp(7)));
        TextView name = ui.text(target.name + "  ▾", 14f, ui.text, true);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        chip.addView(name, ui.wrap(7, 0, 0, 0));
        chip.setOnClickListener(v -> choosePeer(this::select));
        to.addView(chip, ui.wrap(8, 0, 0, 0));
        card.addView(to);

        card.addView(composerInput(), ui.margins(0, 6, 0, 4));

        LinearLayout bottom = ui.row();
        android.widget.HorizontalScrollView chipsScroll = new android.widget.HorizontalScrollView(this);
        chipsScroll.setHorizontalScrollBarEnabled(false);
        LinearLayout chips = ui.row();
        chips.addView(toolChip(R.drawable.ic_file, "Filer", v -> pickFiles(target)));
        chips.addView(toolChip(R.drawable.ic_image, "Fotos", v -> pickPhotos(target)), ui.wrap(6, 0, 0, 0));
        chips.addView(toolChip(R.drawable.ic_folder, "Mappe", v -> pickTree(target)), ui.wrap(6, 0, 0, 0));
        chips.addView(toolChip(R.drawable.ic_clipboard, null, v -> sendClipboard(target)), ui.wrap(6, 0, 0, 0));
        chipsScroll.addView(chips);
        bottom.addView(chipsScroll, ui.weight(1));

        sendButton = new android.widget.ImageView(this);
        sendButton.setImageResource(R.drawable.ic_send);
        sendButton.setScaleType(android.widget.ImageView.ScaleType.CENTER);
        sendButton.setContentDescription("Send");
        sendButton.setOnClickListener(v -> sendComposer());
        LinearLayout.LayoutParams sendParams = new LinearLayout.LayoutParams(ui.dp(40), ui.dp(40));
        sendParams.setMargins(ui.dp(8), 0, 0, 0);
        bottom.addView(sendButton, sendParams);
        styleSendButton();
        card.addView(bottom);
        return card;
    }

    private View toolChip(int icon, String label, View.OnClickListener click) {
        LinearLayout chip = ui.row();
        chip.setPadding(ui.dp(9), ui.dp(7), ui.dp(11), ui.dp(7));
        chip.setBackground(ui.ripple(ui.rounded(Color.TRANSPARENT, ui.border, 999), 999));
        chip.setClickable(true);
        chip.setOnClickListener(click);
        chip.setContentDescription(label == null ? "Send udklipsholder" : label);
        chip.addView(ui.icon(icon, ui.muted, 15));
        if (label == null) {
            chip.setPadding(ui.dp(10), ui.dp(7), ui.dp(10), ui.dp(7));
            return chip;
        }
        LinearLayout.LayoutParams labelParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        labelParams.setMargins(ui.dp(5), 0, 0, 0);
        chip.addView(ui.text(label, 13f, ui.text, false), labelParams);
        return chip;
    }

    private void styleSendButton() {
        if (sendButton == null || composerInput == null) {
            return;
        }
        boolean ready = composerInput.getText().toString().trim().length() > 0;
        sendButton.setBackground(ui.ripple(ui.rounded(ready ? ui.accent : ui.surfaceAlt, 0, 999), 999));
        sendButton.setColorFilter(ready ? ui.onAccent : ui.faint);
        sendButton.setEnabled(ready);
    }

    private void sendComposer() {
        Peer target = selectedPeer();
        String text = composerInput == null ? "" : composerInput.getText().toString().trim();
        if (target == null || text.isEmpty()) {
            return;
        }
        service.sendText(target, text);
        composerInput.setText("");
        composerInput.clearFocus();
        android.view.inputmethod.InputMethodManager keyboard =
                (android.view.inputmethod.InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (keyboard != null) {
            keyboard.hideSoftInputFromWindow(composerInput.getWindowToken(), 0);
        }
        toast((Ui.isLink(text) ? "Link sendt – åbner på " : "Sendt til ") + target.name, false);
    }

    private View clipboardSuggestion(Peer target) {
        String clip = service.currentClipboard();
        if (clip == null || clip.trim().isEmpty() || clip.equals(dismissedClip)
                || service.isClipboardShared(clip)) {
            return null;
        }
        clip = clip.trim();
        LinearLayout card = ui.row();
        card.setPadding(ui.dp(14), ui.dp(12), ui.dp(10), ui.dp(12));
        card.setBackground(ui.rounded(ui.accentSoft, 0, 18));
        card.addView(ui.iconBadge(Ui.isLink(clip) ? R.drawable.ic_link : R.drawable.ic_clipboard, 34,
                ui.surface, ui.accent));
        LinearLayout texts = ui.column();
        texts.addView(ui.text(Ui.isLink(clip) ? "Link i din udklipsholder" : "Fra din udklipsholder",
                12f, ui.accent, true));
        TextView preview = ui.text(clip.replace('\n', ' '), 14f, ui.text, false);
        preview.setSingleLine(true);
        preview.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(preview, ui.margins(0, 1, 0, 0));
        LinearLayout.LayoutParams textParams = ui.weight(1);
        textParams.setMargins(ui.dp(12), 0, ui.dp(8), 0);
        card.addView(texts, textParams);
        TextView send = ui.button("Send", "primary");
        send.setMinHeight(ui.dp(36));
        send.setTextSize(13.5f);
        String value = clip;
        send.setOnClickListener(v -> {
            service.sendText(target, value);
            service.markClipboardShared(value);
            dismissedClip = value;
            toast("Sendt til " + target.name, false);
            render();
        });
        card.addView(send);
        TextView close = ui.text("✕", 15f, ui.muted, false);
        close.setGravity(Gravity.CENTER);
        close.setContentDescription("Skjul");
        close.setOnClickListener(v -> {
            dismissedClip = value;
            render();
        });
        card.addView(close, new LinearLayout.LayoutParams(ui.dp(32), ui.dp(36)));
        return card;
    }

    private View welcomeCard() {
        LinearLayout card = ui.card();
        card.setBackground(ui.rounded(ui.surface, ui.border, 24));
        card.setPadding(ui.dp(20), ui.dp(20), ui.dp(20), ui.dp(20));
        card.addView(ui.title("Forbind din PC", 21));
        String[] steps = {
                "Åbn h4xtor share på PC'en",
                "Klik “+ Forbind ny enhed”",
                "Scan QR-koden med knappen herunder",
        };
        for (int index = 0; index < steps.length; index++) {
            LinearLayout line = ui.row();
            TextView number = ui.text(String.valueOf(index + 1), 12.5f, ui.accent, true);
            number.setGravity(Gravity.CENTER);
            number.setBackground(ui.rounded(ui.accentSoft, 0, 999));
            line.addView(number, new LinearLayout.LayoutParams(ui.dp(24), ui.dp(24)));
            line.addView(ui.text(steps[index], 14.5f, ui.text, false), ui.margins(12, 0, 0, 0));
            card.addView(line, ui.margins(0, index == 0 ? 14 : 10, 0, 0));
        }
        LinearLayout buttons = ui.row();
        TextView scan = ui.button("Scan QR-kode", "primary");
        scan.setOnClickListener(v -> scanQr());
        buttons.addView(scan, ui.weight(1));
        TextView mine = ui.button("Vis min kode", "secondary");
        mine.setOnClickListener(v -> showMyQr());
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(10), 0, 0, 0);
        buttons.addView(mine, params);
        card.addView(buttons, ui.margins(0, 18, 0, 0));
        return card;
    }

    private View deviceGroup(List<Peer> peers, Peer selected) {
        LinearLayout group = ui.column();
        group.setBackground(ui.rounded(ui.surface, ui.border, 20));
        for (int index = 0; index < peers.size(); index++) {
            if (index > 0) {
                View line = new View(this);
                line.setBackgroundColor(ui.border);
                LinearLayout.LayoutParams lineParams = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, ui.dp(0.7f)));
                lineParams.setMargins(ui.dp(70), 0, 0, 0);
                group.addView(line, lineParams);
            }
            Peer peer = peers.get(index);
            group.addView(deviceRow(peer, selected != null && selected.deviceId.equals(peer.deviceId),
                    index == 0, index == peers.size() - 1));
        }
        return group;
    }

    private View deviceRow(Peer peer, boolean selected, boolean first, boolean last) {
        boolean paired = service.identity().isOutboundTrusted(peer.deviceId);
        boolean online = service.isOnline(peer.deviceId);
        LinearLayout row = ui.row();
        row.setPadding(ui.dp(14), ui.dp(12), ui.dp(4), ui.dp(12));
        GradientDrawable fill = ui.rounded(selected ? ui.accentSoft : Color.TRANSPARENT, 0, 20);
        float r = ui.dp(20);
        fill.setCornerRadii(new float[]{first ? r : 0, first ? r : 0, first ? r : 0, first ? r : 0,
                last ? r : 0, last ? r : 0, last ? r : 0, last ? r : 0});
        row.setBackground(ui.ripple(fill, 20));
        row.setClickable(true);
        row.setOnClickListener(v -> {
            if (paired) {
                select(peer);
            } else {
                service.pair(peer);
                toast("Beder " + peer.name + " om en kode…", false);
            }
        });
        row.setOnLongClickListener(v -> {
            peerMenu(peer);
            return true;
        });

        FrameLayout avatarFrame = new FrameLayout(this);
        avatarFrame.addView(ui.avatar(peer.platform, 42));
        if (paired) {
            View dot = new View(this);
            dot.setBackground(ui.rounded(online ? ui.success : ui.faint, ui.surface, 999));
            FrameLayout.LayoutParams dotParams = new FrameLayout.LayoutParams(ui.dp(13), ui.dp(13),
                    Gravity.BOTTOM | Gravity.END);
            avatarFrame.addView(dot, dotParams);
        }
        row.addView(avatarFrame);

        LinearLayout texts = ui.column();
        TextView name = ui.text(peer.name, 16f, ui.text, true);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(name);
        String transport = "wifi-direct".equals(peer.transport) ? "Wi-Fi Direct" : "Wi-Fi";
        String meta = paired
                ? (online ? "Online" : "Offline") + " · " + Ui.platformLabel(peer.platform) + " · " + transport
                : "Fundet på " + transport + " · " + peer.address;
        TextView metaView = ui.text(meta, 12.5f, paired && online ? ui.success : ui.muted, false);
        metaView.setSingleLine(true);
        metaView.setEllipsize(TextUtils.TruncateAt.END);
        texts.addView(metaView, ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams textParams = ui.weight(1);
        textParams.setMargins(ui.dp(14), 0, ui.dp(8), 0);
        row.addView(texts, textParams);

        if (paired && online) {
            LinearLayout.LayoutParams barsParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ui.dp(16));
            barsParams.setMargins(0, 0, ui.dp(6), 0);
            row.addView(signalBars(service.rtt(peer.deviceId)), barsParams);
        }
        if (selected) {
            LinearLayout.LayoutParams checkParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            checkParams.setMargins(ui.dp(2), 0, ui.dp(2), 0);
            row.addView(ui.text("✓", 17f, ui.accent, true), checkParams);
        }
        if (!paired) {
            TextView connect = ui.button("Forbind", "soft");
            connect.setMinHeight(ui.dp(36));
            connect.setTextSize(13.5f);
            connect.setOnClickListener(v -> {
                service.pair(peer);
                toast("Beder " + peer.name + " om en kode…", false);
            });
            row.addView(connect);
        }
        TextView more = ui.text("⋮", 21f, ui.muted, true);
        more.setGravity(Gravity.CENTER);
        more.setBackground(ui.ripple(ui.rounded(Color.TRANSPARENT, 0, 999), 999));
        more.setOnClickListener(v -> peerMenu(peer));
        more.setContentDescription("Flere valg for " + peer.name);
        row.addView(more, new LinearLayout.LayoutParams(ui.dp(38), ui.dp(40)));
        return row;
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
            labels.add("Fjern enhed");
            actions.add(() -> confirmForget(peer));
        } else {
            labels.add("Forbind");
            actions.add(() -> service.pair(peer));
            labels.add("Fjern fra listen");
            actions.add(() -> service.remove(peer));
        }
        new AlertDialog.Builder(this)
                .setTitle(peer.name)
                .setItems(labels.toArray(new String[0]), (dialog, which) -> actions.get(which).run())
                .show();
    }

    private void confirmForget(Peer peer) {
        new AlertDialog.Builder(this)
                .setTitle("Fjern " + peer.name + "?")
                .setMessage("I skal forbinde igen for at dele. Den anden enhed glemmer også denne telefon.")
                .setNegativeButton("Annullér", null)
                .setPositiveButton("Fjern", (dialog, which) -> service.forget(peer))
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
        boolean active = "active".equals(item.status);
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
                detail = direction + " · Færdig · " + Ui.formatBytes(item.total)
                        + (item.total > 0 && item.finishedAt > 0
                        ? " på " + Ui.formatDuration(item.seconds()) : "");
                break;
            case "cancelled":
                detail = direction + " · Annulleret";
                break;
            case "failed":
                detail = direction + " · Mislykkedes"
                        + (item.error == null || item.error.isEmpty() ? "" : ": " + item.error);
                break;
            default:
                detail = direction + " · " + Ui.formatBytes(item.sent) + " af " + Ui.formatBytes(item.total);
        }
        TextView meta = ui.text(detail, 12.5f, "failed".equals(item.status) ? ui.danger : ui.muted, false);
        texts.addView(meta, ui.margins(0, 2, 0, 0));
        LinearLayout.LayoutParams params = ui.weight(1);
        params.setMargins(ui.dp(14), 0, ui.dp(6), 0);
        row.addView(texts, params);
        if (active) {
            TextView percent = ui.text(Math.round(item.fraction() * 100) + "%", 22f, ui.text, true);
            percent.setTypeface(android.graphics.Typeface.create("sans-serif-medium",
                    android.graphics.Typeface.NORMAL));
            percent.setFontFeatureSettings("tnum");
            row.addView(percent);
        }
        card.addView(row);

        if (active || "failed".equals(item.status) || "cancelled".equals(item.status)) {
            ProgressBar bar = ui.progress();
            bar.setProgress((int) Math.round(item.fraction() * 1000));
            if (!active) {
                bar.setProgressTintList(android.content.res.ColorStateList.valueOf(
                        "failed".equals(item.status) ? ui.danger : ui.faint));
            }
            card.addView(bar, ui.margins(0, 12, 0, 0));
        }
        if (active) {
            LinearLayout stats = ui.row();
            stats.addView(statChip("Hastighed", item.speed > 0 ? Ui.formatSpeed(item.speed) : "…"), ui.weight(1));
            String eta = item.speed > 0 ? Ui.formatEta((item.total - item.sent) / item.speed) : "";
            stats.addView(statChip("Tid tilbage", eta.isEmpty() ? "…" : eta.replace(" tilbage", "")), ui.weight(1));
            stats.addView(statChip("Top", item.peakSpeed > 0 ? Ui.formatSpeed(item.peakSpeed) : "…"), ui.weight(1));
            card.addView(stats, ui.margins(0, 10, 0, 0));
        }
        float[] samples = item.samples();
        if (active || ("done".equals(item.status) && samples.length >= 3)) {
            SpeedGraph graph = new SpeedGraph(this, item.outgoing ? ui.accent : ui.success, ui.border);
            graph.setSamples(samples);
            graph.setContentDescription("Hastighedsgraf");
            card.addView(graph, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                    ui.dp(active ? 54 : 30)));
            if ("done".equals(item.status)) {
                TextView summary = ui.text("Gennemsnit " + Ui.formatSpeed(item.averageSpeed()) + " · top "
                        + Ui.formatSpeed(Math.max(item.peakSpeed, item.averageSpeed())), 11.5f, ui.faint, false);
                summary.setFontFeatureSettings("tnum");
                card.addView(summary, ui.margins(0, 4, 0, 0));
            }
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
        boolean canOpenSent = item.outgoing && !item.folder && !item.uri.isEmpty();
        if ("done".equals(item.status) && (!item.outgoing || canOpenSent)) {
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

    private View statChip(String label, String value) {
        LinearLayout box = ui.column();
        box.addView(ui.text(label, 11f, ui.faint, false));
        TextView text = ui.text(value, 14f, ui.text, true);
        text.setSingleLine(true);
        text.setFontFeatureSettings("tnum");
        box.addView(text);
        return box;
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

        content.addView(ui.label("Smarte tricks"), ui.margins(4, 0, 0, 8));
        LinearLayout tricks = ui.card();
        tricks.addView(toggleRow("Send nye skærmbilleder til PC'en",
                "Tag et skærmbillede – så ligger det på PC'en et øjeblik efter.",
                identity.flag("auto_screenshots", false), value -> {
                    if (value && !hasMediaPermission()) {
                        requestPermissions(ShareService.mediaPermissions(), REQUEST_MEDIA_PERMISSION);
                        return;
                    }
                    service.setAutoScreenshots(value);
                    toast(value ? "Nye skærmbilleder sendes automatisk" : "Slået fra", false);
                }));
        tricks.addView(ui.divider());
        tricks.addView(toggleRow("Hold skærmen tændt under overførsler",
                "Store filer bliver ikke afbrudt af, at telefonen går i dvale.",
                identity.flag("keep_screen_on", true), value -> identity.setFlag("keep_screen_on", value)));
        tricks.addView(ui.divider());
        tricks.addView(toggleRow("Vibrér når noget er sendt eller modtaget",
                "En kort dobbelt-summen, så du ved det er landet.",
                identity.flag("vibrate_done", true), value -> identity.setFlag("vibrate_done", value)));
        content.addView(tricks, ui.margins(0, 0, 0, 18));

        content.addView(ui.label("Nørd-panel"), ui.margins(4, 0, 0, 8));
        content.addView(nerdPanel(), ui.margins(0, 0, 0, 18));

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
            TextView forget = ui.button("Fjern", "danger");
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

    private boolean hasMediaPermission() {
        for (String permission : ShareService.mediaPermissions()) {
            if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
        }
        return true;
    }

    private View nerdPanel() {
        LinearLayout card = ui.card();
        // Totals
        LinearLayout grid1 = ui.row();
        grid1.addView(statChip("Sendt", Ui.formatBytes(service.stat("stat_sent_bytes"))
                + " · " + service.stat("stat_sent_count")), ui.weight(1));
        grid1.addView(statChip("Modtaget", Ui.formatBytes(service.stat("stat_received_bytes"))
                + " · " + service.stat("stat_received_count")), ui.weight(1));
        card.addView(grid1);
        long bytes = service.stat("stat_sent_bytes") + service.stat("stat_received_bytes");
        double seconds = service.stat("stat_seconds_ms") / 1000.0;
        LinearLayout grid2 = ui.row();
        grid2.addView(statChip("Gennemsnit", seconds > 0 ? Ui.formatSpeed(bytes / seconds) : "–"), ui.weight(1));
        long top = service.stat("stat_top_speed");
        grid2.addView(statChip("Rekord", top > 0 ? Ui.formatSpeed(top) : "–"), ui.weight(1));
        card.addView(grid2, ui.margins(0, 12, 0, 0));

        // Speed test
        card.addView(ui.divider(), ui.margins(0, 14, 0, 14));
        card.addView(ui.text("Hastighedstest", 15f, ui.text, true));
        TextView result = ui.text("Måler ping og sender 32 MB testdata til PC'en (gemmes ikke).",
                12.5f, ui.muted, false);
        result.setFontFeatureSettings("tnum");
        card.addView(result, ui.margins(0, 2, 0, 8));
        ProgressBar bar = ui.progress();
        bar.setVisibility(View.GONE);
        card.addView(bar, ui.margins(0, 0, 0, 8));
        SpeedGraph graph = new SpeedGraph(this, ui.accent, ui.border);
        graph.setVisibility(View.GONE);
        card.addView(graph, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(54)));
        TextView start = ui.button("Test hastighed til PC", "soft");
        card.addView(start, ui.margins(0, 8, 0, 0));
        start.setOnClickListener(v -> {
            Peer target = service.preferredOnlinePeer();
            if (target == null) {
                toast("Ingen PC online lige nu", true);
                return;
            }
            if (!target.supports("speedtest")) {
                toast(target.name + " skal opdateres til v1.1.2 for at kunne teste", true);
                return;
            }
            start.setEnabled(false);
            start.setText("Tester mod " + target.name + "…");
            bar.setVisibility(View.VISIBLE);
            graph.setVisibility(View.VISIBLE);
            List<Float> samples = new ArrayList<>();
            service.speedTest(target, new ShareService.SpeedTestListener() {
                long lastSample;

                @Override
                public void onProgress(long sent, long total, double bytesPerSecond) {
                    bar.setProgress((int) (sent * 1000 / Math.max(1, total)));
                    result.setText(Ui.formatBytes(sent) + " af " + Ui.formatBytes(total) + " · "
                            + Ui.formatSpeed(bytesPerSecond));
                    long now = android.os.SystemClock.elapsedRealtime();
                    if (now - lastSample > 150) {
                        lastSample = now;
                        samples.add((float) bytesPerSecond);
                        float[] values = new float[samples.size()];
                        for (int index = 0; index < values.length; index++) {
                            values[index] = samples.get(index);
                        }
                        graph.setSamples(values);
                    }
                }

                @Override
                public void onDone(double upload, long pingMs) {
                    result.setText("Upload " + Ui.formatSpeed(upload) + " (" + Ui.formatMbit(upload) + ") · ping "
                            + pingMs + " ms");
                    result.setTextColor(ui.text);
                    start.setEnabled(true);
                    start.setText("Test igen");
                    bar.setProgress(1000);
                }

                @Override
                public void onFailed(String reason) {
                    result.setText("Testen fejlede: " + reason);
                    result.setTextColor(ui.danger);
                    start.setEnabled(true);
                    start.setText("Prøv igen");
                }
            });
        });

        // Connection details
        card.addView(ui.divider(), ui.margins(0, 14, 0, 14));
        card.addView(ui.text("Forbindelse", 15f, ui.text, true));
        StringBuilder info = new StringBuilder();
        List<String> addresses = service.localAddresses();
        info.append("Telefonens IP: ").append(addresses.isEmpty() ? "–" : TextUtils.join(", ", addresses));
        info.append("\nPort: ").append(AppIdentity.PORT).append(" · TLS 1.3 · certifikat-låst");
        for (Peer peer : service.pairedPeers()) {
            long rtt = service.rtt(peer.deviceId);
            info.append("\n").append(peer.name).append(": ").append(peer.address).append(":").append(peer.port)
                    .append(" · ").append(service.isOnline(peer.deviceId)
                            ? (rtt >= 0 ? "ping " + rtt + " ms" : "online") : "offline")
                    .append("wifi-direct".equals(peer.transport) ? " · Wi-Fi Direct" : "");
        }
        TextView infoText = ui.text(info.toString(), 12.5f, ui.muted, false);
        infoText.setTypeface(android.graphics.Typeface.MONOSPACE);
        infoText.setTextIsSelectable(true);
        card.addView(infoText, ui.margins(0, 4, 0, 0));
        TextView reset = ui.button("Nulstil statistik", "ghost");
        reset.setOnClickListener(v -> {
            service.resetStats();
            render();
        });
        card.addView(reset, ui.margins(0, 10, 0, 0));
        return card;
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

    private void pickPhotos(Peer peer) {
        pendingPeerId = peer.deviceId;
        Intent intent;
        if (Build.VERSION.SDK_INT >= 33) {
            intent = new Intent(MediaStore.ACTION_PICK_IMAGES);
            intent.putExtra(MediaStore.EXTRA_PICK_IMAGES_MAX, MediaStore.getPickImagesMaxLimit());
        } else {
            intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.setType("image/*");
            intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/*", "video/*"});
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        }
        try {
            startActivityForResult(intent, REQUEST_FILES);
        } catch (ActivityNotFoundException error) {
            pickFiles(peer);
        }
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
        // Keep read access even if this screen is closed during a long transfer.
        int grant = Intent.FLAG_GRANT_READ_URI_PERMISSION;
        if (data.getClipData() != null) {
            for (int index = 0; index < data.getClipData().getItemCount(); index++) {
                persist(data.getClipData().getItemAt(index).getUri(), grant);
            }
        } else if (data.getData() != null) {
            persist(data.getData(), grant);
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

    private void persist(Uri uri, int flags) {
        try {
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (Exception ignored) {
            // Not every provider offers persistable grants; the activity grant still works.
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
    public void onStopped() {
        service = null;
        finishAndRemoveTask();
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
