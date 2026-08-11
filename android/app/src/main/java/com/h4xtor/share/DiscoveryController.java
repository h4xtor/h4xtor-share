package com.h4xtor.share;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;

public final class DiscoveryController {
    public interface Listener {
        void onPeerAddress(String address, int port);
        void onStatus(String text);
    }

    private static final String SERVICE_TYPE = "_h4xtor-share._tcp.";

    private final Context context;
    private final AppIdentity identity;
    private final Listener listener;
    private final NsdManager nsdManager;
    private NsdManager.DiscoveryListener discoveryListener;
    private NsdManager.RegistrationListener registrationListener;
    private WifiManager.MulticastLock multicastLock;

    public DiscoveryController(Context context, AppIdentity identity, Listener listener) {
        this.context = context.getApplicationContext();
        this.identity = identity;
        this.listener = listener;
        this.nsdManager = (NsdManager) context.getSystemService(Context.NSD_SERVICE);
    }

    public void start() {
        acquireMulticast();
        register();
        discover();
    }

    public void stop() {
        if (discoveryListener != null) {
            try {
                nsdManager.stopServiceDiscovery(discoveryListener);
            } catch (Exception ignored) {
                // Already stopped.
            }
            discoveryListener = null;
        }
        if (registrationListener != null) {
            try {
                nsdManager.unregisterService(registrationListener);
            } catch (Exception ignored) {
                // Already unregistered.
            }
            registrationListener = null;
        }
        if (multicastLock != null && multicastLock.isHeld()) {
            multicastLock.release();
        }
        multicastLock = null;
    }

    private void acquireMulticast() {
        try {
            WifiManager wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            multicastLock = wifi.createMulticastLock("h4xtor-share-mdns");
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        } catch (Exception ignored) {
            multicastLock = null;
        }
    }

    private void register() {
        NsdServiceInfo service = new NsdServiceInfo();
        service.setServiceName(identity.deviceId());
        service.setServiceType(SERVICE_TYPE);
        service.setPort(AppIdentity.PORT);
        try {
            service.setAttribute("id", identity.deviceId());
            service.setAttribute("name", identity.deviceName());
            service.setAttribute("platform", "android");
            service.setAttribute("protocol", "1");
            service.setAttribute("fingerprint", identity.fingerprint());
        } catch (Exception error) {
            listener.onStatus("mDNS attributes unavailable: " + safeMessage(error));
        }

        registrationListener = new NsdManager.RegistrationListener() {
            @Override public void onRegistrationFailed(NsdServiceInfo serviceInfo, int errorCode) {
                listener.onStatus("mDNS advertise failed (" + errorCode + ")");
            }
            @Override public void onUnregistrationFailed(NsdServiceInfo serviceInfo, int errorCode) { }
            @Override public void onServiceRegistered(NsdServiceInfo serviceInfo) { }
            @Override public void onServiceUnregistered(NsdServiceInfo serviceInfo) { }
        };
        try {
            nsdManager.registerService(service, NsdManager.PROTOCOL_DNS_SD, registrationListener);
        } catch (Exception error) {
            listener.onStatus("mDNS advertise unavailable: " + safeMessage(error));
        }
    }

    private void discover() {
        discoveryListener = new NsdManager.DiscoveryListener() {
            @Override public void onStartDiscoveryFailed(String serviceType, int errorCode) {
                listener.onStatus("mDNS discovery failed (" + errorCode + ")");
            }

            @Override public void onStopDiscoveryFailed(String serviceType, int errorCode) { }
            @Override public void onDiscoveryStarted(String serviceType) { }
            @Override public void onDiscoveryStopped(String serviceType) { }

            @Override
            public void onServiceFound(NsdServiceInfo serviceInfo) {
                if (identity.deviceId().equals(serviceInfo.getServiceName())) {
                    return;
                }
                try {
                    nsdManager.resolveService(serviceInfo, new NsdManager.ResolveListener() {
                        @Override public void onResolveFailed(NsdServiceInfo info, int errorCode) { }

                        @Override
                        public void onServiceResolved(NsdServiceInfo info) {
                            if (info.getHost() == null) {
                                return;
                            }
                            String address = info.getHost().getHostAddress();
                            if (address == null || address.contains(":")) {
                                return;
                            }
                            listener.onPeerAddress(address, info.getPort());
                        }
                    });
                } catch (Exception ignored) {
                    // Active LAN scan remains available as a deterministic fallback.
                }
            }

            @Override public void onServiceLost(NsdServiceInfo serviceInfo) { }
        };
        try {
            nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener);
        } catch (Exception error) {
            listener.onStatus("mDNS discovery unavailable: " + safeMessage(error));
        }
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? error.getClass().getSimpleName() : message;
    }
}
