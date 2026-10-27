package com.h4xtor.share;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;

import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Wi-Fi + 5G: a paired PC on the same Wi-Fi sends "CONNECT host:port" to this phone's
 * h4xtor share server (pinned TLS + pairing token), and the connection goes out over the
 * phone's mobile data. The PC spreads its connections between its own Wi-Fi and phones.
 */
final class NetGateway {
    private static final int CONNECT_TIMEOUT_MS = 10_000;

    private final ConnectivityManager connectivity;
    private final ExecutorService pumps = Executors.newCachedThreadPool();
    private final AtomicLong sharedBytes = new AtomicLong();
    private final AtomicLong active = new AtomicLong();
    private volatile Network cellular;
    private ConnectivityManager.NetworkCallback callback;

    NetGateway(Context context) {
        connectivity = context.getSystemService(ConnectivityManager.class);
    }

    /** Keeps mobile data up next to Wi-Fi while sharing is on (Android drops it otherwise). */
    synchronized void setEnabled(boolean enabled) {
        if (enabled && callback == null) {
            NetworkRequest request = new NetworkRequest.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    .build();
            callback = new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    cellular = network;
                }

                @Override
                public void onLost(Network network) {
                    if (network.equals(cellular)) {
                        cellular = null;
                    }
                }
            };
            connectivity.requestNetwork(request, callback);
        } else if (!enabled && callback != null) {
            try {
                connectivity.unregisterNetworkCallback(callback);
            } catch (IllegalArgumentException ignored) {
                // Already gone.
            }
            callback = null;
            cellular = null;
        }
    }

    boolean ready() {
        return cellular != null;
    }

    long sharedBytes() {
        return sharedBytes.get();
    }

    long activeTunnels() {
        return active.get();
    }

    JSONObject status(boolean enabled) throws Exception {
        return new JSONObject()
                .put("enabled", enabled && ready())
                .put("switched_on", enabled)
                .put("network", "mobildata")
                .put("shared_bytes", sharedBytes.get())
                .put("active", active.get());
    }

    /** Tunnels one connection until either side closes. */
    void tunnel(String target, Socket client, InputStream in, OutputStream out) throws Exception {
        Network network = cellular;
        if (network == null) {
            throw new H4xtorServer.HttpError(503, "Mobildata er ikke klar på telefonen.");
        }
        String[] hostPort = parseTarget(target);
        if (hostPort == null) {
            throw new H4xtorServer.HttpError(400, "Ugyldig adresse.");
        }
        int port = Integer.parseInt(hostPort[1]);
        Socket upstream = network.getSocketFactory().createSocket();
        try {
            InetAddress[] addresses;
            try {
                addresses = network.getAllByName(hostPort[0]);
            } catch (IOException error) {
                throw new H4xtorServer.HttpError(502, "Ukendt adresse: " + hostPort[0]);
            }
            IOException last = null;
            for (InetAddress address : addresses) {
                try {
                    upstream.connect(new InetSocketAddress(address, port), CONNECT_TIMEOUT_MS);
                    last = null;
                    break;
                } catch (IOException error) {
                    last = error;
                    upstream.close();
                    upstream = network.getSocketFactory().createSocket();
                }
            }
            if (last != null || !upstream.isConnected()) {
                throw new H4xtorServer.HttpError(502, "Kunne ikke forbinde over mobildata.");
            }
            out.write("HTTP/1.1 200 Connection established\r\n\r\n".getBytes(StandardCharsets.US_ASCII));
            out.flush();
            client.setSoTimeout(0);
            active.incrementAndGet();
            Socket remote = upstream;
            Future<?> upload = pumps.submit(() -> {
                pump(in, remote.getOutputStream());
                try {
                    remote.shutdownOutput();
                } catch (IOException ignored) {
                    // Closed meanwhile.
                }
                return null;
            });
            try {
                pump(remote.getInputStream(), out);
            } finally {
                upload.cancel(true);
                active.decrementAndGet();
            }
        } finally {
            upstream.close();
        }
    }

    /** Copies until EOF; both directions count as mobile data used. */
    private void pump(InputStream source, OutputStream sink) {
        byte[] buffer = new byte[64 * 1024];
        try {
            int read;
            while ((read = source.read(buffer)) >= 0) {
                sink.write(buffer, 0, read);
                sink.flush();
                sharedBytes.addAndGet(read);
            }
        } catch (IOException ignored) {
            // Either side hung up: the tunnel is over.
        }
    }

    /** "host:port" or "[v6]:port" → {host, port}; null when malformed. */
    static String[] parseTarget(String target) {
        if (target == null) {
            return null;
        }
        String host;
        String port;
        if (target.startsWith("[")) {
            int end = target.indexOf("]:");
            if (end < 0) {
                return null;
            }
            host = target.substring(1, end);
            port = target.substring(end + 2);
        } else {
            int colon = target.lastIndexOf(':');
            if (colon <= 0 || target.indexOf(':') != colon) {
                return null;
            }
            host = target.substring(0, colon);
            port = target.substring(colon + 1);
        }
        try {
            int value = Integer.parseInt(port);
            if (host.isEmpty() || value <= 0 || value > 65535) {
                return null;
            }
        } catch (NumberFormatException error) {
            return null;
        }
        return new String[]{host, port};
    }
}
