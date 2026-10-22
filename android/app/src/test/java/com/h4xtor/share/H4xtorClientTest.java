package com.h4xtor.share;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.concurrent.atomic.AtomicInteger;

public class H4xtorClientTest {
    @Test
    public void stalledUploadIsCutOffOnce() throws Exception {
        AtomicInteger cut = new AtomicInteger();
        H4xtorClient.Stall stall = new H4xtorClient.Stall(300, cut::incrementAndGet);
        Thread.sleep(1_200);
        stall.stop();
        assertTrue(stall.fired());
        assertEquals(1, cut.get());
    }

    @Test
    public void movingUploadIsLeftAlone() throws Exception {
        AtomicInteger cut = new AtomicInteger();
        H4xtorClient.Stall stall = new H4xtorClient.Stall(300, cut::incrementAndGet);
        for (int index = 0; index < 12; index++) {
            Thread.sleep(100);
            stall.moved();
        }
        stall.stop();
        assertFalse(stall.fired());
        assertEquals(0, cut.get());
    }
}
