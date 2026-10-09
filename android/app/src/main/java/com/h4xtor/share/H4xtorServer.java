package com.h4xtor.share;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.MimeTypeMap;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.Principal;
import java.security.PrivateKey;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
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

/** TLS server speaking the h4xtor-share protocol (same API as the desktop app). */
public final class H4xtorServer {
    public interface Listener {
        void onPairingCode(String peerName, String code, long expiresAt);
        void onPeerPaired(Peer peer);
        void onPeerForgotten(String peerId, String peerName);
        void onClipboardReceived(String peerId, String peerName, String text);
        void onLinkReceived(String peerId, String peerName, String url);
        void onReceiveProgress(String transferId, String name, String peerName, long received, long total);
        void onFileReceived(String transferId, String peerName, String fileName, String uri, long size);
        void onFolderReceived(String transferId, String peerName, String folderName, int files, long size);
        void onStatus(String text);
    }

    private static final long PAIRING_TTL_MS = 120_000L;
    private static final long QR_TTL_MS = 300_000L;
    private static final int JSON_BODY_LIMIT = 4 * 1024 * 1024;
    private static final int BUFFER_SIZE = 1024 * 1024;
    private static final int MAX_FOLDER_ENTRIES = 10_000;
    private static final long PROGRESS_INTERVAL_MS = 200L;
    static final String INCOMING_RELATIVE = "Download/h4xtor-share";

    private final Context context;
    private final AppIdentity identity;
    private final Listener listener;
    private final Map<String, PendingPairing> pairings = new ConcurrentHashMap<>();
    private final Map<String, Long> qrSecrets = new ConcurrentHashMap<>();
    private final Map<String, Transfer> transfers = new ConcurrentHashMap<>();
    private final Map<String, FolderState> folders = new ConcurrentHashMap<>();
    private final ExecutorService clients = Executors.newCachedThreadPool();
    private final AtomicBoolean running = new AtomicBoolean(false);

    /** Last request from a PC on this phone's Wi-Fi Direct group (elapsedRealtime). */
    volatile long lastWifiDirectRequestAt;
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
        serverSocket = (SSLServerSocket) factory.createServerSocket();
        serverSocket.setReuseAddress(true);
        serverSocket.bind(new java.net.InetSocketAddress(AppIdentity.PORT), 64);
        running.set(true);
        acceptThread = new Thread(this::acceptLoop, "h4xtor-server");
        acceptThread.setDaemon(true);
        acceptThread.start();
    }

    public synchronized void stop() {
        running.set(false);
        if (serverSocket != null) {
            try {
                serverSocket.close();
            } catch (Exception ignored) {
                // Closing is best-effort.
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

    public boolean isRunning() {
        return running.get();
    }

    /** One-time secret for the QR code this device shows. */
    public String createQrSecret() {
        long now = System.currentTimeMillis();
        Iterator<Map.Entry<String, Long>> iterator = qrSecrets.entrySet().iterator();
        while (iterator.hasNext()) {
            if (iterator.next().getValue() < now) {
                iterator.remove();
            }
        }
        byte[] bytes = new byte[18];
        new SecureRandom().nextBytes(bytes);
        String secret = android.util.Base64.encodeToString(
                bytes,
                android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
        qrSecrets.put(secret, now + QR_TTL_MS);
        return secret;
    }

    public void revokeQrSecret(String secret) {
        if (secret != null) {
            qrSecrets.remove(secret);
        }
    }

    public void rejectPairing(String code) {
        for (Map.Entry<String, PendingPairing> entry : pairings.entrySet()) {
            if (entry.getValue().code.equals(code)) {
                pairings.remove(entry.getKey());
            }
        }
    }

    private void acceptLoop() {
        while (running.get()) {
            try {
                Socket socket = serverSocket.accept();
                clients.execute(() -> handle(socket));
            } catch (Exception error) {
                if (running.get()) {
                    listener.onStatus("Serverfejl: " + safeMessage(error));
                }
            }
        }
    }

    private void handle(Socket rawSocket) {
        try (SSLSocket socket = (SSLSocket) rawSocket) {
            socket.setSoTimeout(60_000);
            socket.startHandshake();
            BufferedInputStream input = new BufferedInputStream(socket.getInputStream(), 256 * 1024);
            BufferedOutputStream output = new BufferedOutputStream(socket.getOutputStream());
            Request request = readRequest(input);
            request.remote = remoteAddress(socket.getInetAddress());
            if (request.remote.startsWith("192.168.49.")) {
                lastWifiDirectRequestAt = android.os.SystemClock.elapsedRealtime();
            }
            try {
                route(request, input, output);
            } catch (HttpError error) {
                sendText(output, error.status, error.getMessage());
            }
            output.flush();
        } catch (Exception ignored) {
            // Peers routinely disconnect during LAN scans; that is not a user-facing error.
        }
    }

    static String remoteAddress(InetAddress address) {
        if (address == null) {
            return "";
        }
        String value = address.getHostAddress();
        if (value == null) {
            return "";
        }
        if (value.startsWith("::ffff:")) {
            value = value.substring(7);
        }
        return value;
    }

    private JSONObject infoJson() throws Exception {
        JSONArray capabilities = new JSONArray();
        for (String capability : AppIdentity.CAPABILITIES) {
            capabilities.put(capability);
        }
        return new JSONObject()
                .put("protocol", 1)
                .put("device_id", identity.deviceId())
                .put("name", identity.deviceName())
                .put("platform", "android")
                .put("port", AppIdentity.PORT)
                .put("fingerprint", identity.fingerprint())
                .put("capabilities", capabilities)
                .put("version", AppIdentity.VERSION);
    }

    private void route(Request request, BufferedInputStream input, BufferedOutputStream output)
            throws Exception {
        String method = request.method;
        String path = request.path;
        if ("GET".equals(method) && "/api/v1/info".equals(path)) {
            sendJson(output, 200, infoJson());
            return;
        }
        if ("GET".equals(method) && "/api/v1/ping".equals(path)) {
            sendJson(output, 200, new JSONObject().put("pong", true).put("device_id", identity.deviceId()));
            return;
        }
        if ("POST".equals(method) && "/api/v1/pair/request".equals(path)) {
            JSONObject body = readJsonBody(request, input);
            String peerId = body.optString("device_id", "").trim();
            String peerName = clip(body.optString("name", "Ukendt enhed").trim(), 80);
            if (!peerId.matches("[a-f0-9]{32}")) {
                throw new HttpError(400, "Invalid device id.");
            }
            String pairingId = UUID.randomUUID().toString().replace("-", "");
            String code = String.format(Locale.ROOT, "%06d", new SecureRandom().nextInt(1_000_000));
            long expiresAt = System.currentTimeMillis() + PAIRING_TTL_MS;
            pairings.put(pairingId, new PendingPairing(peerId, peerName, code, expiresAt));
            listener.onPairingCode(peerName, code, expiresAt);
            sendJson(output, 200, new JSONObject().put("pairing_id", pairingId).put("expires_in", 120));
            return;
        }
        if ("POST".equals(method) && "/api/v1/pair/confirm".equals(path)) {
            JSONObject body = readJsonBody(request, input);
            PendingPairing pending = pairings.remove(body.optString("pairing_id", ""));
            if (pending == null || pending.expiresAt < System.currentTimeMillis()) {
                throw new HttpError(401, "Pairing request expired.");
            }
            if (!MessageDigest.isEqual(
                    pending.code.getBytes(StandardCharsets.US_ASCII),
                    body.optString("code", "").getBytes(StandardCharsets.US_ASCII))) {
                throw new HttpError(401, "Incorrect pairing code.");
            }
            sendJson(output, 200, completePairing(request, pending.peerId, pending.peerName,
                    body.optJSONObject("reverse")));
            return;
        }
        if ("POST".equals(method) && "/api/v1/pair/qr".equals(path)) {
            JSONObject body = readJsonBody(request, input);
            String secret = body.optString("secret", "");
            String peerId = body.optString("device_id", "").trim();
            String peerName = clip(body.optString("name", "Ukendt enhed").trim(), 80);
            if (!peerId.matches("[a-f0-9]{32}")) {
                throw new HttpError(400, "Invalid device id.");
            }
            String match = null;
            for (String known : qrSecrets.keySet()) {
                if (MessageDigest.isEqual(known.getBytes(StandardCharsets.US_ASCII),
                        secret.getBytes(StandardCharsets.US_ASCII))) {
                    match = known;
                }
            }
            Long expires = match == null ? null : qrSecrets.remove(match);
            if (expires == null || expires < System.currentTimeMillis()) {
                throw new HttpError(401, "QR code expired. Show a new code.");
            }
            JSONObject reverse = body.optJSONObject("reverse");
            if (reverse == null) {
                throw new HttpError(400, "QR pairing requires reverse credentials.");
            }
            sendJson(output, 200, completePairing(request, peerId, peerName, reverse));
            return;
        }

        Auth auth = authenticate(request);
        if (auth == null) {
            throw new HttpError(401, "Peer is not trusted.");
        }

        switch (method + " " + (path.startsWith("/api/v1/files/") && !path.endsWith("/init")
                ? "/api/v1/files/*"
                : path.startsWith("/api/v1/folders/") && "PUT".equals(method)
                ? "/api/v1/folders/*/*"
                : path)) {
            case "POST /api/v1/clipboard": {
                JSONObject body = readJsonBody(request, input);
                if (!body.has("text")) {
                    throw new HttpError(400, "Clipboard payload must contain text.");
                }
                String text = body.getString("text");
                listener.onClipboardReceived(auth.peerId, auth.peerName, text);
                sendJson(output, 200, new JSONObject().put("accepted", true).put("characters", text.length()));
                return;
            }
            case "POST /api/v1/link": {
                JSONObject body = readJsonBody(request, input);
                String url = body.optString("url", "").trim();
                if (!isSafeUrl(url)) {
                    throw new HttpError(400, "Only http(s) links can be pushed.");
                }
                listener.onLinkReceived(auth.peerId, auth.peerName, url);
                sendJson(output, 200, new JSONObject().put("accepted", true));
                return;
            }
            case "POST /api/v1/unpair": {
                readJsonBody(request, input);
                identity.forget(auth.peerId);
                listener.onPeerForgotten(auth.peerId, auth.peerName);
                sendJson(output, 200, new JSONObject().put("forgotten", true));
                return;
            }
            case "POST /api/v1/files/init":
                fileInit(request, input, output, auth);
                return;
            case "PUT /api/v1/files/*":
                fileUpload(request, input, output);
                return;
            case "POST /api/v1/folders/init":
                folderInit(request, input, output, auth);
                return;
            case "PUT /api/v1/folders/*/*":
                folderUpload(request, input, output);
                return;
            case "POST /api/v1/folders/complete":
                folderComplete(request, input, output);
                return;
            default:
                throw new HttpError(404, "Not found.");
        }
    }

    private JSONObject completePairing(Request request, String peerId, String peerName, JSONObject reverse)
            throws Exception {
        String token = randomToken();
        identity.trustInbound(peerId, token, peerName);
        boolean mutual = false;
        if (reverse != null) {
            Peer peer = acceptReverse(request, peerId, peerName, reverse);
            if (peer != null) {
                mutual = true;
                listener.onPeerPaired(peer);
            }
        }
        JSONArray capabilities = new JSONArray();
        for (String capability : AppIdentity.CAPABILITIES) {
            capabilities.put(capability);
        }
        return new JSONObject()
                .put("token", token)
                .put("device_id", identity.deviceId())
                .put("name", identity.deviceName())
                .put("fingerprint", identity.fingerprint())
                .put("platform", "android")
                .put("port", AppIdentity.PORT)
                .put("capabilities", capabilities)
                .put("mutual", mutual);
    }

    private Peer acceptReverse(Request request, String peerId, String peerName, JSONObject reverse) {
        String token = reverse.optString("token", "");
        String fingerprint = reverse.optString("fingerprint", "").toLowerCase(Locale.ROOT);
        int port = reverse.optInt("port", AppIdentity.PORT);
        if (token.length() < 16 || !fingerprint.matches("[a-f0-9]{64}") || port <= 0 || port >= 65536) {
            return null;
        }
        if (request.remote.isEmpty()) {
            return null;
        }
        Peer peer = new Peer(
                peerId,
                peerName,
                request.remote,
                port,
                fingerprint,
                clip(reverse.optString("platform", "unknown"), 32),
                "lan",
                Peer.capabilities(reverse.optJSONArray("capabilities")));
        identity.trustOutbound(peerId, token, fingerprint, peerName);
        identity.remember(peer);
        return peer;
    }

    // ------------------------------------------------------------------ files
    private void fileInit(Request request, InputStream input, OutputStream output, Auth auth)
            throws Exception {
        JSONObject body = readJsonBody(request, input);
        String transferId = body.optString("transfer_id", "");
        if (!transferId.matches("[a-f0-9]{32}")) {
            throw new HttpError(400, "Invalid transfer id.");
        }
        String fileName;
        long size;
        try {
            fileName = safeFileName(body.optString("name", ""));
            size = body.getLong("size");
        } catch (Exception error) {
            throw new HttpError(400, "Invalid file metadata.");
        }
        if (size < 0) {
            throw new HttpError(400, "Invalid file size.");
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
        sendJson(output, 200, new JSONObject().put("transfer_id", transferId).put("offset", offset));
    }

    private void fileUpload(Request request, InputStream input, OutputStream output) throws Exception {
        String transferId = request.path.substring("/api/v1/files/".length());
        Transfer transfer = transfers.get(transferId);
        if (transfer == null) {
            throw new HttpError(404, "Transfer was not initialized.");
        }
        long actualOffset = transfer.part.exists() ? transfer.part.length() : 0L;
        if (requestedOffset(request) != actualOffset) {
            Map<String, String> extra = new HashMap<>();
            extra.put("X-H4xtor-Offset", Long.toString(actualOffset));
            sendText(output, 409, Long.toString(actualOffset), extra);
            return;
        }
        final long[] lastEmit = {0L};
        try (FileOutputStream file = new FileOutputStream(transfer.part, true)) {
            actualOffset = copyRequestBody(request, input, file, actualOffset, transfer.size, done -> {
                long now = System.currentTimeMillis();
                if (now - lastEmit[0] >= PROGRESS_INTERVAL_MS) {
                    lastEmit[0] = now;
                    listener.onReceiveProgress(transferId, transfer.name, transfer.peerName, done, transfer.size);
                }
            });
        }
        boolean complete = actualOffset == transfer.size;
        if (complete) {
            listener.onReceiveProgress(transferId, transfer.name, transfer.peerName, transfer.size, transfer.size);
            Uri uri = publishToDownloads(transfer.part, transfer.name, INCOMING_RELATIVE);
            //noinspection ResultOfMethodCallIgnored
            transfer.part.delete();
            transfers.remove(transferId);
            listener.onFileReceived(transferId, transfer.peerName, transfer.name,
                    uri == null ? "" : uri.toString(), transfer.size);
        }
        sendJson(output, 200, new JSONObject()
                .put("transfer_id", transferId)
                .put("offset", actualOffset)
                .put("complete", complete));
    }

    // ---------------------------------------------------------------- folders
    private void folderInit(Request request, InputStream input, OutputStream output, Auth auth)
            throws Exception {
        JSONObject body = readJsonBody(request, input);
        String folderId = body.optString("folder_id", "");
        if (!folderId.matches("[a-f0-9]{32}")) {
            throw new HttpError(400, "Invalid folder id.");
        }
        String folderName;
        try {
            folderName = safeFileName(body.optString("name", ""));
        } catch (Exception error) {
            throw new HttpError(400, "Invalid folder name.");
        }
        JSONArray entries = body.optJSONArray("entries");
        if (entries == null || entries.length() == 0) {
            throw new HttpError(400, "Folder must contain at least one file.");
        }
        if (entries.length() > MAX_FOLDER_ENTRIES) {
            throw new HttpError(400, "Folder contains too many files.");
        }
        File staging = new File(incomingDirectory(), ".h4xtor-folder-" + folderId);
        //noinspection ResultOfMethodCallIgnored
        staging.mkdirs();
        FolderState state = new FolderState(auth.peerName, folderName, staging);
        JSONArray offsets = new JSONArray();
        for (int index = 0; index < entries.length(); index++) {
            JSONObject entry = entries.getJSONObject(index);
            String fileId = entry.optString("id", "");
            long size = entry.optLong("size", -1);
            String relative;
            try {
                relative = safeRelativePath(entry.optString("path", ""));
            } catch (Exception error) {
                throw new HttpError(400, "Invalid folder entry.");
            }
            if (!fileId.matches("[a-f0-9]{32}") || size < 0 || state.files.containsKey(fileId)) {
                throw new HttpError(400, "Invalid folder entry.");
            }
            File part = new File(staging, ".h4xtor-" + fileId + ".part");
            File done = new File(staging, "done-" + fileId);
            long offset = done.exists() ? size : part.exists() ? part.length() : 0L;
            if (offset > size) {
                //noinspection ResultOfMethodCallIgnored
                part.delete();
                offset = 0L;
            }
            state.files.put(fileId, new FolderEntry(relative, size, part));
            state.received.put(fileId, offset);
            if (done.exists()) {
                state.done.add(fileId);
            }
            state.total += size;
            offsets.put(new JSONObject().put("id", fileId).put("path", relative).put("offset", offset));
        }
        folders.put(folderId, state);
        sendJson(output, 200, new JSONObject()
                .put("folder_id", folderId)
                .put("name", folderName)
                .put("entries", offsets));
    }

    private void folderUpload(Request request, InputStream input, OutputStream output) throws Exception {
        String[] parts = request.path.substring("/api/v1/folders/".length()).split("/");
        if (parts.length != 2) {
            throw new HttpError(404, "Not found.");
        }
        String folderId = parts[0];
        String fileId = parts[1];
        FolderState folder = folders.get(folderId);
        if (folder == null) {
            throw new HttpError(404, "Folder was not initialized.");
        }
        if (folder.done.contains(fileId)) {
            throw new HttpError(409, "File already received.");
        }
        FolderEntry entry = folder.files.get(fileId);
        if (entry == null) {
            throw new HttpError(404, "Folder entry was not initialized.");
        }
        long actualOffset = entry.part.exists() ? entry.part.length() : 0L;
        if (requestedOffset(request) != actualOffset) {
            Map<String, String> extra = new HashMap<>();
            extra.put("X-H4xtor-Offset", Long.toString(actualOffset));
            sendText(output, 409, Long.toString(actualOffset), extra);
            return;
        }
        final long[] lastEmit = {0L};
        try (FileOutputStream file = new FileOutputStream(entry.part, true)) {
            actualOffset = copyRequestBody(request, input, file, actualOffset, entry.size, done -> {
                folder.received.put(fileId, done);
                long now = System.currentTimeMillis();
                if (now - lastEmit[0] >= PROGRESS_INTERVAL_MS) {
                    lastEmit[0] = now;
                    listener.onReceiveProgress(folderId, folder.name, folder.peerName,
                            folder.receivedTotal(), folder.total);
                }
            });
        }
        boolean complete = actualOffset == entry.size;
        if (complete) {
            folder.done.add(fileId);
            //noinspection ResultOfMethodCallIgnored
            new File(folder.staging, "done-" + fileId).createNewFile();
        }
        sendJson(output, 200, new JSONObject()
                .put("folder_id", folderId)
                .put("file_id", fileId)
                .put("offset", actualOffset)
                .put("complete", complete));
    }

    private void folderComplete(Request request, InputStream input, OutputStream output) throws Exception {
        JSONObject body = readJsonBody(request, input);
        String folderId = body.optString("folder_id", "");
        FolderState folder = folders.get(folderId);
        if (folder == null) {
            throw new HttpError(404, "Folder was not initialized.");
        }
        int missing = folder.files.size() - folder.done.size();
        if (missing > 0) {
            throw new HttpError(409, missing + " file(s) not received yet.");
        }
        String finalName = uniqueFolderName(folder.name);
        for (FolderEntry entry : folder.files.values()) {
            String relativeDir = INCOMING_RELATIVE + "/" + finalName;
            String fileName = entry.relative;
            int slash = entry.relative.lastIndexOf('/');
            if (slash >= 0) {
                relativeDir = relativeDir + "/" + entry.relative.substring(0, slash);
                fileName = entry.relative.substring(slash + 1);
            }
            publishToDownloads(entry.part, fileName, relativeDir);
        }
        deleteRecursively(folder.staging);
        folders.remove(folderId);
        listener.onReceiveProgress(folderId, folder.name, folder.peerName, folder.total, folder.total);
        listener.onFolderReceived(folderId, folder.peerName, finalName, folder.files.size(), folder.total);
        sendJson(output, 200, new JSONObject()
                .put("folder_id", folderId)
                .put("name", finalName)
                .put("path", INCOMING_RELATIVE + "/" + finalName));
    }

    private String uniqueFolderName(String requested) {
        ContentResolver resolver = context.getContentResolver();
        for (int index = 0; index < 1000; index++) {
            String candidate = index == 0 ? requested : requested + " (" + index + ")";
            try (Cursor cursor = resolver.query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{MediaStore.Downloads._ID},
                    MediaStore.Downloads.RELATIVE_PATH + " LIKE ?",
                    new String[]{INCOMING_RELATIVE + "/" + candidate + "/%"},
                    null)) {
                if (cursor == null || !cursor.moveToFirst()) {
                    return candidate;
                }
            } catch (Exception ignored) {
                return candidate;
            }
        }
        return requested + "-" + System.currentTimeMillis();
    }

    private static void deleteRecursively(File file) {
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) {
                deleteRecursively(child);
            }
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
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

    private static long requestedOffset(Request request) throws HttpError {
        try {
            return Long.parseLong(request.headers.getOrDefault("x-h4xtor-offset", "-1"));
        } catch (NumberFormatException error) {
            throw new HttpError(400, "Invalid transfer offset.");
        }
    }

    static boolean isSafeUrl(String url) {
        if (url == null || url.isEmpty() || url.length() > 8192) {
            return false;
        }
        for (int index = 0; index < url.length(); index++) {
            if (Character.isWhitespace(url.charAt(index))) {
                return false;
            }
        }
        String lower = url.toLowerCase(Locale.ROOT);
        return lower.startsWith("http://") || lower.startsWith("https://");
    }

    // ------------------------------------------------------------------- http
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
            headers.put(line.substring(0, colon).trim().toLowerCase(Locale.ROOT), line.substring(colon + 1).trim());
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
        if (length < 0 && request.headers.getOrDefault("transfer-encoding", "").contains("chunked")) {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            copyRequestBody(request, input, buffer, 0L, JSON_BODY_LIMIT, null);
            String text = buffer.toString(StandardCharsets.UTF_8.name());
            return text.trim().isEmpty() ? new JSONObject() : new JSONObject(text);
        }
        if (length < 0 || length > JSON_BODY_LIMIT) {
            throw new HttpError(400, "Invalid JSON body length");
        }
        byte[] data = readExact(input, (int) length);
        String text = new String(data, StandardCharsets.UTF_8);
        return text.trim().isEmpty() ? new JSONObject() : new JSONObject(text);
    }

    interface ProgressSink {
        void onProgress(long done);
    }

    private static long copyRequestBody(
            Request request,
            InputStream input,
            OutputStream output,
            long currentOffset,
            long totalSize,
            ProgressSink sink) throws Exception {
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
                offset = copyExact(input, output, chunkSize, offset, sink);
                String afterChunk = readLine(input, 2);
                if (afterChunk == null || !afterChunk.isEmpty()) {
                    throw new IllegalArgumentException("Malformed chunked request");
                }
            }
            output.flush();
            return offset;
        }
        long length = contentLength(request);
        if (length < 0) {
            throw new IllegalArgumentException("Missing request body length");
        }
        if (currentOffset + length > totalSize) {
            throw new IllegalArgumentException("Received more bytes than declared");
        }
        long result = copyExact(input, output, length, currentOffset, sink);
        output.flush();
        return result;
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

    private static long copyExact(InputStream input, OutputStream output, long length, long offset,
                                  ProgressSink sink) throws Exception {
        byte[] buffer = new byte[(int) Math.min(BUFFER_SIZE, Math.max(1, length))];
        long remaining = length;
        long position = offset;
        while (remaining > 0) {
            int read = input.read(buffer, 0, (int) Math.min(buffer.length, remaining));
            if (read < 0) {
                throw new IllegalStateException("Unexpected end of request body");
            }
            output.write(buffer, 0, read);
            remaining -= read;
            position += read;
            if (sink != null) {
                sink.onProgress(position);
            }
        }
        return position;
    }

    // ---------------------------------------------------------------- storage
    static String mimeFor(String fileName) {
        String lower = fileName.toLowerCase(Locale.ROOT);
        int dot = lower.lastIndexOf('.');
        if (dot < 0 || dot == lower.length() - 1) {
            return "application/octet-stream";
        }
        String extension = lower.substring(dot + 1);
        if ("apk".equals(extension)) {
            return "application/vnd.android.package-archive";
        }
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
        return mime == null ? "application/octet-stream" : mime;
    }

    private Uri publishToDownloads(File source, String requestedName, String relativePath) throws Exception {
        ContentResolver resolver = context.getContentResolver();
        String displayName = uniqueMediaName(resolver, requestedName, relativePath);
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, displayName);
        values.put(MediaStore.Downloads.MIME_TYPE, mimeFor(requestedName));
        values.put(MediaStore.Downloads.RELATIVE_PATH, relativePath);
        values.put(MediaStore.Downloads.IS_PENDING, 1);
        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) {
            throw new IllegalStateException("Android could not create a Downloads entry");
        }
        boolean success = false;
        try (InputStream input = new BufferedInputStream(new FileInputStream(source), BUFFER_SIZE);
             OutputStream raw = resolver.openOutputStream(uri, "w")) {
            if (raw == null) {
                throw new IllegalStateException("Android could not open the Downloads entry");
            }
            try (OutputStream output = new BufferedOutputStream(raw, BUFFER_SIZE)) {
                byte[] buffer = new byte[BUFFER_SIZE];
                int read;
                while ((read = input.read(buffer)) >= 0) {
                    output.write(buffer, 0, read);
                }
                output.flush();
            }
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
        return uri;
    }

    private static String uniqueMediaName(ContentResolver resolver, String requestedName, String relativePath) {
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
                    new String[]{candidate, relativePath + "/"},
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
        reserved.add("CON");
        reserved.add("PRN");
        reserved.add("AUX");
        reserved.add("NUL");
        for (int i = 1; i <= 9; i++) {
            reserved.add("COM" + i);
            reserved.add("LPT" + i);
        }
        if (reserved.contains(stem)) {
            name = "_" + name;
        }
        return name.length() > 240 ? name.substring(0, 240) : name;
    }

    static String safeRelativePath(String raw) {
        String normalized = raw == null ? "" : raw.trim().replace('\\', '/');
        while (normalized.startsWith("/")) {
            normalized = normalized.substring(1);
        }
        List<String> segments = new ArrayList<>();
        for (String part : normalized.split("/")) {
            if (part.isEmpty() || ".".equals(part)) {
                continue;
            }
            String safe = safeFileName(part);
            if ("..".equals(safe) || ".".equals(safe)) {
                throw new IllegalArgumentException("Invalid relative path");
            }
            segments.add(safe);
        }
        if (segments.isEmpty() || segments.size() > 64) {
            throw new IllegalArgumentException("Invalid relative path");
        }
        return String.join("/", segments);
    }

    private static String clip(String value, int max) {
        return value.length() > max ? value.substring(0, max) : value;
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

    private static void send(OutputStream output, int status, String contentType, byte[] body,
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

    static final class HttpError extends Exception {
        final int status;

        HttpError(int status, String message) {
            super(message);
            this.status = status;
        }
    }

    private static final class Request {
        final String method;
        final String path;
        final Map<String, String> headers;
        String remote = "";

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

    private static final class FolderEntry {
        final String relative;
        final long size;
        final File part;

        FolderEntry(String relative, long size, File part) {
            this.relative = relative;
            this.size = size;
            this.part = part;
        }
    }

    private static final class FolderState {
        final String peerName;
        final String name;
        final File staging;
        final Map<String, FolderEntry> files = new LinkedHashMap<>();
        final Map<String, Long> received = new ConcurrentHashMap<>();
        final Set<String> done = java.util.Collections.synchronizedSet(new HashSet<>());
        long total;

        FolderState(String peerName, String name, File staging) {
            this.peerName = peerName;
            this.name = name;
            this.staging = staging;
        }

        long receivedTotal() {
            long sum = 0L;
            for (Long value : received.values()) {
                sum += value;
            }
            return sum;
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
        private boolean matches(String keyType) {
            String algorithm = privateKey.getAlgorithm();
            return keyType == null || algorithm == null
                    || keyType.toUpperCase(Locale.ROOT).startsWith(algorithm.toUpperCase(Locale.ROOT))
                    || ("EC".equalsIgnoreCase(algorithm) && keyType.toUpperCase(Locale.ROOT).contains("EC"));
        }

        @Override
        public String[] getServerAliases(String keyType, Principal[] issuers) {
            return matches(keyType) ? new String[]{"h4xtor"} : null;
        }

        @Override
        public String chooseServerAlias(String keyType, Principal[] issuers, Socket socket) {
            return matches(keyType) ? "h4xtor" : null;
        }
        @Override public X509Certificate[] getCertificateChain(String alias) { return new X509Certificate[]{certificate}; }
        @Override public PrivateKey getPrivateKey(String alias) { return privateKey; }
    }
}
