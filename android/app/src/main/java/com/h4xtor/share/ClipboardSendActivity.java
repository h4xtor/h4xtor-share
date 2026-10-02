package com.h4xtor.share;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Toast;

/**
 * Invisible helper: Android only lets the focused app read the clipboard, so
 * the notification action and the Quick Settings tile open this for a split
 * second, read the clipboard, send it, and close.
 */
public final class ClipboardSendActivity extends Activity {
    private boolean done;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ShareService.start(this);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (!hasFocus || done) {
            return;
        }
        done = true;
        ShareService.with(this, service -> {
            String text = service.currentClipboard();
            if (text == null || text.trim().isEmpty()) {
                Toast.makeText(this, "Udklipsholderen er tom", Toast.LENGTH_SHORT).show();
            } else {
                Peer selected = service.peer(service.identity().string("selected_peer", null));
                int count;
                if (selected != null && service.isOnline(selected.deviceId)) {
                    service.sendText(selected, text);
                    count = 1;
                } else {
                    count = service.sendTextToAll(text);
                }
                Toast.makeText(this, count == 0
                        ? "Ingen forbundne enheder online"
                        : "Udklipsholder sendt ✓", Toast.LENGTH_SHORT).show();
            }
            finish();
        });
    }
}
