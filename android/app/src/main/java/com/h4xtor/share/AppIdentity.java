package com.h4xtor.share;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

import org.json.JSONArray;
import org.json.JSONObject;

import java.math.BigInteger;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.cert.X509Certificate;
import java.util.Calendar;
import java.util.Locale;
import java.util.UUID;

import javax.security.auth.x500.X500Principal;

public final class AppIdentity {
    public static final int PORT = 47474;
    public static final String VERSION = "1.1.1";
    public static final String[] CAPABILITIES = {
            "clipboard", "files", "resume", "folders", "links", "mutual-pair", "qr-pair",
            "unpair", "wifi-direct-host"
    };
    private static final String PREFS = "h4xtor_share";
    // v1: EC P-256. The original RSA key only allowed PKCS#1 signatures, which TLS 1.3
    // forbids, so desktops could never complete a handshake with the phone.
    private static final String TLS_ALIAS = "h4xtor_share_tls_ec";
    private static final String LEGACY_TLS_ALIAS = "h4xtor_share_tls";
    private static final int HISTORY_LIMIT = 200;

    private final SharedPreferences prefs;

    public AppIdentity(Context context) {
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!prefs.contains("device_id")) {
            prefs.edit().putString("device_id", UUID.randomUUID().toString().replace("-", "")).apply();
        }
        if (!prefs.contains("device_name")) {
            prefs.edit().putString("device_name", friendlyDeviceName(context)).apply();
        }
    }

    /** The name the user gave the phone (e.g. "S24 Ultra"), else the model code. */
    static String friendlyDeviceName(Context context) {
        String[] keys = {"device_name", "bluetooth_name"};
        for (String key : keys) {
            try {
                String value = android.provider.Settings.Global.getString(context.getContentResolver(), key);
                if (value == null || value.trim().isEmpty()) {
                    value = android.provider.Settings.Secure.getString(context.getContentResolver(), key);
                }
                if (value != null && !value.trim().isEmpty()) {
                    return value.trim().length() > 80 ? value.trim().substring(0, 80) : value.trim();
                }
            } catch (Exception ignored) {
                // Not readable on this device.
            }
        }
        String model = Build.MODEL == null ? "Android" : Build.MODEL.trim();
        return model.isEmpty() ? "Android" : model;
    }

    public synchronized java.util.Set<String> hiddenPeers() {
        return new java.util.HashSet<>(prefs.getStringSet("hidden_peers", new java.util.HashSet<>()));
    }

    public synchronized void hidePeer(String peerId) {
        java.util.Set<String> hidden = hiddenPeers();
        hidden.add(peerId);
        prefs.edit().putStringSet("hidden_peers", hidden).apply();
    }

    public synchronized void unhidePeer(String peerId) {
        java.util.Set<String> hidden = hiddenPeers();
        if (hidden.remove(peerId)) {
            prefs.edit().putStringSet("hidden_peers", hidden).apply();
        }
    }

    public String deviceId() {
        return prefs.getString("device_id", "");
    }

    public String deviceName() {
        return prefs.getString("device_name", "Android");
    }

    public void setDeviceName(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty()) {
            throw new IllegalArgumentException("Device name cannot be empty");
        }
        if (normalized.length() > 80) {
            normalized = normalized.substring(0, 80);
        }
        prefs.edit().putString("device_name", normalized).apply();
    }

    public void trustOutbound(Peer peer, String token, String fingerprint, String name) {
        trustOutbound(peer.deviceId, token, fingerprint, name);
        remember(peer);
    }

    public String outboundToken(String peerId) {
        return prefs.getString("out_token_" + peerId, null);
    }

    public String outboundFingerprint(String peerId) {
        return prefs.getString("out_fp_" + peerId, null);
    }

    public boolean isOutboundTrusted(String peerId) {
        return outboundToken(peerId) != null && outboundFingerprint(peerId) != null;
    }

    public void trustInbound(String peerId, String token, String name) {
        prefs.edit()
                .putString("in_token_" + peerId, token)
                .putString("peer_name_" + peerId, name)
                .apply();
    }

    public boolean validateInbound(String peerId, String token) {
        String expected = prefs.getString("in_token_" + peerId, null);
        return expected != null && constantTimeEquals(expected, token);
    }

    public String peerName(String peerId) {
        return prefs.getString("peer_name_" + peerId, peerId);
    }

    public boolean isClipboardSyncEnabled() {
        return prefs.getBoolean("clipboard_sync", true);
    }

    public void setClipboardSyncEnabled(boolean value) {
        prefs.edit().putBoolean("clipboard_sync", value).apply();
    }

    public boolean flag(String key, boolean fallback) {
        return prefs.getBoolean("flag_" + key, fallback);
    }

    public void setFlag(String key, boolean value) {
        prefs.edit().putBoolean("flag_" + key, value).apply();
    }

    public String string(String key, String fallback) {
        return prefs.getString("str_" + key, fallback);
    }

    public void setString(String key, String value) {
        prefs.edit().putString("str_" + key, value).apply();
    }

    /** Remove every trace of a peer: tokens, pin and stored address. */
    public synchronized void forget(String peerId) {
        prefs.edit()
                .remove("out_token_" + peerId)
                .remove("out_fp_" + peerId)
                .remove("in_token_" + peerId)
                .apply();
        try {
            JSONObject known = knownRaw();
            known.remove(peerId);
            prefs.edit().putString("known_peers", known.toString()).apply();
        } catch (Exception ignored) {
            // Nothing stored.
        }
    }

    public void trustOutbound(String peerId, String token, String fingerprint, String name) {
        prefs.edit()
                .putString("out_token_" + peerId, token)
                .putString("out_fp_" + peerId, fingerprint)
                .putString("peer_name_" + peerId, name)
                .apply();
    }

    private JSONObject knownRaw() {
        try {
            return new JSONObject(prefs.getString("known_peers", "{}"));
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }

    /** Persist the latest address of a trusted peer so it reconnects after restarts. */
    public synchronized void remember(Peer peer) {
        try {
            JSONObject known = knownRaw();
            String encoded = peer.toJson().toString();
            if (encoded.equals(String.valueOf(known.optJSONObject(peer.deviceId)))) {
                return;
            }
            known.put(peer.deviceId, peer.toJson());
            prefs.edit().putString("known_peers", known.toString()).apply();
        } catch (Exception ignored) {
            // Best effort.
        }
    }

    public synchronized java.util.List<Peer> knownPeers() {
        java.util.List<Peer> result = new java.util.ArrayList<>();
        JSONObject known = knownRaw();
        java.util.Iterator<String> keys = known.keys();
        while (keys.hasNext()) {
            try {
                Peer peer = Peer.fromJson(known.getJSONObject(keys.next()));
                if (isOutboundTrusted(peer.deviceId)) {
                    result.add(peer);
                }
            } catch (Exception ignored) {
                // Skip malformed entries.
            }
        }
        return result;
    }

    public java.util.List<String> trustedPeerIds() {
        java.util.List<String> result = new java.util.ArrayList<>();
        for (String key : prefs.getAll().keySet()) {
            if (key.startsWith("out_token_")) {
                String id = key.substring("out_token_".length());
                if (isOutboundTrusted(id)) {
                    result.add(id);
                }
            }
        }
        return result;
    }

    public synchronized void appendHistory(String bucket, JSONObject entry) {
        try {
            JSONArray list = history(bucket);
            list.put(entry);
            while (list.length() > HISTORY_LIMIT) {
                list.remove(0);
            }
            prefs.edit().putString("history_" + bucket, list.toString()).apply();
        } catch (Exception ignored) {
            // History is best-effort and must never break a transfer.
        }
    }

    public synchronized JSONArray history(String bucket) {
        try {
            String raw = prefs.getString("history_" + bucket, null);
            return raw == null ? new JSONArray() : new JSONArray(raw);
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    public static String timestamp() {
        return java.text.DateFormat.getDateTimeInstance(
                java.text.DateFormat.MEDIUM,
                java.text.DateFormat.MEDIUM).format(new java.util.Date());
    }

    private static boolean constantTimeEquals(String left, String right) {
        byte[] a = left.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        byte[] b = right.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }

    public synchronized X509Certificate certificate() throws Exception {
        ensureTlsIdentity();
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return (X509Certificate) store.getCertificate(TLS_ALIAS);
    }

    public synchronized PrivateKey privateKey() throws Exception {
        ensureTlsIdentity();
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return (PrivateKey) store.getKey(TLS_ALIAS, null);
    }

    public String fingerprint() throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] encoded = certificate().getEncoded();
        return toHex(digest.digest(encoded));
    }

    private void ensureTlsIdentity() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(TLS_ALIAS)) {
            return;
        }

        Calendar start = Calendar.getInstance();
        start.add(Calendar.DAY_OF_MONTH, -1);
        Calendar end = Calendar.getInstance();
        end.add(Calendar.YEAR, 10);
        String commonName = deviceName().replaceAll("[^A-Za-z0-9._-]", "-");
        if (commonName.isEmpty()) {
            commonName = "h4xtor-share";
        }

        KeyPairGenerator generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_EC,
                "AndroidKeyStore");
        generator.initialize(new KeyGenParameterSpec.Builder(
                        TLS_ALIAS,
                        KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(new java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256,
                        KeyProperties.DIGEST_SHA384, KeyProperties.DIGEST_SHA512)
                .setCertificateSubject(new X500Principal("CN=" + commonName))
                .setCertificateSerialNumber(new BigInteger(64, new java.security.SecureRandom()).abs().add(BigInteger.ONE))
                .setCertificateNotBefore(start.getTime())
                .setCertificateNotAfter(end.getTime())
                .build());
        generator.generateKeyPair();
        if (store.containsAlias(LEGACY_TLS_ALIAS)) {
            // The certificate fingerprint changed, so every old pin is invalid: start clean.
            try {
                store.deleteEntry(LEGACY_TLS_ALIAS);
            } catch (Exception ignored) {
                // Leaving the unused legacy key behind is harmless.
            }
            SharedPreferences.Editor editor = prefs.edit();
            for (String key : prefs.getAll().keySet()) {
                if (key.startsWith("in_token_") || key.startsWith("out_token_") || key.startsWith("out_fp_")) {
                    editor.remove(key);
                }
            }
            editor.remove("known_peers").apply();
        }
    }

    public static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder(data.length * 2);
        for (byte value : data) {
            builder.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return builder.toString();
    }
}
