package com.h4xtor.share;

import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Plain-Java rules for app updates (no Android classes, so JUnit can test them):
 * version order, the CHANGELOG.md format, the GitHub release JSON and SHA-256.
 * Only GitHub Releases of h4xtor/h4xtor-share over HTTPS are a valid source.
 */
final class UpdateLogic {
    static final String REPO = "h4xtor/h4xtor-share";
    static final String API_URL = "https://api.github.com/repos/" + REPO + "/releases/latest";
    static final String DOWNLOAD_PREFIX = "https://github.com/" + REPO + "/releases/download/";
    static final String APK = "h4xtor-share-android.apk";
    static final String CHANGELOG = "CHANGELOG.md";
    static final long CHECK_INTERVAL_MS = 24L * 3600 * 1000;
    static final long LATER_DELAY_MS = 24L * 3600 * 1000;
    static final String[] SECTIONS = {"Nyt", "Forbedret", "Rettet"};
    static final String NO_CHANGELOG = "Ingen nyhedsliste tilgængelig.";

    private static final Pattern HEADING =
            Pattern.compile("^##\\s+v?(\\d+(?:\\.\\d+)+)\\s*[–—-]\\s*(\\d{4}-\\d{2}-\\d{2})\\s*$");
    private static final Pattern SECTION = Pattern.compile("^###\\s+(.+?)\\s*$");
    private static final Pattern SHA256 = Pattern.compile("^[0-9a-f]{64}$");

    private UpdateLogic() {
    }

    static final class Entry {
        final String version;
        final String date;
        final Map<String, List<String>> sections = new LinkedHashMap<>();

        Entry(String version, String date) {
            this.version = version;
            this.date = date;
        }
    }

    static final class Release {
        final String version;
        final String apkUrl;
        final String checksumUrl;
        final String changelogUrl;

        Release(String version, String apkUrl, String checksumUrl, String changelogUrl) {
            this.version = version;
            this.apkUrl = apkUrl;
            this.checksumUrl = checksumUrl;
            this.changelogUrl = changelogUrl;
        }
    }

    // ------------------------------------------------------------- versions
    static int compare(String a, String b) {
        int[] left = parts(a);
        int[] right = parts(b);
        for (int index = 0; index < Math.max(left.length, right.length); index++) {
            int x = index < left.length ? left[index] : 0;
            int y = index < right.length ? right[index] : 0;
            if (x != y) {
                return Integer.compare(x, y);
            }
        }
        return 0;
    }

    static boolean isNewer(String candidate, String current) {
        return compare(candidate, current) > 0;
    }

    private static int[] parts(String value) {
        String[] pieces = value.trim().replaceFirst("^[vV]", "").split("\\.");
        int[] numbers = new int[pieces.length];
        for (int index = 0; index < pieces.length; index++) {
            String digits = pieces[index].replaceAll("\\D", "");
            try {
                numbers[index] = digits.isEmpty() ? 0 : Integer.parseInt(digits);
            } catch (NumberFormatException tooBig) {
                numbers[index] = Integer.MAX_VALUE;
            }
        }
        return numbers;
    }

    // ------------------------------------------------------------ changelog
    static List<Entry> parseChangelog(String text) {
        List<Entry> entries = new ArrayList<>();
        String section = null;
        for (String raw : (text == null ? "" : text).split("\\r?\\n")) {
            String line = raw.trim();
            Matcher heading = HEADING.matcher(line);
            if (heading.matches()) {
                entries.add(new Entry(heading.group(1), heading.group(2)));
                section = null;
                continue;
            }
            if (entries.isEmpty()) {
                continue;
            }
            Matcher match = SECTION.matcher(line);
            if (match.matches()) {
                section = isSection(match.group(1)) ? match.group(1) : null;
            } else if (section != null && (line.startsWith("- ") || line.startsWith("* "))) {
                Entry entry = entries.get(entries.size() - 1);
                List<String> items = entry.sections.get(section);
                if (items == null) {
                    items = new ArrayList<>();
                    entry.sections.put(section, items);
                }
                items.add(line.substring(2).trim());
            } else if (section != null && !line.isEmpty() && Character.isWhitespace(raw.charAt(0))) {
                // Wrapped bullet: an indented line continues the previous item.
                List<String> items = entries.get(entries.size() - 1).sections.get(section);
                if (items != null && !items.isEmpty()) {
                    items.set(items.size() - 1, items.get(items.size() - 1) + " " + line);
                }
            }
        }
        entries.sort((a, b) -> compare(b.version, a.version));
        return entries;
    }

    private static boolean isSection(String name) {
        for (String known : SECTIONS) {
            if (known.equals(name)) {
                return true;
            }
        }
        return false;
    }

    /** Everything newer than {@code current} up to {@code latest}, newest first. */
    static List<Entry> between(List<Entry> entries, String current, String latest) {
        List<Entry> result = new ArrayList<>();
        for (Entry entry : entries) {
            if (isNewer(entry.version, current) && !isNewer(entry.version, latest)) {
                result.add(entry);
            }
        }
        return result;
    }

    static String format(List<Entry> entries, int limit) {
        if (entries.isEmpty()) {
            return NO_CHANGELOG;
        }
        StringBuilder text = new StringBuilder();
        for (int index = 0; index < Math.min(limit, entries.size()); index++) {
            Entry entry = entries.get(index);
            if (index > 0) {
                text.append("\n\n");
            }
            text.append("Version ").append(entry.version).append("  ·  ").append(entry.date);
            for (String name : SECTIONS) {
                List<String> items = entry.sections.get(name);
                if (items == null || items.isEmpty()) {
                    continue;
                }
                text.append("\n\n").append(name);
                for (String item : items) {
                    text.append("\n•  ").append(item);
                }
            }
        }
        return text.toString();
    }

    // ------------------------------------------------------------ the release
    /** The release JSON from GitHub; null for drafts, pre-releases or foreign download links. */
    static Release parseRelease(String json, String downloadPrefix) throws org.json.JSONException {
        JSONObject payload = new JSONObject(json);
        if (payload.optBoolean("draft") || payload.optBoolean("prerelease")) {
            return null;
        }
        String version = payload.optString("tag_name", "").replaceFirst("^[vV]", "");
        Map<String, String> assets = new LinkedHashMap<>();
        JSONArray list = payload.optJSONArray("assets");
        for (int index = 0; list != null && index < list.length(); index++) {
            JSONObject asset = list.getJSONObject(index);
            String url = asset.optString("browser_download_url", "");
            if (url.startsWith(downloadPrefix)) {
                assets.put(asset.optString("name"), url);
            }
        }
        if (version.isEmpty()) {
            return null;
        }
        return new Release(version, assets.get(APK), assets.get(APK + ".sha256"), assets.get(CHANGELOG));
    }

    static boolean shouldPrompt(String version, String skipped, String later, long laterUntil, long now) {
        if (version.equals(skipped)) {
            return false;
        }
        return !(version.equals(later) && now < laterUntil);
    }

    // ----------------------------------------------------------------- SHA-256
    /** First token of a "&lt;hash&gt;  file" line, or null when it is not a SHA-256. */
    static String parseChecksum(String text) {
        String token = text == null ? "" : text.trim().split("\\s+")[0].toLowerCase(Locale.ROOT);
        return SHA256.matcher(token).matches() ? token : null;
    }

    static String sha256(InputStream input) throws IOException {
        MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IOException(impossible);
        }
        byte[] buffer = new byte[256 * 1024];
        int read;
        while ((read = input.read(buffer)) != -1) {
            digest.update(buffer, 0, read);
        }
        StringBuilder hex = new StringBuilder();
        for (byte value : digest.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", value));
        }
        return hex.toString();
    }
}
