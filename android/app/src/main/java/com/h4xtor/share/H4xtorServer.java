package com.h4xtor.share;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.os.Environment;
import android.provider.MediaStore;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.Principal;
import java.security.PrivateKey;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.KeyManager;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLServerSocketFactory;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.X509KeyManager;

public final class H4xtorServer {
    public interface Listener {
        void onPairingCode(String peerName, String code);
        void onClipboardReceived(String peerName, String text);
        void onFileReceived(String peerName, String fileName);
        void onStatus(String text);
    }

    private static final long PAIRING_TTL_MS = 120_000L;
    private static final int JSON_BODY_LIMIT = 1024 * 1024;
    private static final int BUFFER_SIZE = 1024 * 1024;

    private final Context context;
    private final AppIdentity identity;
    private final Listener listener;
    private final Map<String, PendingPairing> pairings = new ConcurrentHashMap<>();
    private final Map<String, Transfer> transfers = new ConcurrentHashMap<>();
    private final ExecutorService clients = Executors.newCachedThreadPool();
    private final AtomicBoolean running = new AtomicBoolean(false);

    private Thread acceptThread;
    private SSLServerSocket serverSocket;

    public H4xtorServer(Context context, AppIdentity identity, Listener listener) {
        this.context = context.getApplicationContext();
        this.identity = identity;
        this.listener = listener;
    }

    public synchronized void start() throws Exception {
        if (running.get()) {
            return;
        }
        X509Certificate certificate = identity.certificate();
        PrivateKey privateKey = identity.privateKey();
        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(
                new KeyManager[]{new SingleKeyManager(privateKey, certificate)},
                null,
                new SecureRandom());
        SSLServerSocketFactory factory = sslContext.getServerSocketFactory();
        serverSocket = (SSLServerSocket) factory.createServerSocket(AppIdentity.PORT);
        serverSocket.setReuseAddress(true);
        running.set(true);
        acceptThread = new Thread(this::acceptLoop, "h4xtor-server");
        acceptThread.setDaemon(true);
        acceptThread.start();
        listener.onStatus("Online locally on port " + AppIdentity.PORT);
    }

    public synchronized void stop() {
        running.set(false);
        if (serverSocket != null) {
            try {
                serverSocket.close();
            } catch (Exception ignored) {
                // Closing is best-effort during activity shutdown.
            }
        }
        serverSocket = null;
        if (acceptThread != null) {
            try {
                acceptThread.join(1_000L);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            }
        }
        acceptThread = null;
    }

    private void acceptLoop() {
        while (running.get()) {
            try {
                Socket socket = serverSocket.accept();
                clients.execute(() -> handle(socket));
            } catch (Exception error) {
                if (running.get()) {
                    listener.onStatus("Server error: " + safeMessage(error));
                }
            }
        }
    }

    private void handle(Socket rawSocket) {
        try (SSLSocket socket = (SSLSocket) rawSocket) {
            socket.setSoTimeout(60_000);
            socket.startHandshake();
            BufferedInputStream input = new BufferedInputStream(socket.getInputStream());
            BufferedOutputStream output = new BufferedOutputStream(socket.getOutputStream());
            Request request = readRequest(input);
            route(request, input, output);
            output.flush();
        } catch (Exception ignored) {
            // Peers routinely disconnect during LAN scans; that is not a user-facing error.
        }
    }

    private void route(Request request, BufferedInputStream input, BufferedOutputStream output)
            throws Exception {
        if ("GET".equals(request.method) && "/api/v1/info".equals(request.path)) {
            JSONObject body = new JSONObject()
                    .put("protocol", 1)
                    .put("device_id", identity.deviceId())
                    .put("name", identity.deviceName())
                    .put("platform", "android")
                    .put("port", AppIdentity.PORT)
                    .put("fingerprint", identity.fingerprint())
                    .put("capabilities", new org.json.JSONArray()
                            .put("clipboard")
                            .put("files")
                            .put("resume"));
            sendJson(output, 200, body);
            return;
        }

        if ("POST".equals(request.method) && "/api/v1/pair/request".equals(request.path)) {
            JSONObject body = readJsonBody(request, input);
            String peerId = body.optString("device_id", "").trim();
            String peerName = body.optString("name", "Unknown device").trim();
            if (!peerId.matches("[a-f0-9]{32}")) {
                sendText(output, 400, "Invalid device id.");
                return;
            }
            if (peerName.length() > 80) {
                peerName = peerName.substring(0, 80);
            }
            String pairingId = UUID.randomUUID().toString().replace("-", "");
            String code = String.format(Locale.ROOT, "%06d", new SecureRandom().nextInt(1_000_000));
            pairings.put(pairingId, new PendingPairing(peerId, peerName, code, System.currentTimeMillis() + PAIRING_TTL_MS));
            listener.onPairingCode(peerName, code);
            sendJson(output, 200, new JSONObject()
                    .put("pairing_id", pairingId)
                    .put("expires_in", 120));
            return;
        }

        if ("POST".equals(request.method) && "/api/v1/pair/confirm".equals(request.path)) {
            JSONObject body = readJsonBody(request, input);
            String pairingId = body.optString("pairing_id", "");
            String code = body.optString("code", "");
            PendingPairing pending = pairings.remove(pairingId);
            if (pending == null || pending.expiresAt < System.currentTimeMillis()) {
                sendText(output, 401, "Pairing request expired.");
                return;
            }
            if (!java.security.MessageDigest.isEqual(
                    pending.code.getBytes(StandardCharsets.US_ASCII),
                    code.getBytes(StandardCharsets.US_ASCII))) {
                sendText(output, 401, "Incorrect pairing code.");
                return;
            }
            String token = randomToken();
            identity.trustInbound(pending.peerId, token, pending.peerName);
            sendJson(output, 200, new JSONObject()
                    .put("token", token)
                    .put("device_id", identity.deviceId())
                    .put("name", identity.deviceName())
                    .put("fingerprint", identity.fingerprint()));
            return;
        }

        Auth auth = authenticate(request);
        if (auth == null) {
            sendText(output, 401, "Peer is not trusted.");
            return;
        }

        if ("POST".equals(request.method) && "/api/v1/clipboard".equals(request.path)) {
            JSONObject body = readJsonBody(request, input);
            if (!body.has("text")) {
                sendText(output, 400, "Clipboard payload must contain text.");
                return;
            }
            String text = body.getString("text");
            listener.onClipboardReceived(auth.peerName, text);
            sendJson(output, 200, new JSONObject()
                    .put("accepted", true)
                    .put("characters", text.length()));
            return;
        }

        if ("POST".equals(request.method) && "/api/v1/files/init".equals(request.path)) {
            JSONObject body = readJsonBody(request, input);
            String transferId = body.optString("transfer_id", "");
            if (!transferId.matches("[a-f0-9]{32}")) {
                sendText(output, 400, "Invalid transfer id.");
                return;
            }
            String fileName;
            long size;
            try {
                fileName = safeFileName(body.optString("name", ""));
                size = body.getLong("size");
            } catch (Exception error) {
                sendText(output, 400, "Invalid file metadata.");
                return;
            }
            if (size < 0) {
                sendText(output, 400, "Invalid file size.");
                return;
            }
            File directory = incomingDirectory();
            //noinspection ResultOfMethodCallIgnored
            directory.mkdirs();
            File part = new File(directory, ".h4xtor-" + transferId + ".part");
            long offset = part.exists() ? part.length() : 0L;
            if (offset > size) {
                //noinspection ResultOfMethodCallIgnored
                part.delete();
                offset = 0L;
            }
            transfers.put(transferId, new Transfer(auth.peerName, fileName, size, part));
            sendJson(output, 200, new JSONObject()
                    .put("transfer_id", transferId)
                    .put("offset", offset));
            return;
        }

        if ("PUT".equals(request.method) && request.path.startsWith("/api/v1/files/")) {
            String transferId = request.path.substring("/api/v1/files/".length());
            Transfer transfer = transfers.get(transferId);
            if (transfer == null) {
                sendText(output, 404, "Transfer was not initialized.");
                return;
            }
            long requestedOffset;
            try {
                requestedOffset = Long.parseLong(request.headers.getOrDefault("x-h4xtor-offset", "-1"));
            } catch (NumberFormatException error) {
                sendText(output, 400, "Invalid transfer offset.");
                return;
            }
            long actualOffset = transfer.part.exists() ? transfer.part.length() : 0L;
            if (requestedOffset != actualOffset) {
                Map<String, String> extra = new HashMap<>();
                extra.put("X-H4xtor-Offset", Long.toString(actualOffset));
                sendText(output, 409, Long.toString(actualOffset), extra);
                return;
            }

            try (FileOutputStream file = new FileOutputStream(transfer.part, true)) {
                actualOffset = copyRequestBody(request, input, file, actualOffset, transfer.size);
            }
            boolean complete = actualOffset == transfer.size;
            if (complete) {
                publishToDownloads(transfer.part, transfer.name);
                //noinspection ResultOfMethodCallIgnored
                transfer.part.delete();
                transfers.remove(transferId);
                listener.onFileReceived(transfer.peerName, transfer.name);
            }
            sendJson(output, 200, new JSONObject()
                    .put("transfer_id", transferId)
                    .put("offset", actualOffset)
                    .put("complete", complete));
            return;
        }

        sendText(output, 404, "Not found.");
    }

    private Auth authenticate(Request request) {
        String peerId = request.headers.getOrDefault("x-h4xtor-device", "");
        String authorization = request.headers.getOrDefault("authorization", "");
        if (!authorization.startsWith("Bearer ")) {
            return null;
        }
        String token = authorization.substring("Bearer ".length()).trim();
        if (!identity.validateInbound(peerId, token)) {
            return null;
        }
        return new Auth(peerId, identity.peerName(peerId));
    }

    private static Request readRequest(InputStream input) throws Exception {
        String requestLine = readLine(input, 8192);
        if (requestLine == null || requestLine.isEmpty()) {
            throw new IllegalArgumentException("Missing request line");
        }
        String[] parts = requestLine.split(" ");
        if (parts.length < 2) {
            throw new IllegalArgumentException("Invalid request line");
        }
        Map<String, String> headers = new HashMap<>();
        while (true) {
            String line = readLine(input, 16_384);
            if (line == null || line.isEmpty()) {
                break;
            }
            int colon = line.indexOf(':');
            if (colon <= 0) {
                continue;
            }
            headers.put(
                    line.substring(0, colon).trim().toLowerCase(Locale.ROOT),
                    line.substring(colon + 1).trim());
        }
        String path = parts[1];
        int query = path.indexOf('?');
        if (query >= 0) {
            path = path.substring(0, query);
        }
        return new Request(parts[0].toUpperCase(Locale.ROOT), path, headers);
    }

    private static String readLine(InputStream input, int maxBytes) throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        while (buffer.size() < maxBytes) {
            int value = input.read();
            if (value < 0) {
                return buffer.size() == 0 ? null : buffer.toString(StandardCharsets.US_ASCII.name());
            }
            if (value == '\n') {
                break;
            }
            if (value != '\r') {
                buffer.write(value);
            }
        }
        if (buffer.size() >= maxBytes) {
            throw new IllegalArgumentException("HTTP line is too long");
        }
        return buffer.toString(StandardCharsets.US_ASCII.name());
    }

    private static JSONObject readJsonBody(Request request, InputStream input) throws Exception {
        long length = contentLength(request);
        if (length < 0 || length > JSON_BODY_LIMIT) {
            throw new IllegalArgumentException("Invalid JSON body length");
        }
        byte[] data = readExact(input, (int) length);
        return new JSONObject(new String(data, StandardCharsets.UTF_8));
    }

    private static long copyRequestBody(
            Request request,
            InputStream input,
            OutputStream output,
            long currentOffset,
            long totalSize) throws Exception {
        String transferEncoding = request.headers.getOrDefault("transfer-encoding", "");
        if (transferEncoding.toLowerCase(Locale.ROOT).contains("chunked")) {
            long offset = currentOffset;
            while (true) {
                String sizeLine = readLine(input, 128);
                if (sizeLine == null) {
                    throw new IllegalStateException("Unexpected end of chunked request");
                }
                int semicolon = sizeLine.indexOf(';');
                String rawSize = (semicolon >= 0 ? sizeLine.substring(0, semicolon) : sizeLine).trim();
                int chunkSize = Integer.parseInt(rawSize, 16);
                if (chunkSize == 0) {
                    while (true) {
                        String trailer = readLine(input, 8192);
                        if (trailer == null || trailer.isEmpty()) {
                            break;
                        }
                    }
                    break;
                }
                if (offset + chunkSize > totalSize) {
                    throw new IllegalArgumentException("Received more bytes than declared");
                }
                copyExact(input, output, chunkSize);
                offset += chunkSize;
                String afterChunk = readLine(input, 2);
                if (afterChunk == null || !afterChunk.isEmpty()) {
                    throw new IllegalArgumentException("Malformed chunked request");
                }
            }
            return offset;
        }

        long length = contentLength(request);
        if (length < 0) {
            throw new IllegalArgumentException("Missing request body length");
        }
        if (currentOffset + length > totalSize) {
            throw new IllegalArgumentException("Received more bytes than declared");
        }
        copyExact(input, output, length);
        return currentOffset + length;
    }

    private static long contentLength(Request request) {
        try {
            return Long.parseLong(request.headers.getOrDefault("content-length", "-1"));
        } catch (NumberFormatException error) {
            return -1L;
        }
    }

    private static byte[] readExact(InputStream input, int length) throws Exception {
        byte[] result = new byte[length];
        int offset = 0;
        while (offset < length) {
            int read = input.read(result, offset, length - offset);
            if (read < 0) {
                throw new IllegalStateException("Unexpected end of request body");
            }
            offset += read;
        }
        return result;
    }

    private static void copyExact(InputStream input, OutputStream output, long length) throws Exception {
        byte[] buffer = new byte[BUFFER_SIZE];
        long remaining = length;
        while (remaining > 0) {
            int read = input.read(buffer, 0, (int) Math.min(buffer.length, remaining));
            if (read < 0) {
                throw new IllegalStateException("Unexpected end of request body");
            }
            output.write(buffer, 0, read);
            remaining -= read;
        }
        output.flush();
    }

    private void publishToDownloads(File source, String requestedName) throws Exception {
        ContentResolver resolver = context.getContentResolver();
        String displayName = uniqueMediaName(resolver, requestedName);
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, displayName);
        values.put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream");
        values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/h4xtor-share");
        values.put(MediaStore.Downloads.IS_PENDING, 1);
        android.net.Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) {
            throw new IllegalStateException("Android could not create a Downloads entry");
        }
        boolean success = false;
        try (InputStream input = new BufferedInputStream(new java.io.FileInputStream(source));
             OutputStream output = new BufferedOutputStream(resolver.openOutputStream(uri, "w"))) {
            if (output == null) {
                throw new IllegalStateException("Android could not open the Downloads entry");
            }
            byte[] buffer = new byte[BUFFER_SIZE];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                output.write(buffer, 0, read);
            }
            output.flush();
            success = true;
        } finally {
            if (success) {
                ContentValues completed = new ContentValues();
                completed.put(MediaStore.Downloads.IS_PENDING, 0);
                resolver.update(uri, completed, null, null);
            } else {
                resolver.delete(uri, null, null);
            }
        }
    }

    private static String uniqueMediaName(ContentResolver resolver, String requestedName) {
        String base = requestedName;
        String extension = "";
        int dot = requestedName.lastIndexOf('.');
        if (dot > 0) {
            base = requestedName.substring(0, dot);
            extension = requestedName.substring(dot);
        }
        for (int index = 0; index < 10_000; index++) {
            String candidate = index == 0 ? requestedName : base + " (" + index + ")" + extension;
            try (Cursor cursor = resolver.query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{MediaStore.Downloads._ID},
                    MediaStore.Downloads.DISPLAY_NAME + "=? AND " + MediaStore.Downloads.RELATIVE_PATH + "=?",
                    new String[]{candidate, Environment.DIRECTORY_DOWNLOADS + "/h4xtor-share/"},
                    null)) {
                if (cursor == null || !cursor.moveToFirst()) {
                    return candidate;
                }
            } catch (Exception ignored) {
                return candidate;
            }
        }
        return base + "-" + System.currentTimeMillis() + extension;
    }

    private File incomingDirectory() {
        File root = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (root == null) {
            root = context.getFilesDir();
        }
        return new File(root, "h4xtor-share");
    }

    static String safeFileName(String raw) {
        String normalized = raw == null ? "" : raw.replace('\\', '/').trim();
        int slash = normalized.lastIndexOf('/');
        String name = slash >= 0 ? normalized.substring(slash + 1) : normalized;
        StringBuilder builder = new StringBuilder();
        String invalid = "<>:\"|?*";
        for (int index = 0; index < name.length(); index++) {
            char value = name.charAt(index);
            if (value >= 32 && invalid.indexOf(value) < 0) {
                builder.append(value);
            }
        }
        name = builder.toString().replaceAll("[ .]+$", "");
        if (name.isEmpty() || ".".equals(name) || "..".equals(name)) {
            throw new IllegalArgumentException("Invalid file name");
        }
        String stem = name.split("\\.", 2)[0].toUpperCase(Locale.ROOT);
        List<String> reserved = new ArrayList<>();
        reserved.add("CON"); reserved.add("PRN"); reserved.add("AUX"); reserved.add("NUL");
        for (int i = 1; i <= 9; i++) {
            reserved.add("COM" + i); reserved.add("LPT" + i);
        }
        if (reserved.contains(stem)) {
            name = "_" + name;
        }
        return name.length() > 240 ? name.substring(0, 240) : name;
    }

    private static String randomToken() {
        byte[] bytes = new byte[48];
        new SecureRandom().nextBytes(bytes);
        return android.util.Base64.encodeToString(
                bytes,
                android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
    }

    private static void sendJson(OutputStream output, int status, JSONObject body) throws Exception {
        send(output, status, "application/json; charset=utf-8", body.toString().getBytes(StandardCharsets.UTF_8), null);
    }

    private static void sendText(OutputStream output, int status, String text) throws Exception {
        sendText(output, status, text, null);
    }

    private static void sendText(OutputStream output, int status, String text, Map<String, String> extra)
            throws Exception {
        send(output, status, "text/plain; charset=utf-8", text.getBytes(StandardCharsets.UTF_8), extra);
    }

    private static void send(
            OutputStream output,
            int status,
            String contentType,
            byte[] body,
            Map<String, String> extra) throws Exception {
        String reason;
        switch (status) {
            case 200: reason = "OK"; break;
            case 400: reason = "Bad Request"; break;
            case 401: reason = "Unauthorized"; break;
            case 404: reason = "Not Found"; break;
            case 409: reason = "Conflict"; break;
            default: reason = "Error";
        }
        StringBuilder headers = new StringBuilder();
        headers.append("HTTP/1.1 ").append(status).append(' ').append(reason).append("\r\n");
        headers.append("Content-Type: ").append(contentType).append("\r\n");
        headers.append("Content-Length: ").append(body.length).append("\r\n");
        headers.append("Connection: close\r\n");
        if (extra != null) {
            for (Map.Entry<String, String> entry : extra.entrySet()) {
                headers.append(entry.getKey()).append(": ").append(entry.getValue()).append("\r\n");
            }
        }
        headers.append("\r\n");
        output.write(headers.toString().getBytes(StandardCharsets.US_ASCII));
        output.write(body);
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private static final class Request {
        final String method;
        final String path;
        final Map<String, String> headers;

        Request(String method, String path, Map<String, String> headers) {
            this.method = method;
            this.path = path;
            this.headers = headers;
        }
    }

    private static final class PendingPairing {
        final String peerId;
        final String peerName;
        final String code;
        final long expiresAt;

        PendingPairing(String peerId, String peerName, String code, long expiresAt) {
            this.peerId = peerId;
            this.peerName = peerName;
            this.code = code;
            this.expiresAt = expiresAt;
        }
    }

    private static final class Transfer {
        final String peerName;
        final String name;
        final long size;
        final File part;

        Transfer(String peerName, String name, long size, File part) {
            this.peerName = peerName;
            this.name = name;
            this.size = size;
            this.part = part;
        }
    }

    private static final class Auth {
        final String peerId;
        final String peerName;

        Auth(String peerId, String peerName) {
            this.peerId = peerId;
            this.peerName = peerName;
        }
    }

    private static final class SingleKeyManager implements X509KeyManager {
        private final PrivateKey privateKey;
        private final X509Certificate certificate;

        SingleKeyManager(PrivateKey privateKey, X509Certificate certificate) {
            this.privateKey = privateKey;
            this.certificate = certificate;
        }

        @Override public String[] getClientAliases(String keyType, Principal[] issuers) { return null; }
        @Override public String chooseClientAlias(String[] keyType, Principal[] issuers, Socket socket) { return null; }
        @Override public String[] getServerAliases(String keyType, Principal[] issuers) { return new String[]{"h4xtor"}; }
        @Override public String chooseServerAlias(String keyType, Principal[] issuers, Socket socket) { return "h4xtor"; }
        @Override public X509Certificate[] getCertificateChain(String alias) { return new X509Certificate[]{certificate}; }
        @Override public PrivateKey getPrivateKey(String alias) { return privateKey; }
    }
}
