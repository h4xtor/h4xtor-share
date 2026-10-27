package com.h4xtor.share;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.RouteInfo;
import android.net.wifi.WifiNetworkSpecifier;
import android.os.Build;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.util.ArrayList;
import java.util.List;

/**
 * Joins a Wi-Fi Direct network that a PC created (h4xtor share on Windows/Linux).
 * Android shows its own "Forbind til enhed" box; the user taps Forbind once. The
 * network is local only, so the phone keeps its mobile data for the internet,
 * and the app routes its own traffic through it while it is joined.
 */
public final class WifiJoinController {
    public interface Listener {
        /** Joined; {@code gateways} are the PC's likely addresses on the new network. */
        void onJoined(String ssid, List<String> gateways);
        void onJoinFailed(String reason);
        void onLeft(String ssid);
    }

    private static final int TIMEOUT_MS = 60_000;

    private final ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback callback;
    private volatile Network network;
    private volatile String ssid = "";
    private volatile boolean connecting;

    public WifiJoinController(Context context) {
        connectivity = (ConnectivityManager) context.getApplicationContext()
                .getSystemService(Context.CONNECTIVITY_SERVICE);
    }

    public boolean isJoined() {
        return network != null;
    }

    public boolean isConnecting() {
        return connecting;
    }

    public String ssid() {
        return ssid;
    }

    /** Must be called while the app is on screen: Android only shows the box for the foreground app. */
    public synchronized void join(String networkName, String passphrase, Listener listener) {
        leaveQuietly();
        if (connectivity == null) {
            listener.onJoinFailed("Telefonen kan ikke styre Wi-Fi lige nu.");
            return;
        }
        WifiNetworkSpecifier specifier;
        try {
            specifier = new WifiNetworkSpecifier.Builder()
                    .setSsid(networkName)
                    .setWpa2Passphrase(passphrase)
                    .build();
        } catch (IllegalArgumentException error) {
            listener.onJoinFailed("Netværksnavn eller kode er ikke gyldig.");
            return;
        }
        NetworkRequest request = new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .setNetworkSpecifier(specifier)
                .build();
        ssid = networkName;
        connecting = true;
        ConnectivityManager.NetworkCallback current = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network available) {
                synchronized (WifiJoinController.this) {
                    if (callback != this) {
                        return;
                    }
                    network = available;
                    connecting = false;
                    connectivity.bindProcessToNetwork(available);
                }
                listener.onJoined(networkName, gateways(connectivity.getLinkProperties(available)));
            }

            @Override
            public void onUnavailable() {
                synchronized (WifiJoinController.this) {
                    if (callback != this) {
                        return;
                    }
                    callback = null;
                    connecting = false;
                }
                listener.onJoinFailed("Fandt ikke " + networkName + ". Tjek at netværket kører på PC'en, "
                        + "og tryk Forbind i Android-boksen.");
            }

            @Override
            public void onLost(Network lost) {
                boolean ours;
                synchronized (WifiJoinController.this) {
                    ours = callback == this && lost.equals(network);
                    if (ours) {
                        network = null;
                        connectivity.bindProcessToNetwork(null);
                    }
                }
                if (ours) {
                    listener.onLeft(networkName);
                }
            }
        };
        callback = current;
        try {
            connectivity.requestNetwork(request, current, TIMEOUT_MS);
        } catch (RuntimeException error) {
            callback = null;
            connecting = false;
            listener.onJoinFailed("Android afviste forbindelsen: " + error.getMessage());
        }
    }

    /** Give the network back: the phone returns to its normal Wi-Fi by itself. */
    public synchronized String leave() {
        String left = network != null ? ssid : "";
        leaveQuietly();
        return left;
    }

    private void leaveQuietly() {
        if (callback != null && connectivity != null) {
            try {
                connectivity.unregisterNetworkCallback(callback);
            } catch (RuntimeException ignored) {
                // Already released.
            }
        }
        callback = null;
        connecting = false;
        if (network != null && connectivity != null) {
            connectivity.bindProcessToNetwork(null);
        }
        network = null;
    }

    /** The router of the new network is the PC itself: its address comes first. */
    static List<String> gateways(LinkProperties properties) {
        List<String> out = new ArrayList<>();
        if (properties == null) {
            return out;
        }
        if (Build.VERSION.SDK_INT >= 30) {
            Inet4Address dhcp = properties.getDhcpServerAddress();
            if (dhcp != null) {
                add(out, dhcp);
            }
        }
        for (RouteInfo route : properties.getRoutes()) {
            if (route.hasGateway()) {
                add(out, route.getGateway());
            }
        }
        return out;
    }

    private static void add(List<String> out, InetAddress address) {
        if (address instanceof Inet4Address && !address.isAnyLocalAddress()) {
            String text = address.getHostAddress();
            if (text != null && !out.contains(text)) {
                out.add(text);
            }
        }
    }
}
