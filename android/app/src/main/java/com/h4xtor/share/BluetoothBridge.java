package com.h4xtor.share;

import org.json.JSONObject;

import java.io.Closeable;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * One end of the h4xtor share Bluetooth multiplexer ("h4xtor-bt/1"), the same protocol as
 * {@code h4xtor_share/bluetooth.py} on the PC. Every connection made to
 * {@code 127.0.0.1:port()} becomes a stream over the link; streams the PC opens are connected
 * to this phone's own share server on 127.0.0.1. TLS, pinning and tokens stay as they are.
 *
 * <p>Frame: type (1 byte) | stream id (4 bytes, big endian) | length (4 bytes) | payload.
 * The phone numbers its streams even, the PC odd. Plain java.io, so JUnit can test it.
 */
final class BluetoothBridge implements Closeable {
    static final String MAGIC = "h4xtor-bt/1";
    static final int HELLO = 0, OPEN = 1, DATA = 2, CLOSE = 3;
    private static final int MAX_CHUNK = 32 * 1024;
    private static final int MAX_FRAME = 1024 * 1024;

    interface Listener {
        void onClosed(BluetoothBridge bridge);
    }

    private final InputStream in;
    private final OutputStream out;
    private final Closeable link;
    private final String deviceId;
    private final int localPort;
    private final Listener listener;
    private final ServerSocket server;
    private final Map<Integer, Socket> streams = new ConcurrentHashMap<>();
    private final AtomicInteger nextId;
    private final AtomicBoolean closed = new AtomicBoolean();
    private final CountDownLatch hello = new CountDownLatch(1);
    final AtomicInteger opened = new AtomicInteger();
    private volatile String remoteId = "";

    BluetoothBridge(InputStream in, OutputStream out, Closeable link, String deviceId, int localPort,
                    boolean odd, Listener listener) throws IOException {
        this.in = in;
        this.out = out;
        this.link = link;
        this.deviceId = deviceId;
        this.localPort = localPort;
        this.listener = listener;
        this.nextId = new AtomicInteger(odd ? 1 : 2);
        this.server = new ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"));
    }

    static byte[] encode(int kind, int stream, byte[] payload, int length) {
        ByteBuffer buffer = ByteBuffer.allocate(9 + length);
        buffer.put((byte) kind).putInt(stream).putInt(length);
        if (length > 0) {
            buffer.put(payload, 0, length);
        }
        return buffer.array();
    }

    /** Port that apps on this phone connect to for the PC on the other end. */
    int port() {
        return server.getLocalPort();
    }

    String remoteId() {
        return remoteId;
    }

    boolean isClosed() {
        return closed.get();
    }

    BluetoothBridge start() throws IOException {
        byte[] info;
        try {
            info = new JSONObject().put("magic", MAGIC).put("device_id", deviceId).toString()
                    .getBytes(StandardCharsets.UTF_8);
        } catch (Exception error) {
            throw new IOException(error);
        }
        send(HELLO, 0, info, info.length);
        thread(this::readLoop, "h4x-bt-read");
        thread(this::acceptLoop, "h4x-bt-accept");
        return this;
    }

    /** The other side's device id, or null when it never said hello in time. */
    String awaitHello(long timeoutMs) throws InterruptedException {
        if (!hello.await(timeoutMs, TimeUnit.MILLISECONDS) || remoteId.isEmpty()) {
            close();
            return null;
        }
        return remoteId;
    }

    @Override
    public void close() {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        quietly(link);
        quietly(server);
        List<Socket> all = new ArrayList<>(streams.values());
        streams.clear();
        for (Socket socket : all) {
            quietly(socket);
        }
        hello.countDown();
        if (listener != null) {
            listener.onClosed(this);
        }
    }

    // ------------------------------------------------------------------ link
    private void send(int kind, int stream, byte[] payload, int length) throws IOException {
        byte[] frame = encode(kind, stream, payload, length);
        synchronized (out) {
            out.write(frame);
            out.flush();
        }
    }

    private void readLoop() {
        try {
            DataInputStream data = new DataInputStream(in);
            while (!closed.get()) {
                int kind = data.readUnsignedByte();
                int stream = data.readInt();
                int length = data.readInt();
                if (length < 0 || length > MAX_FRAME) {
                    throw new IOException("Bad frame");
                }
                byte[] payload = new byte[length];
                data.readFully(payload);
                handle(kind, stream, payload);
            }
        } catch (Exception ignored) {
            // Link lost (out of range, Bluetooth off) or not an h4xtor share bridge.
        } finally {
            close();
        }
    }

    private void handle(int kind, int stream, byte[] payload) throws Exception {
        if (kind == HELLO) {
            JSONObject info = new JSONObject(new String(payload, StandardCharsets.UTF_8));
            if (!MAGIC.equals(info.optString("magic"))) {
                throw new IOException("Not an h4xtor share bridge");
            }
            String id = info.optString("device_id", "");
            remoteId = id.length() > 64 ? id.substring(0, 64) : id;
            hello.countDown();
        } else if (kind == OPEN) {
            Socket local = new Socket();
            try {
                local.connect(new InetSocketAddress("127.0.0.1", localPort), 5_000);
            } catch (IOException error) {
                quietly(local);
                send(CLOSE, stream, null, 0);
                return;
            }
            attach(stream, local);
        } else if (kind == DATA) {
            Socket local = streams.get(stream);
            if (local != null) {
                // ponytail: no per-stream flow control; a stalled local reader stalls the link.
                try {
                    local.getOutputStream().write(payload);
                } catch (IOException error) {
                    drop(stream, true);
                }
            }
        } else if (kind == CLOSE) {
            drop(stream, false);
        }
    }

    // --------------------------------------------------------------- streams
    private void acceptLoop() {
        while (!closed.get()) {
            Socket local;
            try {
                local = server.accept();
            } catch (IOException error) {
                return;
            }
            int stream = nextId.getAndAdd(2);
            try {
                send(OPEN, stream, null, 0);
            } catch (IOException error) {
                quietly(local);
                close();
                return;
            }
            attach(stream, local);
        }
    }

    private void attach(int stream, Socket local) {
        streams.put(stream, local);
        opened.incrementAndGet();
        thread(() -> pump(stream, local), "h4x-bt-stream");
    }

    private void pump(int stream, Socket local) {
        byte[] buffer = new byte[MAX_CHUNK];
        try {
            InputStream input = local.getInputStream();
            int count;
            while ((count = input.read(buffer)) > 0) {
                send(DATA, stream, buffer, count);
            }
        } catch (IOException ignored) {
            // Stream ended.
        }
        drop(stream, true);
    }

    private void drop(int stream, boolean tellRemote) {
        Socket local = streams.remove(stream);
        if (local == null) {
            return;
        }
        quietly(local);
        if (tellRemote && !closed.get()) {
            try {
                send(CLOSE, stream, null, 0);
            } catch (IOException ignored) {
                // The read loop notices the broken link and closes everything.
            }
        }
    }

    private static void thread(Runnable body, String name) {
        Thread thread = new Thread(body, name);
        thread.setDaemon(true);
        thread.start();
    }

    private static void quietly(Closeable closeable) {
        try {
            if (closeable instanceof Socket) {
                ((Socket) closeable).shutdownInput();
            }
        } catch (IOException ignored) {
            // Already closed.
        }
        try {
            closeable.close();
        } catch (IOException ignored) {
            // Already closed.
        }
    }
}
