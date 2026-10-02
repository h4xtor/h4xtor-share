package com.h4xtor.share;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Arrays;

import org.junit.Test;

public final class PairingInviteTest {
    private static String repeat(char value, int count) {
        char[] chars = new char[count];
        Arrays.fill(chars, value);
        return new String(chars);
    }

    @Test
    public void roundTripsUnicodeNamesAndAddresses() {
        PairingInvite invite = new PairingInvite(repeat('a', 32), "Lennarts PC – æøå & co", repeat('b', 64),
                47474, Arrays.asList("192.168.1.10", "192.168.49.1"), repeat('s', 24), "windows");
        PairingInvite parsed = PairingInvite.parse(invite.toUri());
        assertEquals(invite.deviceId, parsed.deviceId);
        assertEquals(invite.name, parsed.name);
        assertEquals(invite.fingerprint, parsed.fingerprint);
        assertEquals(invite.addresses, parsed.addresses);
        assertEquals(invite.secret, parsed.secret);
        assertEquals("windows", parsed.platform);
    }

    @Test
    public void parsesDesktopGeneratedInvite() {
        String uri = "h4xtor://pair?v=1&id=" + repeat('a', 32) + "&n=Lennarts%20PC%20%E2%80%93%20kontor"
                + "&fp=" + repeat('b', 64) + "&p=47474&a=192.168.1.10%2C192.168.49.23&s=" + repeat('x', 24)
                + "&pl=windows";
        PairingInvite parsed = PairingInvite.parse(uri);
        assertEquals("Lennarts PC – kontor", parsed.name);
        assertEquals(2, parsed.addresses.size());
    }

    @Test
    public void rejectsGarbage() {
        String[] bad = {"https://example.com", "h4xtor://pair?v=2", "h4xtor://pair?v=1&id=zz",
                "h4xtor://pair?v=1&id=" + repeat('a', 32) + "&fp=" + repeat('b', 64) + "&p=1&a=&s=" + repeat('x', 20)};
        for (String value : bad) {
            try {
                PairingInvite.parse(value);
                fail("accepted " + value);
            } catch (IllegalArgumentException expected) {
                // ok
            }
        }
        assertTrue(PairingInvite.looksLikeInvite("H4XTOR://pair?v=1"));
        assertFalse(PairingInvite.looksLikeInvite("WIFI:T:WPA;S:x;;"));
    }

    @Test
    public void ipv4Validation() {
        assertTrue(PairingInvite.isIpv4("10.0.0.1"));
        assertFalse(PairingInvite.isIpv4("256.1.1.1"));
        assertFalse(PairingInvite.isIpv4("fe80::1"));
    }
}
