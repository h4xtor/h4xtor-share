package com.h4xtor.share;

import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.util.List;

/** The update dialogs on the phone: "Ny version", "Opdateringslog" and the welcome note. */
final class UpdateFlow {
    private static final int SHOWN = 3;

    private final MainActivity activity;
    private final Ui ui;
    private final AppIdentity identity;
    /** Waiting for "Tillad fra denne kilde" before it can be installed. */
    private UpdateLogic.Release pending;
    private boolean checking;

    UpdateFlow(MainActivity activity, Ui ui) {
        this.activity = activity;
        this.ui = ui;
        this.identity = new AppIdentity(activity);
    }

    void onResume() {
        activity.getSystemService(NotificationManager.class).cancel(AppUpdater.UPDATED_NOTIFICATION);
        String last = identity.string("last_run_version", "");
        if (!AppIdentity.VERSION.equals(last)) {
            identity.setString("last_run_version", AppIdentity.VERSION);
            if (!last.isEmpty() && UpdateLogic.isNewer(AppIdentity.VERSION, last)) {
                showWelcome(last);
                return;
            }
        }
        if (pending != null && activity.getPackageManager().canRequestPackageInstalls()) {
            UpdateLogic.Release release = pending;
            pending = null;
            download(release);
            return;
        }
        if (AppUpdater.due(activity)) {
            check(false);
        }
    }

    // ------------------------------------------------------------------ checking
    void check(boolean manual) {
        if (checking) {
            return;
        }
        checking = true;
        if (manual) {
            activity.showToast("Søger efter en ny version…", false);
        }
        new Thread(() -> {
            AppUpdater.Found found = null;
            Exception failure = null;
            try {
                found = AppUpdater.check(activity);
            } catch (Exception error) {
                failure = error;
            }
            AppUpdater.Found result = found;
            Exception problem = failure;
            activity.runOnUiThread(() -> {
                checking = false;
                if (activity.isFinishing() || activity.isDestroyed()) {
                    return;
                }
                if (result != null) {
                    if (manual || UpdateLogic.shouldPrompt(result.release.version,
                            identity.string("update_skip", null), identity.string("update_later", null),
                            laterUntil(), System.currentTimeMillis())) {
                        showUpdate(result);
                    }
                } else if (manual && problem != null) {
                    activity.showToast("Kunne ikke nå GitHub – tjek din internetforbindelse.", true);
                } else if (manual) {
                    activity.showToast("Du har den nyeste version (" + AppIdentity.VERSION + ") ✓", false);
                }
            });
        }, "update-check").start();
    }

    private long laterUntil() {
        try {
            return Long.parseLong(identity.string("update_later_until", "0"));
        } catch (NumberFormatException error) {
            return 0;
        }
    }

    // ------------------------------------------------------------------ dialogs
    private View changelogView(List<UpdateLogic.Entry> entries, String warning) {
        LinearLayout box = ui.column();
        box.setPadding(ui.dp(22), ui.dp(8), ui.dp(22), 0);
        TextView text = ui.text(UpdateLogic.format(entries, SHOWN), 14f, ui.text, false);
        text.setTextIsSelectable(true);
        ScrollView scroll = new ScrollView(activity);
        scroll.addView(text);
        box.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(260)));
        if (entries.size() > SHOWN) {
            TextView more = ui.button("Vis alt (" + entries.size() + " versioner)", "ghost");
            more.setOnClickListener(v -> {
                text.setText(UpdateLogic.format(entries, Integer.MAX_VALUE));
                more.setVisibility(View.GONE);
            });
            box.addView(more, ui.margins(0, 6, 0, 0));
        }
        if (warning != null) {
            box.addView(ui.text(warning, 13f, ui.warning, true), ui.margins(0, 10, 0, 0));
        }
        return box;
    }

    private void showUpdate(AppUpdater.Found found) {
        String version = found.release.version;
        ShareService service = ShareService.get();
        String warning = service != null && service.activeTransfers() > 0
                ? "En overførsel er i gang. Den bliver afbrudt, hvis du opdaterer nu." : null;
        new AlertDialog.Builder(activity)
                .setTitle("Version " + version + " er klar")
                .setMessage("Du har version " + AppIdentity.VERSION + ". Her er det nye:")
                .setView(changelogView(found.entries, warning))
                .setPositiveButton("Opdatér nu", (dialog, which) -> start(found.release))
                .setNegativeButton("Senere", (dialog, which) -> later(version))
                .setNeutralButton("Spring denne version over", (dialog, which) -> {
                    identity.setString("update_skip", version);
                    activity.showToast("Version " + version + " springes over", false);
                })
                .setOnCancelListener(dialog -> later(version))
                .show();
    }

    private void later(String version) {
        identity.setString("update_later", version);
        identity.setString("update_later_until",
                String.valueOf(System.currentTimeMillis() + UpdateLogic.LATER_DELAY_MS));
    }

    void showChangelog() {
        new AlertDialog.Builder(activity)
                .setTitle("Opdateringslog")
                .setMessage("Du kører version " + AppIdentity.VERSION + ".")
                .setView(changelogView(AppUpdater.changelog(activity), null))
                .setPositiveButton("Luk", null)
                .show();
    }

    private void showWelcome(String previous) {
        List<UpdateLogic.Entry> entries =
                UpdateLogic.between(AppUpdater.changelog(activity), previous, AppIdentity.VERSION);
        new AlertDialog.Builder(activity)
                .setTitle("Velkommen til version " + AppIdentity.VERSION)
                .setMessage("Her er det nye siden version " + previous + ":")
                .setView(changelogView(entries, null))
                .setPositiveButton("Fint", null)
                .show();
    }

    private void problem(String message) {
        new AlertDialog.Builder(activity)
                .setTitle("Opdateringen blev ikke gennemført")
                .setMessage(message)
                .setPositiveButton("OK", null)
                .show();
    }

    // ------------------------------------------------------------------ installing
    private void start(UpdateLogic.Release release) {
        if (release.apkUrl == null || release.checksumUrl == null) {
            problem("Udgivelsen mangler filen eller dens tjeksum – opdateringen er stoppet.");
            return;
        }
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            pending = release;
            new AlertDialog.Builder(activity)
                    .setTitle("Tillad opdateringer")
                    .setMessage("Android skal give h4xtor share lov til at installere sin egen opdatering. "
                            + "Det er kun første gang.\n\nTryk “Åbn indstillinger”, slå “Tillad fra denne kilde” "
                            + "til, og tryk tilbage. Så fortsætter opdateringen af sig selv.")
                    .setPositiveButton("Åbn indstillinger", (dialog, which) -> {
                        try {
                            activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + activity.getPackageName())));
                        } catch (Exception error) {
                            activity.showToast("Åbn Indstillinger → Apps → h4xtor share → Installer ukendte apps", true);
                        }
                    })
                    .setNegativeButton("Annullér", (dialog, which) -> pending = null)
                    .show();
            return;
        }
        download(release);
    }

    private void download(UpdateLogic.Release release) {
        TextView status = ui.text("Henter version " + release.version + " …", 14.5f, ui.text, false);
        status.setPadding(ui.dp(24), ui.dp(12), ui.dp(24), ui.dp(4));
        AlertDialog progress = new AlertDialog.Builder(activity)
                .setTitle("Opdaterer h4xtor share")
                .setView(status)
                .setCancelable(false)
                .show();
        new Thread(() -> {
            try {
                int[] shown = {-1};
                File apk = AppUpdater.download(activity, release, (done, total) -> {
                    int percent = total > 0 ? (int) (done * 100 / total) : -1;
                    if (percent != shown[0]) {
                        shown[0] = percent;
                        activity.runOnUiThread(() -> status.setText(percent < 0
                                ? "Henter … " + Ui.formatBytes(done)
                                : "Henter … " + percent + " %"));
                    }
                });
                activity.runOnUiThread(() -> {
                    status.setText("Tjeksum OK ✓ – Android spørger nu, om du vil opdatere.");
                    // The installer replaces the running app: stop sharing cleanly first.
                    activity.stopServiceForUpdate();
                    try {
                        AppUpdater.install(activity, apk);
                    } catch (Exception error) {
                        progress.dismiss();
                        activity.reattachService();
                        problem(H4xtorClient.safeMessage(error));
                        return;
                    }
                    progress.dismiss();
                });
            } catch (Exception error) {
                activity.runOnUiThread(() -> {
                    progress.dismiss();
                    problem(error instanceof AppUpdater.UpdateException
                            ? error.getMessage()
                            : "Kunne ikke hente opdateringen – tjek din internetforbindelse og prøv igen.");
                });
            }
        }, "update-download").start();
    }

    /** PackageInstaller's answer (MainActivity gets it as ACTION_INSTALL_STATUS). */
    @SuppressWarnings("deprecation")
    void onInstallStatus(Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = Build.VERSION.SDK_INT >= 33
                    ? intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class)
                    : intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                activity.startActivity(confirm);
                return;
            }
        }
        if (status == PackageInstaller.STATUS_SUCCESS) {
            return;  // Android restarts the app; BootReceiver reopens it.
        }
        activity.reattachService();
        if (status != PackageInstaller.STATUS_FAILURE_ABORTED) {
            String detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            problem("Android installerede ikke opdateringen" + (detail == null ? "." : ": " + detail));
        } else {
            activity.showToast("Opdateringen blev annulleret", false);
        }
    }
}
