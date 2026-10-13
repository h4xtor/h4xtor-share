package com.h4xtor.share;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Build;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * Updates the app from GitHub Releases of h4xtor/h4xtor-share (HTTPS only): check,
 * download, verify SHA-256, then hand the APK to Android's PackageInstaller, which
 * always asks the user to confirm. Local to this phone; nothing goes over the
 * device protocol, and pairings and keys stay as they are.
 */
final class AppUpdater {
    static final String ACTION_INSTALL_STATUS = "com.h4xtor.share.INSTALL_STATUS";
    static final int UPDATED_NOTIFICATION = 4242;
    private static final String CHANNEL = "h4xtor_updates";
    /** E2E only: app-private file naming a local fake release server (needs adb run-as). */
    private static final String TEST_SOURCE = "update_source";

    static final class Found {
        final UpdateLogic.Release release;
        final List<UpdateLogic.Entry> entries;

        Found(UpdateLogic.Release release, List<UpdateLogic.Entry> entries) {
            this.release = release;
            this.entries = entries;
        }
    }

    /** A reason that is shown to the user as it is. */
    static final class UpdateException extends IOException {
        UpdateException(String message) {
            super(message);
        }
    }

    interface Progress {
        void update(long done, long total);
    }

    private AppUpdater() {
    }

    // ------------------------------------------------------------- source
    private static String testBase(Context context) {
        File file = new File(context.getFilesDir(), TEST_SOURCE);
        if (!file.isFile()) {
            return null;
        }
        try {
            String base = read(new FileInputStream(file)).trim();
            return base.matches("http://127\\.0\\.0\\.1:\\d+") ? base : null;
        } catch (IOException error) {
            return null;
        }
    }

    private static String apiUrl(Context context) {
        String base = testBase(context);
        return base == null ? UpdateLogic.API_URL : base + "/repos/" + UpdateLogic.REPO + "/releases/latest";
    }

    private static String downloadPrefix(Context context) {
        String base = testBase(context);
        return base == null ? UpdateLogic.DOWNLOAD_PREFIX : base + "/" + UpdateLogic.REPO + "/releases/download/";
    }

    // ------------------------------------------------------------- network
    private static HttpURLConnection open(Context context, String url) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(60_000);
        connection.setRequestProperty("User-Agent", "h4xtor-share/" + AppIdentity.VERSION);
        connection.setRequestProperty("Accept", "application/vnd.github+json, */*");
        int code = connection.getResponseCode();
        // Redirects (GitHub → its download CDN) must stay on HTTPS.
        if (downloadPrefix(context).startsWith("https://")
                && !"https".equals(connection.getURL().getProtocol())) {
            connection.disconnect();
            throw new UpdateException("Opdateringen blev stoppet: forbindelsen var ikke krypteret.");
        }
        if (code != 200) {
            connection.disconnect();
            throw new IOException("GitHub svarede " + code + ".");
        }
        return connection;
    }

    private static String fetch(Context context, String url) throws IOException {
        HttpURLConnection connection = open(context, url);
        try (InputStream input = connection.getInputStream()) {
            return read(input);
        } finally {
            connection.disconnect();
        }
    }

    private static String read(InputStream input) throws IOException {
        try (InputStream in = input) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = in.read(buffer)) != -1) {
                out.write(buffer, 0, count);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    /** Blocking. Null when this is the newest version; throws when GitHub cannot be reached. */
    static Found check(Context context) throws Exception {
        AppIdentity identity = new AppIdentity(context);
        identity.setString("update_last_check", String.valueOf(System.currentTimeMillis()));
        UpdateLogic.Release release = UpdateLogic.parseRelease(fetch(context, apiUrl(context)), downloadPrefix(context));
        if (release == null) {
            return null;
        }
        if (release.changelogUrl != null) {
            try {
                String text = fetch(context, release.changelogUrl);
                if (!UpdateLogic.parseChangelog(text).isEmpty()) {
                    try (OutputStream out = new FileOutputStream(new File(context.getFilesDir(), "changelog.md"))) {
                        out.write(text.getBytes(StandardCharsets.UTF_8));
                    }
                }
            } catch (IOException ignored) {
                // A missing changelog never blocks an update.
            }
        }
        if (!UpdateLogic.isNewer(release.version, AppIdentity.VERSION)) {
            return null;
        }
        return new Found(release, UpdateLogic.between(changelog(context), AppIdentity.VERSION, release.version));
    }

    static boolean due(Context context) {
        AppIdentity identity = new AppIdentity(context);
        if (!identity.flag("update_auto", true)) {
            return false;
        }
        long last;
        try {
            last = Long.parseLong(identity.string("update_last_check", "0"));
        } catch (NumberFormatException error) {
            last = 0;
        }
        return System.currentTimeMillis() - last >= UpdateLogic.CHECK_INTERVAL_MS;
    }

    /** The newest changelog we know: the downloaded copy or the one inside the APK. */
    static List<UpdateLogic.Entry> changelog(Context context) {
        List<UpdateLogic.Entry> best = UpdateLogic.parseChangelog("");
        try {
            best = UpdateLogic.parseChangelog(read(context.getAssets().open(UpdateLogic.CHANGELOG)));
        } catch (IOException ignored) {
            // Not bundled in this build.
        }
        try {
            List<UpdateLogic.Entry> cached = UpdateLogic.parseChangelog(
                    read(new FileInputStream(new File(context.getFilesDir(), "changelog.md"))));
            if (!cached.isEmpty() && (best.isEmpty()
                    || UpdateLogic.isNewer(cached.get(0).version, best.get(0).version))) {
                best = cached;
            }
        } catch (IOException ignored) {
            // Never downloaded yet.
        }
        return best;
    }

    /** Blocking: download the APK and verify it; a wrong checksum deletes the file. */
    static File download(Context context, UpdateLogic.Release release, Progress progress) throws IOException {
        if (release.apkUrl == null || release.checksumUrl == null) {
            throw new UpdateException("Udgivelsen mangler filen eller dens tjeksum – opdateringen er stoppet.");
        }
        String expected = UpdateLogic.parseChecksum(fetch(context, release.checksumUrl));
        if (expected == null) {
            throw new UpdateException("Tjeksum-filen er ugyldig – opdateringen er stoppet.");
        }
        File folder = new File(context.getCacheDir(), "update");
        File[] old = folder.listFiles();
        for (int index = 0; old != null && index < old.length; index++) {
            //noinspection ResultOfMethodCallIgnored
            old[index].delete();
        }
        if (!folder.isDirectory() && !folder.mkdirs()) {
            throw new IOException("Kunne ikke gemme opdateringen på telefonen.");
        }
        File apk = new File(folder, "h4xtor-share-" + release.version + ".apk");
        HttpURLConnection connection = open(context, release.apkUrl);
        long total = connection.getContentLengthLong();
        try (InputStream input = connection.getInputStream(); OutputStream output = new FileOutputStream(apk)) {
            byte[] buffer = new byte[256 * 1024];
            long done = 0;
            int count;
            while ((count = input.read(buffer)) != -1) {
                output.write(buffer, 0, count);
                done += count;
                progress.update(done, total);
            }
        } finally {
            connection.disconnect();
        }
        String actual;
        try (InputStream input = new FileInputStream(apk)) {
            actual = UpdateLogic.sha256(input);
        }
        if (!expected.equals(actual)) {
            //noinspection ResultOfMethodCallIgnored
            apk.delete();
            throw new UpdateException("Tjeksummen passer ikke – filen er slettet, og intet er ændret. Prøv igen senere.");
        }
        return apk;
    }

    // ------------------------------------------------------------- install
    /** Hands the verified APK to Android; the answer arrives at MainActivity as ACTION_INSTALL_STATUS. */
    static void install(Activity activity, File apk) throws IOException {
        PackageInstaller installer = activity.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(activity.getPackageName());
        int id = installer.createSession(params);
        try (PackageInstaller.Session session = installer.openSession(id)) {
            try (InputStream input = new FileInputStream(apk);
                 OutputStream output = session.openWrite("base.apk", 0, apk.length())) {
                byte[] buffer = new byte[256 * 1024];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    output.write(buffer, 0, count);
                }
                session.fsync(output);
            }
            Intent status = new Intent(activity, MainActivity.class).setAction(ACTION_INSTALL_STATUS);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT
                    | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
            session.commit(PendingIntent.getActivity(activity, 7, status, flags).getIntentSender());
        } catch (IOException | RuntimeException error) {
            installer.abandonSession(id);
            throw error;
        }
    }

    /** After an update: try to reopen the app; Android may block that, so also post a tap-to-open note. */
    static void announceUpdated(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
                CHANNEL, "Opdateringer", NotificationManager.IMPORTANCE_DEFAULT));
        Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent tap = PendingIntent.getActivity(context, 8, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification note = new Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_share)
                .setContentTitle("Opdateret – tryk for at åbne")
                .setContentText("h4xtor share " + AppIdentity.VERSION + " er installeret.")
                .setContentIntent(tap)
                .setAutoCancel(true)
                .build();
        try {
            manager.notify(UPDATED_NOTIFICATION, note);
        } catch (SecurityException noPermission) {
            // Notifications are off: the app still works when opened by hand.
        }
        try {
            context.startActivity(open);
        } catch (Exception blocked) {
            // Android 10+ often blocks this from the background; the notification covers it.
        }
    }
}
