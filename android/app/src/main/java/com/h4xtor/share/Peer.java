package com.h4xtor.share;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

public final class Peer {
    public final String deviceId;
    public final String name;
    public final String address;
    public final int port;
    public final String fingerprint;
    public final String platform;
    public final String transport;
    public final List<String> capabilities;

    public Peer(
            String deviceId,
            String name,
            String address,
            int port,
            String fingerprint,
            String platform) {
        this(deviceId, name, address, port, fingerprint, platform, "lan", Collections.emptyList());
    }

    public Peer(
            String deviceId,
            String name,
            String address,
            int port,
            String fingerprint,
            String platform,
            String transport,
            List<String> capabilities) {
        this.deviceId = deviceId;
        this.name = name;
        this.address = address;
        this.port = port;
        this.fingerprint = fingerprint == null ? "" : fingerprint.toLowerCase(Locale.ROOT);
        this.platform = platform == null ? "unknown" : platform;
        this.transport = transport == null ? "lan" : transport;
        this.capabilities = Collections.unmodifiableList(
                capabilities == null ? new ArrayList<>() : new ArrayList<>(capabilities));
    }

    public String endpoint() {
        return "https://" + address + ":" + port;
    }

    public boolean supports(String capability) {
        return capabilities.contains(capability);
    }

    public boolean isDesktop() {
        String value = platform.toLowerCase(Locale.ROOT);
        return value.equals("windows") || value.equals("linux") || value.equals("darwin")
                || value.equals("macos");
    }

    public Peer withAddress(String newAddress, String newTransport) {
        return new Peer(deviceId, name, newAddress, port, fingerprint, platform, newTransport, capabilities);
    }

    public Peer mergedWith(Peer newer) {
        List<String> caps = newer.capabilities.isEmpty() ? capabilities : newer.capabilities;
        String fp = newer.fingerprint.isEmpty() ? fingerprint : newer.fingerprint;
        return new Peer(deviceId, newer.name, newer.address, newer.port, fp, newer.platform,
                newer.transport, caps);
    }

    public JSONObject toJson() throws Exception {
        JSONArray caps = new JSONArray();
        for (String capability : capabilities) {
            caps.put(capability);
        }
        return new JSONObject()
                .put("device_id", deviceId)
                .put("name", name)
                .put("address", address)
                .put("port", port)
                .put("fingerprint", fingerprint)
                .put("platform", platform)
                .put("transport", transport)
                .put("capabilities", caps);
    }

    public static Peer fromJson(JSONObject object) throws Exception {
        return new Peer(
                object.getString("device_id"),
                object.optString("name", "Enhed"),
                object.getString("address"),
                object.optInt("port", AppIdentity.PORT),
                object.optString("fingerprint", ""),
                object.optString("platform", "unknown"),
                object.optString("transport", "lan"),
                capabilities(object.optJSONArray("capabilities")));
    }

    public static Peer fromInfo(JSONObject object, String address, int fallbackPort) throws Exception {
        int protocol = object.optInt("protocol", 0);
        if (protocol != 1) {
            throw new IllegalArgumentException("Unsupported h4xtor-share protocol");
        }
        return new Peer(
                object.getString("device_id"),
                object.getString("name"),
                address,
                object.optInt("port", fallbackPort),
                object.getString("fingerprint"),
                object.optString("platform", "unknown"),
                "lan",
                capabilities(object.optJSONArray("capabilities")));
    }

    static List<String> capabilities(JSONArray array) {
        List<String> result = new ArrayList<>();
        if (array == null) {
            return result;
        }
        for (int index = 0; index < array.length() && index < 32; index++) {
            String value = array.optString(index, "");
            if (!value.isEmpty()) {
                result.add(value);
            }
        }
        return result;
    }
}
