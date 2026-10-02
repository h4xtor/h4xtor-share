package com.h4xtor.share;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** Client side of the h4xtor-share protocol. */
public final class H4xtorClient {
    public interface ProgressListener {
        void onProgress(String name, long sent, long total);
    }

    /** Lets the UI abort a running transfer; the receiver keeps the bytes for a later resume. */
    public static final class CancelToken {
        private final AtomicBoolean cancelled = new AtomicBoolean(false);
        private volatile HttpURLConnection connection;

        public void cancel() {
            cancelled.set(true);
            HttpURLConnection current = connection;
            if (current != null) {
                try {
                    current.disconnect();
                } catch (Exception ignored) {
                    // Already closed.
                }
            }
        }

        public boolean isCancelled() {
            return cancelled.get();
        }

        void attach(HttpURLConnection value) throws CancelledException {
            connection = value;
            if (cancelled.get()) {
                value.disconnect();
                throw new CancelledException();
            }
        }

        void check() throws CancelledException {
            if (cancelled.get()) {
                throw new CancelledException();
            }
        }
    }

    public static final class CancelledException extends InterruptedIOException {
        CancelledException() {
            super("Annulleret");
        }
    }

    private static final int CHUNK_SIZE = 1024 * 1024;
    private static final HostnameVerifier ALLOW_IP_HOSTNAME = (hostname, session) -> true;

    private final Context context;
    private final AppIdentity identity;
    private final Map<String, String> resumable = new ConcurrentHashMap<>();

    public H4xtorClient(Context context, AppIdentity identity) {
        this.context = context.getApplicationContext();
        this.identity = identity;
    }

    public Peer getInfo(String address, int port, int timeoutMs) throws Exception {
        return getInfo(address, port, timeoutMs, null);
    }

    public Peer getInfo(String address, int port, int timeoutMs, String expectedFingerprint) throws Exception {
        SSLSocketFactory factory = expectedFingerprint != null && expectedFingerprint.length() == 64
                ? pinnedFactory(expectedFingerprint)
                : trustAllFactory();
        HttpsURLConnection connection = open(
                new URL("https://" + address + ":" + port + "/api/v1/info"), "GET", factory, timeoutMs);
        try {
            return Peer.fromInfo(readJson(connection), address, port);
        } finally {
            connection.disconnect();
        }
    }

    public long ping(Peer peer, int timeoutMs) throws Exception {
        long start = System.currentTimeMillis();
        HttpsURLConnection connection = open(
                new URL(peer.endpoint() + "/api/v1/ping"), "GET", trustAllFactory(), timeoutMs);
        try {
            JSONObject answer = readJson(connection);
            if (!answer.optBoolean("pong", false)) {
                throw new IllegalStateException("Peer did not answer the ping");
            }
            String answered = answer.optString("device_id", "");
            if (!answered.isEmpty() && !answered.equals(peer.deviceId)) {
                // Another device (or a reinstalled app with a new id) now owns this address.
                throw new IllegalStateException("A different device answered");
            }
        } finally {
            connection.disconnect();
        }
        return System.currentTimeMillis() - start;
    }

    // ---------------------------------------------------------------- pairing
    public JSONObject requestPairing(Peer peer) throws Exception {
        JSONObject body = new JSONObject()
                .put("device_id", identity.deviceId())
                .put("name", identity.deviceName());
        return jsonRequest(peer.endpoint() + "/api/v1/pair/request", "POST", body,
                pairingFactory(peer.fingerprint), null, 10_000);
    }

    private JSONObject reverseCredentials(String peerId, String peerName) throws Exception {
        byte[] bytes = new byte[48];
        new SecureRandom().nextBytes(bytes);
        String token = android.util.Base64.encodeToString(
                bytes,
                android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
        identity.trustInbound(peerId, token, peerName);
        JSONArray capabilities = new JSONArray();
        for (String capability : AppIdentity.CAPABILITIES) {
            capabilities.put(capability);
        }
        return new JSONObject()
                .put("token", token)
                .put("fingerprint", identity.fingerprint())
                .put("port", AppIdentity.PORT)
                .put("platform", "android")
                .put("capabilities", capabilities);
    }

    public void confirmPairing(Peer peer, String pairingId, String code) throws Exception {
        JSONObject body = new JSONObject()
                .put("pairing_id", pairingId)
                .put("code", code)
                .put("reverse", reverseCredentials(peer.deviceId, peer.name));
        JSONObject response = jsonRequest(peer.endpoint() + "/api/v1/pair/confirm", "POST", body,
                pairingFactory(peer.fingerprint), null, 10_000);
        storePairing(peer, response);
    }

    /** Pair with a device whose QR code was scanned. Returns the paired peer. */
    public Peer pairWithInvite(PairingInvite invite) throws Exception {
        Exception last = null;
        for (String address : invite.addresses) {
            Peer peer;
            try {
                peer = getInfo(address, invite.port, 3_500, invite.fingerprint);
            } catch (Exception error) {
                last = error;
                continue;
            }
            if (!peer.deviceId.equals(invite.deviceId)) {
                last = new IllegalStateException("QR-koden hører til en anden enhed");
                continue;
            }
            JSONObject body = new JSONObject()
                    .put("secret", invite.secret)
                    .put("device_id", identity.deviceId())
                    .put("name", identity.deviceName())
                    .put("reverse", reverseCredentials(peer.deviceId, peer.name));
            JSONObject response = jsonRequest(peer.endpoint() + "/api/v1/pair/qr", "POST", body,
                    pinnedFactory(invite.fingerprint), null, 10_000);
            storePairing(peer, response);
            return peer;
        }
        throw new IllegalStateException("Kunne ikke nå enheden fra QR-koden. Er I på samme netværk?"
                + (last == null ? "" : " (" + safeMessage(last) + ")"));
    }

    private void storePairing(Peer peer, JSONObject response) throws Exception {
        String returnedFingerprint = response.getString("fingerprint").toLowerCase(java.util.Locale.ROOT);
        if (!MessageDigest.isEqual(
                returnedFingerprint.getBytes(StandardCharsets.US_ASCII),
                peer.fingerprint.getBytes(StandardCharsets.US_ASCII))) {
            throw new SecurityException("Enhedens certifikat ændrede sig under parringen");
        }
        identity.trustOutbound(peer, response.getString("token"), returnedFingerprint,
                response.optString("name", peer.name));
    }

    public void unpair(Peer peer) {
        try {
            if (peer.supports("unpair") && identity.isOutboundTrusted(peer.deviceId)) {
                authedPost(peer, "/api/v1/unpair", new JSONObject(), 4_000);
            }
        } catch (Exception ignored) {
            // The local forget must always happen.
        } finally {
            identity.forget(peer.deviceId);
        }
    }

    // ------------------------------------------------------------- messaging
    public void sendClipboard(Peer peer, String text) throws Exception {
        authedPost(peer, "/api/v1/clipboard", new JSONObject().put("text", text == null ? "" : text), 30_000);
    }

    public void sendLink(Peer peer, String url) throws Exception {
        if (!peer.supports("links")) {
            sendClipboard(peer, url);
            return;
        }
        authedPost(peer, "/api/v1/link", new JSONObject().put("url", url), 15_000);
    }

    public void sendWifiDirectOffer(Peer peer, String ssid, String passphrase) throws Exception {
        authedPost(peer, "/api/v1/wifi-direct/offer", new JSONObject()
                .put("ssid", ssid)
                .put("passphrase", passphrase)
                .put("owner_address", WifiDirectController.GROUP_OWNER_ADDRESS)
                .put("port", AppIdentity.PORT), 15_000);
    }

    private JSONObject authedPost(Peer peer, String path, JSONObject body, int timeoutMs) throws Exception {
        requireTrusted(peer);
        return jsonRequest(peer.endpoint() + path, "POST", body,
                pinnedFactory(identity.outboundFingerprint(peer.deviceId)),
                identity.outboundToken(peer.deviceId), timeoutMs);
    }

    // ------------------------------------------------------------------ files
    public static final class SourceInfo {
        public final String name;
        public final long size;

        SourceInfo(String name, long size) {
            this.name = name;
            this.size = size;
        }
    }

    public SourceInfo describe(Uri uri) {
        String name = "fil";
        long size = -1;
        try (Cursor cursor = context.getContentResolver().query(uri, new String[]{
                OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
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
        } catch (Exception ignored) {
            // Fall back to defaults.
        }
        return new SourceInfo(name, size);
    }

    public void sendFile(Peer peer, Uri uri, ProgressListener listener, CancelToken cancel) throws Exception {
        requireTrusted(peer);
        PreparedSource source = prepareSource(uri);
        String key = peer.deviceId + "|" + uri;
        String transferId = resumable.remove(key);
        if (transferId == null) {
            transferId = UUID.randomUUID().toString().replace("-", "");
        }
        try {
            JSONObject metadata = authedPost(peer, "/api/v1/files/init", new JSONObject()
                    .put("transfer_id", transferId)
                    .put("name", source.name)
                    .put("size", source.size), 30_000);
            long offset = metadata.getLong("offset");
            if (offset < 0 || offset > source.size) {
                throw new IllegalStateException("Peer returned an invalid resume offset");
            }
            JSONObject result = upload(peer, "/api/v1/files/" + transferId, source, offset,
                    (sent, total) -> listener.onProgress(source.name, sent, total), cancel);
            if (!result.optBoolean("complete", false)) {
                throw new IllegalStateException("Overførslen stoppede før hele filen var modtaget");
            }
        } catch (Exception error) {
            resumable.put(key, transferId);
            throw error;
        } finally {
            source.close();
        }
    }

    private static final class TreeEntry {
        final String id = UUID.randomUUID().toString().replace("-", "");
        final String relative;
        final Uri uri;
        final long size;

        TreeEntry(String relative, Uri uri, long size) {
            this.relative = relative;
            this.uri = uri;
            this.size = size;
        }
    }

    /** Name of a folder picked with ACTION_OPEN_DOCUMENT_TREE. */
    public String treeName(Uri treeUri) {
        try {
            Uri documentUri = DocumentsContract.buildDocumentUriUsingTree(
                    treeUri, DocumentsContract.getTreeDocumentId(treeUri));
            try (Cursor cursor = context.getContentResolver().query(documentUri,
                    new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME}, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    return cursor.getString(0);
                }
            }
        } catch (Exception ignored) {
            // Fall through.
        }
        return "Mappe";
    }

    private void walkTree(Uri treeUri, String documentId, String prefix, List<TreeEntry> out) {
        ContentResolver resolver = context.getContentResolver();
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, documentId);
        try (Cursor cursor = resolver.query(children, new String[]{
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                DocumentsContract.Document.COLUMN_SIZE}, null, null, null)) {
            if (cursor == null) {
                return;
            }
            while (cursor.moveToNext()) {
                String id = cursor.getString(0);
                String name = cursor.getString(1);
                String mime = cursor.getString(2);
                long size = cursor.isNull(3) ? 0L : cursor.getLong(3);
                String relative = prefix.isEmpty() ? name : prefix + "/" + name;
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    walkTree(treeUri, id, relative, out);
                } else {
                    out.add(new TreeEntry(relative, DocumentsContract.buildDocumentUriUsingTree(treeUri, id), size));
                }
                if (out.size() > 10_000) {
                    throw new IllegalStateException("Mappen indeholder for mange filer");
                }
            }
        }
    }

    public void sendFolder(Peer peer, Uri treeUri, ProgressListener listener, CancelToken cancel)
            throws Exception {
        requireTrusted(peer);
        if (!peer.supports("folders")) {
            throw new IllegalStateException(peer.name + " kan ikke modtage mapper");
        }
        String folderName = treeName(treeUri);
        List<TreeEntry> entries = new ArrayList<>();
        walkTree(treeUri, DocumentsContract.getTreeDocumentId(treeUri), "", entries);
        if (entries.isEmpty()) {
            throw new IllegalStateException("Mappen er tom");
        }
        String folderId = UUID.randomUUID().toString().replace("-", "");
        JSONArray manifest = new JSONArray();
        long total = 0L;
        for (TreeEntry entry : entries) {
            manifest.put(new JSONObject().put("id", entry.id).put("path", entry.relative).put("size", entry.size));
            total += entry.size;
        }
        JSONObject initialized = authedPost(peer, "/api/v1/folders/init", new JSONObject()
                .put("folder_id", folderId)
                .put("name", folderName)
                .put("entries", manifest), 60_000);
        Map<String, Long> offsets = new ConcurrentHashMap<>();
        JSONArray returned = initialized.optJSONArray("entries");
        if (returned != null) {
            for (int index = 0; index < returned.length(); index++) {
                JSONObject item = returned.getJSONObject(index);
                offsets.put(item.getString("id"), item.optLong("offset", 0L));
            }
        }
        long done = 0L;
        for (TreeEntry entry : entries) {
            cancel.check();
            long offset = offsets.getOrDefault(entry.id, 0L);
            final long base = done;
            final long folderTotal = total;
            PreparedSource source = new PreparedSource(entry.relative, entry.size, () -> {
                InputStream input = context.getContentResolver().openInputStream(entry.uri);
                if (input == null) throw new IllegalStateException("Kan ikke åbne " + entry.relative);
                return input;
            }, null);
            // Always PUT, even for complete parts: the receiver marks the entry as done.
            JSONObject result = upload(peer, "/api/v1/folders/" + folderId + "/" + entry.id, source,
                    Math.min(offset, entry.size),
                    (sent, size) -> listener.onProgress(folderName, base + sent, folderTotal), cancel);
            if (!result.optBoolean("complete", false)) {
                throw new IllegalStateException("Mappeoverførslen stoppede undervejs");
            }
            done += entry.size;
            listener.onProgress(folderName, done, total);
        }
        authedPost(peer, "/api/v1/folders/complete", new JSONObject().put("folder_id", folderId), 60_000);
        listener.onProgress(folderName, total, total);
    }

    private interface ByteProgress {
        void onProgress(long sent, long total);
    }

    private JSONObject upload(
            Peer peer,
            String path,
            PreparedSource source,
            long offset,
            ByteProgress listener,
            CancelToken cancel) throws Exception {
        String fingerprint = identity.outboundFingerprint(peer.deviceId);
        String token = identity.outboundToken(peer.deviceId);
        HttpsURLConnection connection = open(new URL(peer.endpoint() + path), "PUT", pinnedFactory(fingerprint), 60_000);
        cancel.attach(connection);
        connection.setReadTimeout(120_000);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("X-H4xtor-Device", identity.deviceId());
        connection.setRequestProperty("X-H4xtor-Offset", Long.toString(offset));
        connection.setRequestProperty("Content-Type", "application/octet-stream");
        connection.setDoOutput(true);
        connection.setFixedLengthStreamingMode(source.size - offset);
        try (InputStream raw = source.open()) {
            skipFully(raw, offset);
            try (InputStream input = new BufferedInputStream(raw, CHUNK_SIZE);
                 OutputStream output = new BufferedOutputStream(connection.getOutputStream(), CHUNK_SIZE)) {
                byte[] buffer = new byte[CHUNK_SIZE];
                long sent = offset;
                listener.onProgress(sent, source.size);
                while (true) {
                    cancel.check();
                    int read = input.read(buffer);
                    if (read < 0) {
                        break;
                    }
                    output.write(buffer, 0, read);
                    sent += read;
                    listener.onProgress(sent, source.size);
                }
                output.flush();
            }
            return readJson(connection);
        } catch (Exception error) {
            if (cancel.isCancelled()) {
                throw new CancelledException();
            }
            throw error;
        } finally {
            connection.disconnect();
        }
    }

    // ---------------------------------------------------------------- plumbing
    private JSONObject jsonRequest(
            String endpoint,
            String method,
            JSONObject body,
            SSLSocketFactory factory,
            String token,
            int timeoutMs) throws Exception {
        HttpsURLConnection connection = open(new URL(endpoint), method, factory, timeoutMs);
        if (token != null) {
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

    private static HttpsURLConnection open(URL url, String method, SSLSocketFactory sslFactory, int timeoutMs)
            throws Exception {
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
        InputStream stream = status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream();
        String text = stream == null ? "" : readText(stream);
        if (status < 200 || status >= 300) {
            throw new IllegalStateException(text.isEmpty() ? "HTTP " + status : text);
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
            throw new IllegalStateException("Forbind med enheden først");
        }
    }

    private static SSLSocketFactory pairingFactory(String fingerprint) throws Exception {
        return fingerprint != null && fingerprint.length() == 64 ? pinnedFactory(fingerprint) : trustAllFactory();
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
        SourceInfo info = describe(uri);
        if (info.size >= 0) {
            return new PreparedSource(info.name, info.size, () -> {
                InputStream input = resolver.openInputStream(uri);
                if (input == null) throw new IllegalStateException("Kan ikke åbne filen");
                return input;
            }, null);
        }
        File temporary = File.createTempFile("h4xtor-send-", ".tmp", context.getCacheDir());
        try (InputStream input = resolver.openInputStream(uri); OutputStream output = new FileOutputStream(temporary)) {
            if (input == null) {
                throw new IllegalStateException("Kan ikke åbne filen");
            }
            byte[] buffer = new byte[CHUNK_SIZE];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                output.write(buffer, 0, read);
            }
        }
        return new PreparedSource(info.name, temporary.length(), () -> new FileInputStream(temporary), temporary);
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

    static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? error.getClass().getSimpleName() : message;
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
