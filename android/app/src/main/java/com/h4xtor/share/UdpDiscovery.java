package com.h4xtor.share;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * UDP broadcast discovery, wire-compatible with the desktop app
 * ({@code h4xtor_share/udp.py}). Works where mDNS multicast is filtered and on
 * Wi-Fi Direct groups, which never carry mDNS.
 */
public final class UdpDiscovery {
    public interface Listener {
        void onAnnouncement(Peer peer);
    }

    public interface Targets {
        List<String> extraTargets();
    }

    private static final int INTERVAL_MS = 5_000;

    private final AppIdentity identity;
    private final Listener listener;
    private final Targets targets;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private DatagramSocket socket;
    private Thread listenThread;
    private Thread announceThread;

    public UdpDiscovery(AppIdentity identity, Listener listener, Targets targets) {
        this.identity = identity;
        this.listener = listener;
        this.targets = targets;
    }

    public synchronized void start() {
        if (running.get()) {
            return;
        }
        try {
            DatagramSocket created = new DatagramSocket(null);
            created.setReuseAddress(true);
            created.setBroadcast(true);
            created.bind(new InetSocketAddress(AppIdentity.PORT));
            socket = created;
        } catch (Exception error) {
            socket = null;
            return;
        }
        running.set(true);
        listenThread = new Thread(this::listenLoop, "h4xtor-udp-listen");
        listenThread.setDaemon(true);
        listenThread.start();
        announceThread = new Thread(this::announceLoop, "h4xtor-udp-announce");
        announceThread.setDaemon(true);
        announceThread.start();
    }

    public synchronized void stop() {
        running.set(false);
        if (socket != null) {
            socket.close();
        }
        socket = null;
        if (announceThread != null) {
            announceThread.interrupt();
        }
        listenThread = null;
        announceThread = null;
    }

    /** Announce immediately, e.g. right after a Wi-Fi Direct group came up. */
    public void announceNow() {
        Thread thread = new Thread(this::announceOnce, "h4xtor-udp-now");
        thread.setDaemon(true);
        thread.start();
    }

    private void listenLoop() {
        byte[] buffer = new byte[4096];
        while (running.get()) {
            DatagramSocket current = socket;
            if (current == null) {
                return;
            }
            try {
                DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                current.receive(packet);
                String text = new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8);
                JSONObject payload = new JSONObject(text);
                if (payload.optInt("protocol", 0) != 1) {
                    continue;
                }
                String deviceId = payload.optString("device_id", "");
                if (deviceId.isEmpty() || deviceId.equals(identity.deviceId())) {
                    continue;
                }
                String address = H4xtorServer.remoteAddress(packet.getAddress());
                listener.onAnnouncement(new Peer(
                        deviceId,
                        payload.optString("name", "Enhed"),
                        address,
                        payload.optInt("port", AppIdentity.PORT),
                        payload.optString("fingerprint", ""),
                        payload.optString("platform", "unknown"),
                        address.startsWith("192.168.49.") ? "wifi-direct" : "lan",
                        Peer.capabilities(payload.optJSONArray("capabilities"))));
            } catch (Exception ignored) {
                // Unrelated broadcast traffic or a closed socket.
            }
        }
    }

    private void announceLoop() {
        while (running.get()) {
            announceOnce();
            try {
                Thread.sleep(INTERVAL_MS);
            } catch (InterruptedException error) {
                return;
            }
        }
    }

    private void announceOnce() {
        DatagramSocket current = socket;
        if (current == null) {
            return;
        }
        byte[] datagram;
        try {
            JSONArray capabilities = new JSONArray();
            for (String capability : AppIdentity.CAPABILITIES) {
                capabilities.put(capability);
            }
            datagram = new JSONObject()
                    .put("protocol", 1)
                    .put("device_id", identity.deviceId())
                    .put("name", identity.deviceName())
                    .put("platform", "android")
                    .put("port", AppIdentity.PORT)
                    .put("fingerprint", identity.fingerprint())
                    .put("capabilities", capabilities)
                    .toString()
                    .getBytes(StandardCharsets.UTF_8);
        } catch (Exception error) {
            return;
        }
        Set<String> destinations = new LinkedHashSet<>();
        destinations.add("255.255.255.255");
        destinations.addAll(broadcastAddresses());
        if (targets != null) {
            destinations.addAll(targets.extraTargets());
        }
        for (String destination : destinations) {
            try {
                current.send(new DatagramPacket(datagram, datagram.length,
                        InetAddress.getByName(destination), AppIdentity.PORT));
            } catch (Exception ignored) {
                // Interface went away or broadcast not permitted.
            }
        }
    }

    static Set<String> broadcastAddresses() {
        Set<String> result = new LinkedHashSet<>();
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            if (interfaces == null) {
                return result;
            }
            for (NetworkInterface networkInterface : Collections.list(interfaces)) {
                if (!networkInterface.isUp() || networkInterface.isLoopback()) {
                    continue;
                }
                for (InterfaceAddress address : networkInterface.getInterfaceAddresses()) {
                    InetAddress broadcast = address.getBroadcast();
                    if (broadcast != null) {
                        result.add(broadcast.getHostAddress());
                    }
                }
            }
        } catch (Exception ignored) {
            // No interfaces.
        }
        return result;
    }
}
