package com.h4xtor.share;

import android.annotation.SuppressLint;
import android.content.Context;
import android.net.wifi.WifiManager;
import android.net.wifi.p2p.WifiP2pConfig;
import android.net.wifi.p2p.WifiP2pGroup;
import android.net.wifi.p2p.WifiP2pManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import java.security.SecureRandom;
import java.util.Locale;

/**
 * Hosts a Wi-Fi Direct group so a PC (or another phone) can connect straight
 * to this phone without any router. Computers join it like a normal WPA2
 * network ("legacy client"), the phone is always {@code 192.168.49.1}.
 */
public final class WifiDirectController {
    public interface Callback {
        void onGroupStarted(String ssid, String passphrase);
        void onGroupFailed(String reason);
        void onGroupStopped();
    }

    public static final String GROUP_OWNER_ADDRESS = "192.168.49.1";
    private static final String ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

    private final Context context;
    private final AppIdentity identity;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private WifiP2pManager manager;
    private WifiP2pManager.Channel channel;
    private volatile boolean active;
    private volatile String ssid = "";
    private volatile String passphrase = "";

    public WifiDirectController(Context context, AppIdentity identity) {
        this.context = context.getApplicationContext();
        this.identity = identity;
    }

    public boolean isActive() {
        return active;
    }

    public String ssid() {
        return ssid;
    }

    public String passphrase() {
        return passphrase;
    }

    /** The Wi-Fi QR format every phone camera understands (join network). */
    public String wifiQrPayload() {
        return "WIFI:T:WPA;S:" + escape(ssid) + ";P:" + escape(passphrase) + ";;";
    }

    private static String escape(String value) {
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
                .replace(":", "\\:").replace("\"", "\\\"");
    }

    private String stableName() {
        String stored = identity.string("p2p_ssid", "");
        if (stored.startsWith("DIRECT-h4-")) {
            return stored;
        }
        String model = Build.MODEL == null ? "Android" : Build.MODEL;
        String clean = model.replaceAll("[^A-Za-z0-9]", "");
        if (clean.isEmpty()) {
            clean = "Android";
        }
        String name = "DIRECT-h4-" + clean;
        if (name.length() > 28) {
            name = name.substring(0, 28);
        }
        identity.setString("p2p_ssid", name);
        return name;
    }

    private String stablePassphrase() {
        String stored = identity.string("p2p_pass", "");
        if (stored.length() >= 8) {
            return stored;
        }
        SecureRandom random = new SecureRandom();
        StringBuilder builder = new StringBuilder();
        for (int index = 0; index < 12; index++) {
            builder.append(ALPHABET.charAt(random.nextInt(ALPHABET.length())));
        }
        String value = builder.toString();
        identity.setString("p2p_pass", value);
        return value;
    }

    @SuppressLint("MissingPermission")
    private boolean ensureManager() {
        if (manager != null && channel != null) {
            return true;
        }
        manager = (WifiP2pManager) context.getSystemService(Context.WIFI_P2P_SERVICE);
        if (manager == null) {
            return false;
        }
        channel = manager.initialize(context, Looper.getMainLooper(), () -> {
            channel = null;
            active = false;
        });
        return channel != null;
    }

    /** Caller must hold NEARBY_WIFI_DEVICES (13+) or ACCESS_FINE_LOCATION (10-12). */
    @SuppressLint("MissingPermission")
    public void start(Callback callback) {
        WifiManager wifi = (WifiManager) context.getSystemService(Context.WIFI_SERVICE);
        if (wifi != null && !wifi.isWifiEnabled()) {
            callback.onGroupFailed("Slå Wi-Fi til først (det behøver ikke være forbundet til et netværk).");
            return;
        }
        if (!ensureManager()) {
            callback.onGroupFailed("Telefonen understøtter ikke Wi-Fi Direct.");
            return;
        }
        final String name = stableName();
        final String pass = stablePassphrase();
        manager.removeGroup(channel, new WifiP2pManager.ActionListener() {
            @Override public void onSuccess() { create(name, pass, callback, 0); }
            @Override public void onFailure(int reason) { create(name, pass, callback, 0); }
        });
    }

    @SuppressLint("MissingPermission")
    private void create(String name, String pass, Callback callback, int attempt) {
        WifiP2pConfig config = new WifiP2pConfig.Builder()
                .setNetworkName(name)
                .setPassphrase(pass)
                .enablePersistentMode(false)
                .setGroupOperatingBand(WifiP2pConfig.GROUP_OWNER_BAND_AUTO)
                .build();
        manager.createGroup(channel, config, new WifiP2pManager.ActionListener() {
            @Override
            public void onSuccess() {
                handler.postDelayed(() -> readGroup(callback, 0), 600);
            }

            @Override
            public void onFailure(int reason) {
                if (reason == WifiP2pManager.BUSY && attempt < 3) {
                    handler.postDelayed(() -> create(name, pass, callback, attempt + 1), 1200);
                    return;
                }
                callback.onGroupFailed(reasonText(reason));
            }
        });
    }

    @SuppressLint("MissingPermission")
    private void readGroup(Callback callback, int attempt) {
        manager.requestGroupInfo(channel, (WifiP2pGroup group) -> {
            if (group == null || group.getNetworkName() == null) {
                if (attempt < 8) {
                    handler.postDelayed(() -> readGroup(callback, attempt + 1), 500);
                } else {
                    callback.onGroupFailed("Gruppen startede ikke. Prøv igen.");
                }
                return;
            }
            ssid = group.getNetworkName();
            passphrase = group.getPassphrase() == null ? "" : group.getPassphrase();
            active = true;
            callback.onGroupStarted(ssid, passphrase);
        });
    }

    @SuppressLint("MissingPermission")
    public void stop(Callback callback) {
        if (!ensureManager()) {
            active = false;
            callback.onGroupStopped();
            return;
        }
        manager.removeGroup(channel, new WifiP2pManager.ActionListener() {
            @Override public void onSuccess() { active = false; callback.onGroupStopped(); }
            @Override public void onFailure(int reason) { active = false; callback.onGroupStopped(); }
        });
    }

    private static String reasonText(int reason) {
        switch (reason) {
            case WifiP2pManager.P2P_UNSUPPORTED:
                return "Wi-Fi Direct understøttes ikke på denne telefon.";
            case WifiP2pManager.BUSY:
                return "Wi-Fi Direct er optaget. Prøv igen om lidt.";
            default:
                return String.format(Locale.ROOT, "Wi-Fi Direct kunne ikke starte (fejl %d).", reason);
        }
    }
}
