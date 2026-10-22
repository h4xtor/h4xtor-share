package com.h4xtor.share;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class H4xtorServerTest {
    @Test
    public void pairingOverTheBluetoothBridgeIsSeenAsLoopback() {
        // A PC that pairs over Bluetooth reaches this server from 127.0.0.1 (the bridge):
        // that address must never be remembered as the PC's own address.
        assertTrue(H4xtorServer.isLoopback("127.0.0.1"));
        assertTrue(H4xtorServer.isLoopback("::1"));
        assertFalse(H4xtorServer.isLoopback("192.168.1.20"));
        assertFalse(H4xtorServer.isLoopback(""));
    }

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

    @Test
    public void safeRelativePathNeutralisesTraversal() {
        assertEquals("a/b/c.txt", H4xtorServer.safeRelativePath("/a/./b/c.txt"));
        assertEquals("_CON/x.txt", H4xtorServer.safeRelativePath("CON\\x.txt"));
    }

    @Test
    public void onlyHttpLinksAreSafe() {
        org.junit.Assert.assertTrue(H4xtorServer.isSafeUrl("https://example.com/a"));
        org.junit.Assert.assertFalse(H4xtorServer.isSafeUrl("javascript:alert(1)"));
        org.junit.Assert.assertFalse(H4xtorServer.isSafeUrl("https://a b"));
    }
}
