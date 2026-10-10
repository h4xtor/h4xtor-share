package com.h4xtor.share;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.WallpaperManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.speech.tts.TextToSpeech;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.Locale;

/** Find my phone, volume, text-to-speech and wallpaper – the "remote control" features. */
final class RemoteTools {
    static final String CHANNEL_FIND = "h4xtor_find";
    static final int NOTIFICATION_FIND = 40;
    private static final long FIND_MAX_MS = 2 * 60_000L;
    private static final long[] VIBRATION = {0, 700, 500};

    private final Context context;
    private final Handler main;
    private Ringtone ringtone;
    private int savedAlarmVolume = -1;
    private boolean ringing;
    private TextToSpeech speech;
    private boolean speechReady;
    private String speechQueued;

    private final Runnable autoStop = this::stopFind;

    RemoteTools(Context context, Handler main) {
        this.context = context;
        this.main = main;
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_FIND, "Find telefon", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("Vises mens telefonen ringer, fordi du leder efter den");
        channel.setSound(null, null);
        channel.enableVibration(false);
        context.getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    boolean enabled(AppIdentity identity) {
        return identity.flag("remote_control", true);
    }

    // ------------------------------------------------------------ find phone
    synchronized boolean isRinging() {
        return ringing;
    }

    synchronized void startFind() {
        if (ringing) {
            main.removeCallbacks(autoStop);
            main.postDelayed(autoStop, FIND_MAX_MS);
            return;
        }
        AudioManager audio = context.getSystemService(AudioManager.class);
        try {
            savedAlarmVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM);
            audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
        } catch (Exception ignored) {
            savedAlarmVolume = -1; // volume locked by Do Not Disturb: ring at the current level
        }
        AudioAttributes attributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build();
        Uri sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
        if (sound == null) {
            sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
        }
        try {
            ringtone = RingtoneManager.getRingtone(context, sound);
            if (ringtone == null) {
                ringtone = RingtoneManager.getRingtone(context,
                        RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE));
            }
            if (ringtone != null) {
                ringtone.setAudioAttributes(attributes);
                ringtone.setLooping(true);
                ringtone.play();
            }
        } catch (Exception ignored) {
            // Vibration and the notification still work.
        }
        vibrate(attributes);
        ringing = true;
        showFindNotification();
        main.removeCallbacks(autoStop);
        main.postDelayed(autoStop, FIND_MAX_MS);
    }

    synchronized void stopFind() {
        main.removeCallbacks(autoStop);
        if (!ringing) {
            return;
        }
        ringing = false;
        try {
            if (ringtone != null) {
                ringtone.stop();
            }
        } catch (Exception ignored) {
            // Already stopped.
        }
        ringtone = null;
        if (savedAlarmVolume >= 0) {
            try {
                context.getSystemService(AudioManager.class)
                        .setStreamVolume(AudioManager.STREAM_ALARM, savedAlarmVolume, 0);
            } catch (Exception ignored) {
                // Leave the volume as it is.
            }
            savedAlarmVolume = -1;
        }
        vibrator().cancel();
        context.getSystemService(NotificationManager.class).cancel(NOTIFICATION_FIND);
    }

    private Vibrator vibrator() {
        if (Build.VERSION.SDK_INT >= 31) {
            return context.getSystemService(VibratorManager.class).getDefaultVibrator();
        }
        return legacyVibrator();
    }

    @SuppressWarnings("deprecation")
    private Vibrator legacyVibrator() {
        return (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
    }

    @SuppressWarnings("deprecation")
    private void vibrate(AudioAttributes attributes) {
        try {
            vibrator().vibrate(VibrationEffect.createWaveform(VIBRATION, 0), attributes);
        } catch (Exception ignored) {
            // No vibrator.
        }
    }

    private void showFindNotification() {
        PendingIntent stop = PendingIntent.getService(context, 41,
                new Intent(context, ShareService.class).setAction(ShareService.ACTION_FIND_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        try {
            context.getSystemService(NotificationManager.class).notify(NOTIFICATION_FIND,
                    new Notification.Builder(context, CHANNEL_FIND)
                            .setSmallIcon(R.drawable.ic_stat_share)
                            .setContentTitle("Find telefon – tryk for at stoppe")
                            .setContentText("Din PC leder efter telefonen")
                            .setOngoing(true)
                            .setColor(Ui.ACCENT_LIGHT)
                            .setCategory(Notification.CATEGORY_ALARM)
                            .setContentIntent(stop)
                            .addAction(new Notification.Action.Builder(null, "Stop", stop).build())
                            .build());
        } catch (Exception ignored) {
            // Notifications may be disabled; the sound still plays.
        }
    }

    // ---------------------------------------------------------------- volume
    /** Sets the media volume (0-100 %) and returns the level that was actually applied. */
    int setVolume(int percent) {
        AudioManager audio = context.getSystemService(AudioManager.class);
        int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, ShareLogic.volumeIndex(percent, max), 0);
        return ShareLogic.volumePercent(audio.getStreamVolume(AudioManager.STREAM_MUSIC), max);
    }

    // ----------------------------------------------------------------- speak
    synchronized void speak(String text) {
        if (speech != null && speechReady) {
            speech.speak(text, TextToSpeech.QUEUE_FLUSH, null, "h4xtor-speak");
            return;
        }
        speechQueued = text;
        if (speech != null) {
            return; // still starting up: the queued text is spoken as soon as it is ready
        }
        speech = new TextToSpeech(context, status -> {
            synchronized (RemoteTools.this) {
                if (status != TextToSpeech.SUCCESS || speech == null) {
                    shutdownSpeech();
                    return;
                }
                Locale danish = new Locale("da", "DK");
                if (speech.isLanguageAvailable(danish) >= TextToSpeech.LANG_AVAILABLE) {
                    speech.setLanguage(danish);
                }
                speechReady = true;
                if (speechQueued != null) {
                    speech.speak(speechQueued, TextToSpeech.QUEUE_FLUSH, null, "h4xtor-speak");
                    speechQueued = null;
                }
            }
        });
    }

    private void shutdownSpeech() {
        if (speech != null) {
            speech.shutdown();
        }
        speech = null;
        speechReady = false;
        speechQueued = null;
    }

    // ------------------------------------------------------------- wallpaper
    void setWallpaper(File image) throws Exception {
        try (InputStream stream = new FileInputStream(image)) {
            WallpaperManager.getInstance(context).setStream(stream);
        } catch (java.io.IOException error) {
            throw new H4xtorServer.HttpError(400, "Billedet kunne ikke bruges som baggrund.");
        }
    }

    synchronized void shutdown() {
        stopFind();
        shutdownSpeech();
    }
}
