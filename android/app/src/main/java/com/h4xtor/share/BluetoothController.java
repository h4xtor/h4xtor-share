package com.h4xtor.share;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothServerSocket;
import android.bluetooth.BluetoothSocket;
import android.content.Context;

import java.io.Closeable;
import java.io.File;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * Waits for a paired PC on Bluetooth (RFCOMM, service {@link #SERVICE_UUID}) and runs a
 * {@link BluetoothBridge} for it. Only one PC at a time; a new connection replaces the old.
 *
 * <p>For the emulator test, which has no Bluetooth, the same bridge can also be reached on
 * 127.0.0.1:&lt;port&gt; when the private file {@code files/bt_debug_port} holds that port
 * (only adb run-as can create it).
 */
final class BluetoothController {
    static final UUID SERVICE_UUID = UUID.fromString("6f3b2a10-5c1e-4d8a-9f47-4834786f7231");

    interface Listener {
        void onBridgeUp(BluetoothBridge bridge, String pcId);

        void onBridgeDown(BluetoothBridge bridge);
    }

    private final Context context;
    private final AppIdentity identity;
    private final Listener listener;
    private volatile boolean running;
    private volatile int generation; // a stopped-and-restarted controller ends the old loop
    private volatile Closeable acceptor;
    private volatile ServerSocket debugAcceptor;
    private volatile BluetoothBridge current;

    BluetoothController(Context context, AppIdentity identity, Listener listener) {
        this.context = context.getApplicationContext();
        this.identity = identity;
        this.listener = listener;
    }

    boolean isRunning() {
        return running;
    }

    BluetoothBridge current() {
        BluetoothBridge bridge = current;
        return bridge == null || bridge.isClosed() ? null : bridge;
    }

    /** Null when Bluetooth can be used, otherwise a Danish reason. Caller holds BLUETOOTH_CONNECT. */
    @SuppressLint("MissingPermission")
    String start() {
        if (running) {
            return null;
        }
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        running = true;
        startDebugListener();
        if (adapter == null) {
            if (debugAcceptor == null) {
                running = false; // nothing to wait for; a later start() may try again
                return "Telefonen har ikke Bluetooth.";
            }
            return null;
        }
        // The loop retries every few seconds, so it also starts once Bluetooth is switched on.
        int mine = ++generation;
        thread(() -> acceptLoop(adapter, mine), "h4x-bt-listen");
        return adapter.isEnabled() || debugAcceptor != null ? null
                : "Slå Bluetooth til på telefonen – forbindelsen starter af sig selv bagefter.";
    }

    void stop() {
        running = false;
        quietly(acceptor);
        quietly(debugAcceptor);
        BluetoothBridge bridge = current;
        if (bridge != null) {
            bridge.close();
        }
    }

    @SuppressLint("MissingPermission")
    private void acceptLoop(BluetoothAdapter adapter, int mine) {
        while (running && mine == generation) {
            try {
                // Secure RFCOMM: only devices paired with this phone can connect.
                BluetoothServerSocket server =
                        adapter.listenUsingRfcommWithServiceRecord("h4xtor share", SERVICE_UUID);
                acceptor = server;
                BluetoothSocket socket = server.accept();
                quietly(server);
                serve(socket.getInputStream(), socket.getOutputStream(), socket);
            } catch (Exception error) {
                if (!running || mine != generation) {
                    return;
                }
                sleep(3_000); // Bluetooth is off (or was switched off); try again.
            }
        }
    }

    private void startDebugListener() {
        File file = new File(context.getFilesDir(), "bt_debug_port");
        if (!file.isFile()) {
            return;
        }
        try {
            String text = new String(java.nio.file.Files.readAllBytes(file.toPath()), StandardCharsets.US_ASCII);
            int port = Integer.parseInt(text.trim());
            ServerSocket server = new ServerSocket(port, 2, InetAddress.getByName("127.0.0.1"));
            debugAcceptor = server;
            thread(() -> {
                while (running) {
                    try {
                        Socket socket = server.accept();
                        serve(socket.getInputStream(), socket.getOutputStream(), socket);
                    } catch (Exception error) {
                        return;
                    }
                }
            }, "h4x-bt-debug");
        } catch (Exception ignored) {
            // No test port.
        }
    }

    private void serve(java.io.InputStream in, java.io.OutputStream out, Closeable link) throws Exception {
        BluetoothBridge old = current;
        if (old != null) {
            old.close();
        }
        BluetoothBridge bridge = new BluetoothBridge(in, out, link, identity.deviceId(), AppIdentity.PORT,
                false, listener::onBridgeDown).start();
        current = bridge;
        thread(() -> {
            try {
                String pcId = bridge.awaitHello(10_000);
                if (pcId != null && identity.isOutboundTrusted(pcId)) {
                    listener.onBridgeUp(bridge, pcId);
                } else {
                    bridge.close(); // not a PC this phone is paired with in h4xtor share
                }
            } catch (InterruptedException error) {
                bridge.close();
            }
        }, "h4x-bt-hello");
    }

    private static void thread(Runnable body, String name) {
        Thread thread = new Thread(body, name);
        thread.setDaemon(true);
        thread.start();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    private static void quietly(Closeable closeable) {
        if (closeable == null) {
            return;
        }
        try {
            closeable.close();
        } catch (Exception ignored) {
            // Already closed.
        }
    }
}
