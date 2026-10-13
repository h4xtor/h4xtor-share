package com.h4xtor.share;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Starts the background service after a reboot (when enabled) and after an app update. */
public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();
        AppIdentity identity = new AppIdentity(context);
        boolean updated = Intent.ACTION_MY_PACKAGE_REPLACED.equals(action);
        boolean boot = Intent.ACTION_BOOT_COMPLETED.equals(action) && identity.flag("start_on_boot", false);
        if ((updated || boot) && identity.flag("run_in_background", true)
                && !identity.flag("stopped_by_user", false)) {
            try {
                ShareService.start(context);
            } catch (Exception ignored) {
                // Android may refuse background starts on some devices.
            }
        }
        if (updated) {
            AppUpdater.announceUpdated(context);
        }
    }
}
