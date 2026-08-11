package com.h4xtor.share;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class H4xtorServerTest {
    @Test
    public void safeFileNameStripsPathTraversal() {
        assertEquals("payload.bin", H4xtorServer.safeFileName("../../payload.bin"));
        assertEquals("payload.bin", H4xtorServer.safeFileName("C:\\temp\\payload.bin"));
    }

    @Test
    public void safeFileNameMatchesDesktopWindowsRules() {
        assertEquals("report2026.pdf", H4xtorServer.safeFileName("report:2026.pdf"));
        assertEquals("_CON.txt", H4xtorServer.safeFileName("CON.txt"));
    }
}
