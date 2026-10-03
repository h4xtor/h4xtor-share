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
        sheet.addView(sub, ui.margins(0, 4, 0, 16));

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

    private void send(ShareService service, Peer peer) {
        if (!uris.isEmpty()) {
            // Hand the read grant to the service: it outlives this short-lived sheet.
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
            service.sendUris(peer, uris);
            Toast.makeText(this, "Sender til " + peer.name + " – følg med i notifikationen", Toast.LENGTH_SHORT).show();
        } else {
            service.sendText(peer, text);
            Toast.makeText(this, "Sendt til " + peer.name, Toast.LENGTH_SHORT).show();
        }
        finish();
    }
}
