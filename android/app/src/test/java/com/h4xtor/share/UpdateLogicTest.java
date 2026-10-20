package com.h4xtor.share;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import org.junit.Test;

public class UpdateLogicTest {
    private static final String LOG = "# Opdateringslog\n\n"
            + "## 9.10.0 – 2030-02-01\n### Nyt\n- Ti\n### Rettet\n- Fejl B\n  fortsat\n\n"
            + "## 9.9.9 – 2030-01-01\n### Forbedret\n- Ni\n### Andet\n- ignoreres\n\n"
            + "## 0.0.1 – 2020-01-01\n### Nyt\n- Gammel\n";

    @Test
    public void versionsCompareNumerically() {
        assertTrue(UpdateLogic.isNewer("1.10.0", "1.9.9"));
        assertTrue(UpdateLogic.isNewer("v1.2.1", "1.2.0"));
        assertFalse(UpdateLogic.isNewer("1.2.0", "v1.2.0"));
        assertFalse(UpdateLogic.isNewer("1.2", "1.2.0"));
        assertFalse(UpdateLogic.isNewer("1.9.9", "1.10.0"));
    }

    @Test
    public void changelogIsParsedAndAggregatedNewestFirst() {
        List<UpdateLogic.Entry> entries = UpdateLogic.parseChangelog(LOG);
        assertEquals(3, entries.size());
        assertEquals("9.10.0", entries.get(0).version);
        assertEquals(List.of("Fejl B fortsat"), entries.get(0).sections.get("Rettet"));
        assertNull(entries.get(1).sections.get("Andet"));
        List<UpdateLogic.Entry> skipped = UpdateLogic.between(entries, "0.0.1", "9.10.0");
        assertEquals(2, skipped.size());
        String text = UpdateLogic.format(skipped, 10);
        assertTrue(text.startsWith("Version 9.10.0  ·  2030-02-01\n\nNyt\n•  Ti"));
        assertTrue(text.indexOf("9.10.0") < text.indexOf("9.9.9"));
        assertEquals(UpdateLogic.NO_CHANGELOG, UpdateLogic.format(UpdateLogic.parseChangelog(""), 3));
    }

    @Test
    public void repoChangelogHasThisVersion() throws Exception {
        Path file = Paths.get("../../CHANGELOG.md");
        String text = new String(Files.readAllBytes(file), StandardCharsets.UTF_8);
        List<UpdateLogic.Entry> entries = UpdateLogic.parseChangelog(text);
        assertEquals(AppIdentity.VERSION, entries.get(0).version);
        assertFalse(entries.get(0).sections.isEmpty());
    }

    @Test
    public void releaseOnlyTrustsTheRepoDownloads() throws Exception {
        String prefix = UpdateLogic.DOWNLOAD_PREFIX;
        String json = "{\"tag_name\":\"v9.10.0\",\"assets\":["
                + "{\"name\":\"h4xtor-share-android.apk\",\"browser_download_url\":\"" + prefix + "v9.10.0/h4xtor-share-android.apk\"},"
                + "{\"name\":\"h4xtor-share-android.apk.sha256\",\"browser_download_url\":\"http://evil.example/x\"}]}";
        UpdateLogic.Release release = UpdateLogic.parseRelease(json, prefix);
        assertNotNull(release);
        assertEquals("9.10.0", release.version);
        assertNotNull(release.apkUrl);
        assertNull(release.checksumUrl);  // not from the repo: ignored, so no install
        assertNull(UpdateLogic.parseRelease("{\"tag_name\":\"v9\",\"prerelease\":true}", prefix));
    }

    @Test
    public void skipAndLater() {
        assertTrue(UpdateLogic.shouldPrompt("2.0.0", null, null, 0, 1000));
        assertFalse(UpdateLogic.shouldPrompt("2.0.0", null, "2.0.0", 5000, 1000));  // "Senere"
        assertTrue(UpdateLogic.shouldPrompt("2.0.0", null, "2.0.0", 5000, 6000));
        assertFalse(UpdateLogic.shouldPrompt("2.0.0", "2.0.0", null, 0, 1000));  // skipped
        assertTrue(UpdateLogic.shouldPrompt("2.0.1", "2.0.0", null, 0, 1000));
    }

    @Test
    public void checksum() throws Exception {
        String abc = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        assertEquals(abc, UpdateLogic.sha256(new ByteArrayInputStream("abc".getBytes(StandardCharsets.UTF_8))));
        assertEquals(abc, UpdateLogic.parseChecksum(abc.toUpperCase() + "  h4xtor-share-android.apk\n"));
        assertNull(UpdateLogic.parseChecksum("not a hash"));
    }
}
