package com.h4xtor.share;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class CopyWatchServiceTest {
    @Test
    public void recognisesCopyButtons() {
        for (String label : new String[] {"Kopiér", "Kopier", "kopiér link", "Copy", "COPY LINK", "  Copy  ", "Link kopieren"}) {
            assertTrue(label, CopyWatchService.isCopyLabel(label));
        }
    }

    @Test
    public void ignoresEverythingElse() {
        for (String label : new String[] {"Indsæt", "Paste", "Del", "Klip", "", "Microcopy",
                "Copy this long paragraph of text about copying things around"}) {
            assertFalse(label, CopyWatchService.isCopyLabel(label));
        }
        assertFalse(CopyWatchService.isCopyLabel(null));
    }
}
