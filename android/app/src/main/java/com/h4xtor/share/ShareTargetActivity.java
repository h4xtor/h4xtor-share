package com.h4xtor.share;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/** Target of Android's "Del" sheet: pick a device, done. */
public final class ShareTargetActivity extends Activity {
    private Ui ui;
    private final List<Uri> uris = new ArrayList<>();
    private String text;
    private LinearLayout list;
    private View chooseLabel;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ui = new Ui(this);
        ui.styleWindow(this);
        readIntent(getIntent());
        if (uris.isEmpty() && (text == null || text.trim().isEmpty())) {
            finish();
            return;
        }
        setContentView(buildSheet());
        ShareService.with(this, service -> renderDevices(service));
    }

    @SuppressWarnings("deprecation")
    private void readIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        String action = intent.getAction();
        if (Intent.ACTION_PROCESS_TEXT.equals(action)) {
            // "Send til PC" in the text-selection menu of any app.
            CharSequence value = intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT);
            text = value == null ? null : value.toString();
            return;
        }
        if (Intent.ACTION_SEND.equals(action)) {
            Uri stream = Build.VERSION.SDK_INT >= 33
                    ? intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class)
                    : intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (stream != null) {
                uris.add(stream);
            } else {
                CharSequence value = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
                text = value == null ? null : value.toString();
            }
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> streams = Build.VERSION.SDK_INT >= 33
                    ? intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri.class)
                    : intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (streams != null) {
                uris.addAll(streams);
            }
        }
        if (uris.isEmpty() && intent.getClipData() != null) {
            ClipData clip = intent.getClipData();
            for (int index = 0; index < clip.getItemCount(); index++) {
                Uri uri = clip.getItemAt(index).getUri();
                if (uri != null) {
                    uris.add(uri);
                }
            }
        }
    }

    private View buildSheet() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.argb(110, 0, 0, 0));
        root.setOnClickListener(v -> finish());

        LinearLayout sheet = ui.column();
        sheet.setClickable(true);
        sheet.setPadding(ui.dp(22), ui.dp(12), ui.dp(22), ui.dp(26));
        android.graphics.drawable.GradientDrawable background = new android.graphics.drawable.GradientDrawable();
        background.setColor(ui.bg);
        float radius = ui.dp(26);
        background.setCornerRadii(new float[]{radius, radius, radius, radius, 0, 0, 0, 0});
        sheet.setBackground(background);

        View handle = new View(this);
        handle.setBackground(ui.rounded(ui.border, 0, 999));
        LinearLayout.LayoutParams handleParams = new LinearLayout.LayoutParams(ui.dp(40), ui.dp(5));
        handleParams.gravity = Gravity.CENTER_HORIZONTAL;
        handleParams.setMargins(0, 0, 0, ui.dp(16));
        sheet.addView(handle, handleParams);

        sheet.addView(ui.title("Send med h4xtor share", 21));
        String what;
        if (!uris.isEmpty()) {
            what = uris.size() == 1 ? "1 fil" : uris.size() + " filer";
        } else if (Ui.isLink(text)) {
            what = "Link · åbner direkte på modtageren";
        } else {
            what = "Tekst · lander i udklipsholderen";
        }
        TextView sub = ui.text(what, 14f, ui.muted, false);
        sub.setSingleLine(true);
        sub.setEllipsize(TextUtils.TruncateAt.END);
        sheet.addView(sub, ui.margins(0, 4, 0, 14));
        if (uris.isEmpty() && text != null) {
            LinearLayout preview = ui.row();
            preview.setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(12));
            preview.setBackground(ui.rounded(ui.surfaceAlt, 0, 16));
            preview.addView(ui.icon(Ui.isLink(text) ? R.drawable.ic_link : R.drawable.ic_clipboard, ui.accent, 18));
            TextView value = ui.text(text.trim().replace('\n', ' '), 14f, ui.text, false);
            value.setMaxLines(2);
            value.setEllipsize(TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams valueParams = ui.weight(1);
            valueParams.setMargins(ui.dp(10), 0, 0, 0);
            preview.addView(value, valueParams);
            sheet.addView(preview, ui.margins(0, 0, 0, 16));
        }
        chooseLabel = ui.label("Vælg enhed");
        sheet.addView(chooseLabel, ui.margins(2, 0, 0, 8));

        ScrollView scroll = new ScrollView(this);
        list = ui.column();
        scroll.addView(list);
        sheet.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        TextView loading = ui.text("Henter enheder…", 14f, ui.muted, false);
        list.addView(loading);

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
        params.topMargin = ui.dp(80);
        root.addView(sheet, params);
        Ui.onInsets(root, (top, bottom) ->
                sheet.setPadding(ui.dp(22), ui.dp(12), ui.dp(22), ui.dp(26) + bottom));
        return root;
    }

    private void renderDevices(ShareService service) {
        List<Peer> paired = service.pairedPeers();
        if (paired.size() == 1) {
            // Only one place it can go: send straight away, no extra tap.
            send(service, paired.get(0));
            return;
        }
        renderList(service);
        // Refresh the online state once the service had time to ping everyone.
        list.postDelayed(() -> {
            if (!isFinishing()) {
                renderList(service);
            }
        }, 1500);
    }

    private void renderList(ShareService service) {
        list.removeAllViews();
        List<Peer> peers = service.pairedPeers();
        if (peers.isEmpty()) {
            list.addView(ui.text("Du har ikke forbundet nogen enheder endnu. Åbn h4xtor share og scan "
                    + "QR-koden på din PC.", 14f, ui.muted, false));
            TextView open = ui.button("Åbn h4xtor share", "primary");
            open.setOnClickListener(v -> {
                startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                finish();
            });
            list.addView(open, ui.margins(0, 14, 0, 0));
            return;
        }
        if (peers.size() >= 2) {
            int onlineCount = service.onlinePairedPeers().size();
            LinearLayout all = ui.card();
            all.setClickable(true);
            all.setBackground(ui.ripple(ui.rounded(ui.accentSoft, 0, 18), 18));
            LinearLayout allRow = ui.row();
            allRow.addView(ui.iconBadge(R.drawable.ic_nav_share, 42, ui.surface, ui.accent));
            LinearLayout allTexts = ui.column();
            allTexts.addView(ui.text("Alle enheder", 16f, ui.text, true));
            allTexts.addView(ui.text(onlineCount + " af " + peers.size() + " er online lige nu",
                    12.5f, onlineCount > 0 ? ui.success : ui.muted, false));
            LinearLayout.LayoutParams allParams = ui.weight(1);
            allParams.setMargins(ui.dp(14), 0, 0, 0);
            allRow.addView(allTexts, allParams);
            allRow.addView(ui.icon(R.drawable.ic_nav_share, ui.accent, 22));
            all.addView(allRow);
            all.setOnClickListener(v -> sendAll(service));
            list.addView(all, ui.margins(0, 0, 0, 10));
        }
        for (Peer peer : peers) {
            boolean online = service.isOnline(peer.deviceId);
            LinearLayout card = ui.card();
            card.setClickable(true);
            card.setBackground(ui.ripple(ui.rounded(ui.surface, ui.border, 18), 18));
            LinearLayout row = ui.row();
            row.addView(ui.avatar(peer.platform, 42));
            LinearLayout texts = ui.column();
            texts.addView(ui.text(peer.name, 16f, ui.text, true));
            texts.addView(ui.text(Ui.platformLabel(peer.platform) + (online ? " · online" : " · ikke set lige nu"),
                    12.5f, online ? ui.success : ui.muted, false));
            LinearLayout.LayoutParams params = ui.weight(1);
            params.setMargins(ui.dp(14), 0, 0, 0);
            row.addView(texts, params);
            row.addView(ui.icon(R.drawable.ic_nav_share, ui.accent, 22));
            card.addView(row);
            card.setOnClickListener(v -> send(service, peer));
            list.addView(card, ui.margins(0, 0, 0, 10));
        }
    }

    // ---------------------------------------------------------- live progress
    private final android.os.Handler ticker = new android.os.Handler(android.os.Looper.getMainLooper());
    private boolean closing;

    /** Stay open and show how far the upload has come (bar, %, speed, time left). */
    private void showProgress(ShareService service, String label, List<ShareService.DeviceSend> groups) {
        List<String> ids = new ArrayList<>();
        for (ShareService.DeviceSend group : groups) {
            ids.addAll(group.ids);
        }
        list.removeAllViews();
        if (chooseLabel != null) {
            chooseLabel.setVisibility(View.GONE);
        }
        LinearLayout box = ui.column();
        TextView title = ui.text("Sender til " + label, 15f, ui.text, true);
        box.addView(title);
        LinearLayout numbers = ui.row();
        TextView percent = ui.text("0%", 34f, ui.text, true);
        percent.setFontFeatureSettings("tnum");
        numbers.addView(percent, ui.weight(1));
        TextView speed = ui.text("", 15f, ui.accent, true);
        speed.setFontFeatureSettings("tnum");
        numbers.addView(speed);
        box.addView(numbers, ui.margins(0, 6, 0, 0));
        android.widget.ProgressBar bar = ui.progress();
        box.addView(bar, ui.margins(0, 6, 0, 0));
        TextView detail = ui.text("", 12.5f, ui.muted, false);
        detail.setFontFeatureSettings("tnum");
        box.addView(detail, ui.margins(0, 6, 0, 0));
        SpeedGraph graph = new SpeedGraph(this, ui.accent, ui.border);
        box.addView(graph, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(56)));
        TextView background = ui.button("Fortsæt i baggrunden", "secondary");
        background.setOnClickListener(v -> finish());
        box.addView(background, ui.margins(0, 14, 0, 0));
        list.addView(box);

        Runnable tick = new Runnable() {
            @Override
            public void run() {
                if (isFinishing()) {
                    return;
                }
                long sent = 0;
                long total = 0;
                double rate = 0;
                int done = 0;
                int failed = 0;
                double seconds = 0;
                ShareService.TransferItem lead = null;
                for (String id : ids) {
                    ShareService.TransferItem item = service.transfer(id);
                    if (item == null) {
                        continue;
                    }
                    sent += Math.min(item.sent, item.total);
                    total += item.total;
                    if ("active".equals(item.status)) {
                        rate += item.speed;
                        if (lead == null) {
                            lead = item;
                        }
                    }
                    if ("done".equals(item.status)) {
                        done++;
                        seconds = Math.max(seconds, item.seconds());
                    }
                    if ("failed".equals(item.status) || "cancelled".equals(item.status)) {
                        failed++;
                        detail.setText(item.error == null || item.error.isEmpty() ? "Afbrudt" : item.error);
                    }
                }
                double fraction = total <= 0 ? 0 : (double) sent / total;
                percent.setText(Math.round(fraction * 100) + "%");
                bar.setProgress((int) Math.round(fraction * 1000));
                if (lead != null) {
                    graph.setSamples(lead.samples());
                }
                if (failed > 0 && done + failed == ids.size()) {
                    title.setText(groups.size() > 1 ? groupSummary(service, groups)
                            : "Kunne ikke sende alt til " + label);
                    title.setTextColor(ui.danger);
                    background.setText("Luk – prøv igen fra Overførsler");
                    return;
                }
                if (done == ids.size() && !closing) {
                    closing = true;
                    title.setText(groups.size() > 1 ? "✓ " + groupSummary(service, groups)
                            : "✓ Sendt til " + label);
                    speed.setText(Ui.formatSpeed(total / Math.max(0.001, seconds)) + " gns.");
                    detail.setText(Ui.formatBytes(total) + " på " + Ui.formatDuration(seconds));
                    ticker.postDelayed(ShareTargetActivity.this::finish, 1400);
                    return;
                }
                speed.setText(rate > 0 ? Ui.formatSpeed(rate) : "");
                String eta = rate > 0 ? Ui.formatEta((total - sent) / rate) : "";
                detail.setText(Ui.formatBytes(sent) + " af " + Ui.formatBytes(total)
                        + (ids.size() > 1 ? " · " + done + "/" + ids.size() + " filer" : "")
                        + (eta.isEmpty() ? "" : " · " + eta));
                ticker.postDelayed(this, 250);
            }
        };
        ticker.post(tick);
    }

    /** "Sendt til 2 af 3 – Bærbar fejlede: …" built from the per-device transfers. */
    private static String groupSummary(ShareService service, List<ShareService.DeviceSend> groups) {
        List<String> names = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        for (ShareService.DeviceSend group : groups) {
            boolean bad = false;
            String error = "";
            for (String id : group.ids) {
                ShareService.TransferItem item = service.transfer(id);
                if (item != null && ("failed".equals(item.status) || "cancelled".equals(item.status))) {
                    bad = true;
                    if (error.isEmpty() && item.error != null) {
                        error = item.error;
                    }
                }
            }
            if (bad) {
                names.add(group.peer.name);
                errors.add(error);
            }
        }
        return ShareLogic.allSummary(groups.size(), names, errors);
    }

    @Override
    protected void onDestroy() {
        ticker.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    /** Hand the read grant to the service: it outlives this short-lived sheet. */
    private void holdGrant() {
        Intent hold = new Intent(this, ShareService.class).setAction(ShareService.ACTION_HOLD);
        ClipData clip = ClipData.newRawUri("h4xtor", uris.get(0));
        for (int index = 1; index < uris.size(); index++) {
            clip.addItem(new ClipData.Item(uris.get(index)));
        }
        hold.setClipData(clip);
        hold.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startForegroundService(hold);
        } catch (Exception ignored) {
            // Service already running in the foreground; grant attempt is best effort.
        }
    }

    /** "Alle enheder": files go to every online device in parallel, text is sent to each. */
    private void sendAll(ShareService service) {
        if (service.onlinePairedPeers().isEmpty()) {
            Toast.makeText(this, "Ingen af dine enheder er online lige nu", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!uris.isEmpty()) {
            holdGrant();
            showProgress(service, "alle enheder", service.sendUrisToAll(uris));
            return;
        }
        list.removeAllViews();
        if (chooseLabel != null) {
            chooseLabel.setVisibility(View.GONE);
        }
        TextView status = ui.text("Sender til alle enheder\u2026", 15f, ui.text, true);
        list.addView(status);
        service.sendTextToAll(text, (results, summary) -> {
            if (isFinishing()) {
                return;
            }
            boolean allOk = !results.isEmpty();
            for (ShareService.DeviceResult result : results) {
                allOk &= result.ok;
            }
            status.setText((allOk ? "\u2713 " : "") + summary);
            status.setTextColor(allOk ? ui.text : ui.danger);
            ticker.postDelayed(this::finish, allOk ? 1400 : 3500);
        });
    }

    private void send(ShareService service, Peer peer) {
        if (!uris.isEmpty()) {
            holdGrant();
            List<String> ids = service.sendUris(peer, uris);
            showProgress(service, peer.name,
                    java.util.Collections.singletonList(new ShareService.DeviceSend(peer, ids)));
            return;
        } else {
            service.sendText(peer, text);
            Toast.makeText(this, (Ui.isLink(text) ? "Link sendt – åbner på " : "Sendt til ") + peer.name,
                    Toast.LENGTH_SHORT).show();
        }
        finish();
    }
}
