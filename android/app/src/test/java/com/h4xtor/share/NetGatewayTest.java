package com.h4xtor.share;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public final class NetGatewayTest {
    @Test
    public void parsesConnectTargets() {
        assertArrayEquals(new String[]{"example.com", "443"}, NetGateway.parseTarget("example.com:443"));
        assertArrayEquals(new String[]{"2001:db8::1", "80"}, NetGateway.parseTarget("[2001:db8::1]:80"));
    }

    @Test
    public void rejectsMalformedTargets() {
        assertNull(NetGateway.parseTarget(null));
        assertNull(NetGateway.parseTarget("example.com"));
        assertNull(NetGateway.parseTarget(":443"));
        assertNull(NetGateway.parseTarget("example.com:0"));
        assertNull(NetGateway.parseTarget("example.com:70000"));
        assertNull(NetGateway.parseTarget("example.com:http"));
        assertNull(NetGateway.parseTarget("2001:db8::1:80"));
        assertNull(NetGateway.parseTarget("[2001:db8::1]"));
    }
}
