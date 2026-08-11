package com.h4xtor.share;

import org.json.JSONObject;

public final class Peer {
    public final String deviceId;
    public final String name;
    public final String address;
    public final int port;
    public final String fingerprint;
    public final String platform;

    public Peer(
            String deviceId,
            String name,
            String address,
            int port,
            String fingerprint,
            String platform) {
        this.deviceId = deviceId;
        this.name = name;
        this.address = address;
        this.port = port;
        this.fingerprint = fingerprint;
        this.platform = platform;
    }

    public String endpoint() {
        return "https://" + address + ":" + port;
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
                object.optString("platform", "unknown"));
    }
}
