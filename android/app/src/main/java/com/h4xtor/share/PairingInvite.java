package com.h4xtor.share;

import java.net.URLDecoder;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * QR pairing invite: {@code h4xtor://pair?v=1&id=..&n=..&fp=..&p=..&a=ip1,ip2&s=..&pl=..}.
 *
 * <p>Pure Java (no Android classes) so it is unit-testable and identical to the
 * desktop implementation in {@code h4xtor_share/pairing.py}.
 */
public final class PairingInvite {
    public static final String SCHEME = "h4xtor";
    private static final String VERSION = "1";

    public final String deviceId;
    public final String name;
    public final String fingerprint;
    public final int port;
    public final List<String> addresses;
    public final String secret;
    public final String platform;

    public PairingInvite(
            String deviceId,
            String name,
            String fingerprint,
            int port,
            List<String> addresses,
            String secret,
            String platform) {
        this.deviceId = deviceId;
        this.name = name;
        this.fingerprint = fingerprint.toLowerCase(Locale.ROOT);
        this.port = port;
        this.addresses = Collections.unmodifiableList(new ArrayList<>(addresses));
        this.secret = secret;
        this.platform = platform;
    }

    public String toUri() {
        StringBuilder builder = new StringBuilder(SCHEME).append("://pair?");
        builder.append("v=").append(VERSION);
        builder.append("&id=").append(encode(deviceId));
        builder.append("&n=").append(encode(name));
        builder.append("&fp=").append(encode(fingerprint));
        builder.append("&p=").append(port);
        builder.append("&a=").append(encode(String.join(",", addresses)));
        builder.append("&s=").append(encode(secret));
        builder.append("&pl=").append(encode(platform));
        return builder.toString();
    }

    public static boolean looksLikeInvite(String text) {
        return text != null && text.trim().toLowerCase(Locale.ROOT).startsWith(SCHEME + "://pair");
    }

    public static PairingInvite parse(String uri) {
        if (!looksLikeInvite(uri)) {
            throw new IllegalArgumentException("Det er ikke en h4xtor share-kode");
        }
        String trimmed = uri.trim();
        int question = trimmed.indexOf('?');
        if (question < 0) {
            throw new IllegalArgumentException("Koden mangler data");
        }
        Map<String, String> values = new HashMap<>();
        for (String pair : trimmed.substring(question + 1).split("&")) {
            if (pair.isEmpty()) {
                continue;
            }
            int equals = pair.indexOf('=');
            String key = decode(equals < 0 ? pair : pair.substring(0, equals));
            String value = equals < 0 ? "" : decode(pair.substring(equals + 1));
            if (!values.containsKey(key)) {
                values.put(key, value);
            }
        }
        if (!VERSION.equals(values.get("v"))) {
            throw new IllegalArgumentException("Koden er fra en anden version");
        }
        String id = values.getOrDefault("id", "");
        String fp = values.getOrDefault("fp", "").toLowerCase(Locale.ROOT);
        String secret = values.getOrDefault("s", "");
        if (!id.matches("[a-f0-9]{32}")) {
            throw new IllegalArgumentException("Ugyldigt enheds-id i koden");
        }
        if (!fp.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("Ugyldigt certifikat i koden");
        }
        if (secret.length() < 16 || secret.length() > 128) {
            throw new IllegalArgumentException("Ugyldig engangskode");
        }
        int port;
        try {
            port = Integer.parseInt(values.getOrDefault("p", ""));
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("Ugyldig port i koden");
        }
        if (port <= 0 || port >= 65536) {
            throw new IllegalArgumentException("Ugyldig port i koden");
        }
        List<String> addresses = new ArrayList<>();
        for (String raw : values.getOrDefault("a", "").split(",")) {
            String candidate = raw.trim();
            if (isIpv4(candidate)) {
                addresses.add(candidate);
            }
        }
        if (addresses.isEmpty()) {
            throw new IllegalArgumentException("Koden indeholder ingen adresse");
        }
        String name = values.getOrDefault("n", "Enhed");
        if (name.length() > 80) {
            name = name.substring(0, 80);
        }
        String platform = values.getOrDefault("pl", "unknown");
        return new PairingInvite(id, name.isEmpty() ? "Enhed" : name, fp, port, addresses, secret,
                platform.isEmpty() ? "unknown" : platform);
    }

    static boolean isIpv4(String value) {
        String[] parts = value.split("\\.");
        if (parts.length != 4) {
            return false;
        }
        for (String part : parts) {
            if (part.isEmpty() || part.length() > 3 || !part.matches("\\d+")) {
                return false;
            }
            if (Integer.parseInt(part) > 255) {
                return false;
            }
        }
        return true;
    }

    private static String encode(String value) {
        try {
            return URLEncoder.encode(value, StandardCharsets.UTF_8.name()).replace("+", "%20");
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }

    private static String decode(String value) {
        try {
            return URLDecoder.decode(value, StandardCharsets.UTF_8.name());
        } catch (Exception error) {
            throw new IllegalArgumentException("Ugyldig kode");
        }
    }
}
