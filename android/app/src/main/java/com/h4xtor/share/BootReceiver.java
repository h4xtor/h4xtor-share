package com.h4xtor.share;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Starts the background service after a reboot when the user enabled it. */
public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }
        AppIdentity identity = new AppIdentity(context);
        if (identity.flag("start_on_boot", false) && identity.flag("run_in_background", true)) {
            try {
                ShareService.start(context);
            } catch (Exception ignored) {
                // Android may refuse background starts on some devices.
            }
        }
    }
}
