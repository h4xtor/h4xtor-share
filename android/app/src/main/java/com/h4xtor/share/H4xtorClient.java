package com.h4xtor.share;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.UUID;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

public final class H4xtorClient {
    public interface ProgressListener {
        void onProgress(String fileName, long sent, long total);
    }

    private static final int CHUNK_SIZE = 1024 * 1024;
    private static final HostnameVerifier ALLOW_IP_HOSTNAME = (hostname, session) -> true;

    private final Context context;
    private final AppIdentity identity;

    public H4xtorClient(Context context, AppIdentity identity) {
        this.context = context.getApplicationContext();
        this.identity = identity;
    }

    public Peer getInfo(String address, int port, int timeoutMs) throws Exception {
        HttpsURLConnection connection = open(
                new URL("https://" + address + ":" + port + "/api/v1/info"),
                "GET",
                trustAllFactory(),
                timeoutMs);
        try {
            JSONObject object = readJson(connection);
            return Peer.fromInfo(object, address, port);
        } finally {
            connection.disconnect();
        }
    }

    public long ping(Peer peer, int timeoutMs) throws Exception {
        long start = System.currentTimeMillis();
        HttpsURLConnection connection = open(
                new URL(peer.endpoint() + "/api/v1/ping"),
                "GET",
                trustAllFactory(),
                timeoutMs);
        try {
            JSONObject object = readJson(connection);
            if (!object.optBoolean("pong", false)) {
                throw new IllegalStateException("Peer did not answer the ping");
            }
        } finally {
            connection.disconnect();
        }
        return System.currentTimeMillis() - start;
    }

    public JSONObject requestPairing(Peer peer) throws Exception {
        JSONObject body = new JSONObject()
                .put("device_id", identity.deviceId())
                .put("name", identity.deviceName());
        return jsonRequest(peer.endpoint() + "/api/v1/pair/request", "POST", body, null, null, 10_000);
    }

    public void confirmPairing(Peer peer, String pairingId, String code) throws Exception {
        JSONObject body = new JSONObject()
                .put("pairing_id", pairingId)
                .put("code", code);
        JSONObject response = jsonRequest(
                peer.endpoint() + "/api/v1/pair/confirm",
                "POST",
                body,
                null,
                null,
                10_000);
        String returnedFingerprint = response.getString("fingerprint");
        if (!MessageDigest.isEqual(
                returnedFingerprint.getBytes(StandardCharsets.US_ASCII),
                peer.fingerprint.getBytes(StandardCharsets.US_ASCII))) {
            throw new SecurityException("Peer certificate changed during pairing");
        }
        identity.trustOutbound(
                peer,
                response.getString("token"),
                returnedFingerprint,
                response.optString("name", peer.name));
    }

    public void sendClipboard(Peer peer, String text) throws Exception {
        requireTrusted(peer);
        JSONObject body = new JSONObject().put("text", text == null ? "" : text);
        jsonRequest(
                peer.endpoint() + "/api/v1/clipboard",
                "POST",
                body,
                peer,
                identity.outboundToken(peer.deviceId),
                30_000);
    }

    public void sendFile(Peer peer, Uri uri, ProgressListener listener) throws Exception {
        requireTrusted(peer);
        PreparedSource source = prepareSource(uri);
        try {
            String transferId = UUID.randomUUID().toString().replace("-", "");
            JSONObject initBody = new JSONObject()
                    .put("transfer_id", transferId)
                    .put("name", source.name)
                    .put("size", source.size);
            JSONObject metadata = jsonRequest(
                    peer.endpoint() + "/api/v1/files/init",
                    "POST",
                    initBody,
                    peer,
                    identity.outboundToken(peer.deviceId),
                    30_000);
            long offset = metadata.getLong("offset");
            if (offset < 0 || offset > source.size) {
                throw new IllegalStateException("Peer returned an invalid resume offset");
            }
            upload(peer, transferId, source, offset, listener);
        } finally {
            source.close();
        }
    }

    private void upload(
            Peer peer,
            String transferId,
            PreparedSource source,
            long offset,
            ProgressListener listener) throws Exception {
        String fingerprint = identity.outboundFingerprint(peer.deviceId);
        String token = identity.outboundToken(peer.deviceId);
        HttpsURLConnection connection = open(
                new URL(peer.endpoint() + "/api/v1/files/" + transferId),
                "PUT",
                pinnedFactory(fingerprint),
                60_000);
        connection.setReadTimeout(60_000);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("X-H4xtor-Device", identity.deviceId());
        connection.setRequestProperty("X-H4xtor-Offset", Long.toString(offset));
        connection.setRequestProperty("Content-Type", "application/octet-stream");
        connection.setDoOutput(true);
        long remaining = source.size - offset;
        connection.setFixedLengthStreamingMode(remaining);

        try (InputStream raw = source.open()) {
            skipFully(raw, offset);
            try (InputStream input = new BufferedInputStream(raw);
                 OutputStream output = new BufferedOutputStream(connection.getOutputStream())) {
                byte[] buffer = new byte[CHUNK_SIZE];
                long sent = offset;
                while (true) {
                    int read = input.read(buffer);
                    if (read < 0) {
                        break;
                    }
                    output.write(buffer, 0, read);
                    sent += read;
                    if (listener != null) {
                        listener.onProgress(source.name, sent, source.size);
                    }
                }
                output.flush();
            }
            JSONObject result = readJson(connection);
            if (!result.optBoolean("complete", false)) {
                throw new IllegalStateException("Transfer stopped before the complete file arrived");
            }
        } finally {
            connection.disconnect();
        }
    }

    private JSONObject jsonRequest(
            String endpoint,
            String method,
            JSONObject body,
            Peer peer,
            String token,
            int timeoutMs) throws Exception {
        SSLSocketFactory factory = peer == null
                ? trustAllFactory()
                : pinnedFactory(identity.outboundFingerprint(peer.deviceId));
        HttpsURLConnection connection = open(new URL(endpoint), method, factory, timeoutMs);
        if (peer != null) {
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("X-H4xtor-Device", identity.deviceId());
        }
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setDoOutput(true);
        byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(data.length);
        try (OutputStream output = connection.getOutputStream()) {
            output.write(data);
        }
        try {
            return readJson(connection);
        } finally {
            connection.disconnect();
        }
    }

    private static HttpsURLConnection open(
            URL url,
            String method,
            SSLSocketFactory sslFactory,
            int timeoutMs) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
        connection.setRequestMethod(method);
        connection.setSSLSocketFactory(sslFactory);
        connection.setHostnameVerifier(ALLOW_IP_HOSTNAME);
        connection.setConnectTimeout(timeoutMs);
        connection.setReadTimeout(timeoutMs);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", "application/json");
        return connection;
    }

    private static JSONObject readJson(HttpURLConnection connection) throws Exception {
        int status = connection.getResponseCode();
        InputStream stream = status >= 200 && status < 300
                ? connection.getInputStream()
                : connection.getErrorStream();
        String text = stream == null ? "" : readText(stream);
        if (status < 200 || status >= 300) {
            throw new IllegalStateException("HTTP " + status + (text.isEmpty() ? "" : ": " + text));
        }
        return text.isEmpty() ? new JSONObject() : new JSONObject(text);
    }

    private static String readText(InputStream input) throws Exception {
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = stream.read(buffer)) >= 0) {
                output.write(buffer, 0, read);
            }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }

    private void requireTrusted(Peer peer) {
        if (!identity.isOutboundTrusted(peer.deviceId)) {
            throw new IllegalStateException("Pair with this device before sending data");
        }
    }

    private static SSLSocketFactory trustAllFactory() throws Exception {
        X509TrustManager trustManager = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] chain, String authType) { }
            @Override public void checkServerTrusted(X509Certificate[] chain, String authType) { }
            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, new TrustManager[]{trustManager}, new SecureRandom());
        return context.getSocketFactory();
    }

    private static SSLSocketFactory pinnedFactory(String fingerprint) throws Exception {
        if (fingerprint == null || fingerprint.length() != 64) {
            throw new SecurityException("Missing or invalid peer certificate fingerprint");
        }
        final String expected = fingerprint.toLowerCase(java.util.Locale.ROOT);
        X509TrustManager trustManager = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] chain, String authType) { }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String authType)
                    throws java.security.cert.CertificateException {
                if (chain == null || chain.length == 0) {
                    throw new java.security.cert.CertificateException("Peer sent no certificate");
                }
                try {
                    MessageDigest digest = MessageDigest.getInstance("SHA-256");
                    String actual = AppIdentity.toHex(digest.digest(chain[0].getEncoded()));
                    if (!MessageDigest.isEqual(
                            actual.getBytes(StandardCharsets.US_ASCII),
                            expected.getBytes(StandardCharsets.US_ASCII))) {
                        throw new java.security.cert.CertificateException("Peer certificate pin mismatch");
                    }
                } catch (java.security.cert.CertificateException error) {
                    throw error;
                } catch (Exception error) {
                    throw new java.security.cert.CertificateException(error);
                }
            }

            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, new TrustManager[]{trustManager}, new SecureRandom());
        return context.getSocketFactory();
    }

    private PreparedSource prepareSource(Uri uri) throws Exception {
        ContentResolver resolver = context.getContentResolver();
        String name = "file.bin";
        long size = -1;
        try (Cursor cursor = resolver.query(uri, new String[]{
                OpenableColumns.DISPLAY_NAME,
                OpenableColumns.SIZE
        }, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE);
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) {
                    name = cursor.getString(nameIndex);
                }
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) {
                    size = cursor.getLong(sizeIndex);
                }
            }
        }
        if (size >= 0) {
            final String finalName = name;
            final long finalSize = size;
            return new PreparedSource(finalName, finalSize, () -> {
                InputStream input = resolver.openInputStream(uri);
                if (input == null) throw new IllegalStateException("Cannot open selected file");
                return input;
            }, null);
        }

        File temporary = File.createTempFile("h4xtor-send-", ".tmp", context.getCacheDir());
        try (InputStream input = resolver.openInputStream(uri);
             OutputStream output = new FileOutputStream(temporary)) {
            if (input == null) {
                throw new IllegalStateException("Cannot open selected file");
            }
            byte[] buffer = new byte[CHUNK_SIZE];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                output.write(buffer, 0, read);
            }
        }
        String finalName = name;
        return new PreparedSource(finalName, temporary.length(), () -> new FileInputStream(temporary), temporary);
    }

    private static void skipFully(InputStream input, long offset) throws Exception {
        long remaining = offset;
        while (remaining > 0) {
            long skipped = input.skip(remaining);
            if (skipped <= 0) {
                if (input.read() < 0) {
                    throw new IllegalStateException("Cannot resume beyond the selected file size");
                }
                skipped = 1;
            }
            remaining -= skipped;
        }
    }

    private interface StreamFactory {
        InputStream open() throws Exception;
    }

    private static final class PreparedSource implements AutoCloseable {
        final String name;
        final long size;
        final StreamFactory streamFactory;
        final File temporary;

        PreparedSource(String name, long size, StreamFactory streamFactory, File temporary) {
            this.name = name;
            this.size = size;
            this.streamFactory = streamFactory;
            this.temporary = temporary;
        }

        InputStream open() throws Exception {
            return streamFactory.open();
        }

        @Override
        public void close() {
            if (temporary != null) {
                //noinspection ResultOfMethodCallIgnored
                temporary.delete();
            }
        }
    }
}
