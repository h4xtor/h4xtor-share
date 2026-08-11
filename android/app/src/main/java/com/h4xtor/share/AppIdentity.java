package com.h4xtor.share;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

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
    private static final String PREFS = "h4xtor_share";
    private static final String TLS_ALIAS = "h4xtor_share_tls";

    private final SharedPreferences prefs;

    public AppIdentity(Context context) {
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!prefs.contains("device_id")) {
            prefs.edit().putString("device_id", UUID.randomUUID().toString().replace("-", "")).apply();
        }
        if (!prefs.contains("device_name")) {
            String model = Build.MODEL == null ? "Android" : Build.MODEL.trim();
            prefs.edit().putString("device_name", model.isEmpty() ? "Android" : model).apply();
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
        prefs.edit()
                .putString("out_token_" + peer.deviceId, token)
                .putString("out_fp_" + peer.deviceId, fingerprint)
                .putString("peer_name_" + peer.deviceId, name)
                .apply();
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
                KeyProperties.KEY_ALGORITHM_RSA,
                "AndroidKeyStore");
        generator.initialize(new KeyGenParameterSpec.Builder(
                        TLS_ALIAS,
                        KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY)
                .setKeySize(2048)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                .setCertificateSubject(new X500Principal("CN=" + commonName))
                .setCertificateSerialNumber(new BigInteger(64, new java.security.SecureRandom()).abs().add(BigInteger.ONE))
                .setCertificateNotBefore(start.getTime())
                .setCertificateNotAfter(end.getTime())
                .build());
        generator.generateKeyPair();
    }

    public static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder(data.length * 2);
        for (byte value : data) {
            builder.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return builder.toString();
    }
}
