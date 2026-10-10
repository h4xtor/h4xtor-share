package com.h4xtor.share;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class ShareLogicTest {
    @Test
    public void notificationPayloadIsClippedToProtocolLimits() throws Exception {
        String longText = new String(new char[5000]).replace('\0', 'x');
        JSONObject json = ShareLogic.notificationPosted(
                longText, longText, longText, longText, longText, 1760090000000L, "AAAA", true, false);
        assertEquals("posted", json.getString("event"));
        assertEquals(512, json.getString("key").length());
        assertEquals(200, json.getString("package").length());
        assertEquals(80, json.getString("app").length());
        assertEquals(200, json.getString("title").length());
        assertEquals(4000, json.getString("text").length());
        assertEquals(1760090000000L, json.getLong("time"));
        assertEquals("AAAA", json.getString("icon"));
        assertTrue(json.getBoolean("can_reply"));
        assertFalse(json.getBoolean("can_dismiss"));
    }

    @Test
    public void missingIconBecomesEmptyString() throws Exception {
        JSONObject json = ShareLogic.notificationPosted("k", "p", "App", "T", "x", 1L, null, false, true);
        assertEquals("", json.getString("icon"));
    }

    @Test
    public void removedPayloadOnlyHasEventAndKey() throws Exception {
        JSONObject json = ShareLogic.notificationRemoved("0|com.whatsapp|1|null|10123");
        assertEquals("removed", json.getString("event"));
        assertEquals("0|com.whatsapp|1|null|10123", json.getString("key"));
        assertEquals(2, json.length());
    }

    @Test
    public void iconSizeLimitIs48Kb() {
        assertTrue(ShareLogic.iconFits(48 * 1024));
        assertFalse(ShareLogic.iconFits(48 * 1024 + 1));
        assertFalse(ShareLogic.iconFits(0));
    }

    @Test
    public void skipsOwnOngoingSummaryAndEmptyNotifications() {
        assertTrue(ShareLogic.shouldMirror(false, false, false, "Mor", ""));
        assertTrue(ShareLogic.shouldMirror(false, false, false, "", "Hej"));
        assertFalse(ShareLogic.shouldMirror(true, false, false, "Mor", "Hej"));
        assertFalse(ShareLogic.shouldMirror(false, true, false, "Mor", "Hej"));
        assertFalse(ShareLogic.shouldMirror(false, false, true, "Mor", "Hej"));
        assertFalse(ShareLogic.shouldMirror(false, false, false, " ", null));
    }

    @Test
    public void emptyAllowListMeansAllApps() {
        assertTrue(ShareLogic.isAllowed(Collections.emptySet(), "com.whatsapp"));
        assertTrue(ShareLogic.isAllowed(null, "com.whatsapp"));
        Set<String> only = new HashSet<>(Arrays.asList("com.whatsapp"));
        assertTrue(ShareLogic.isAllowed(only, "com.whatsapp"));
        assertFalse(ShareLogic.isAllowed(only, "com.facebook.orca"));
    }

    @Test
    public void allowListParsingDropsJunk() {
        Set<String> parsed = ShareLogic.parseAllowList(Arrays.asList(" com.a ", "", null, "com.b", "com.a"));
        assertEquals(new HashSet<>(Arrays.asList("com.a", "com.b")), parsed);
        assertTrue(ShareLogic.parseAllowList(null).isEmpty());
    }

    @Test
    public void duplicateUpdatesWithinTwoSecondsAreDropped() {
        ShareLogic.DuplicateGate gate = new ShareLogic.DuplicateGate(2_000L);
        assertTrue(gate.accept("k", "Mor", "Hej", 1_000L));
        assertFalse(gate.accept("k", "Mor", "Hej", 2_500L));
        assertTrue(gate.accept("k", "Mor", "Hej igen", 2_600L));
        assertTrue(gate.accept("k", "Mor", "Hej igen", 5_000L));
        assertTrue(gate.accept("other", "Mor", "Hej igen", 5_001L));
        gate.forget("k");
        assertTrue(gate.accept("k", "Mor", "Hej igen", 5_002L));
    }

    @Test
    public void volumeIsClampedAndScaled() {
        assertEquals(0, ShareLogic.clampPercent(-20));
        assertEquals(100, ShareLogic.clampPercent(250));
        assertEquals(0, ShareLogic.volumeIndex(-5, 15));
        assertEquals(15, ShareLogic.volumeIndex(500, 15));
        assertEquals(8, ShareLogic.volumeIndex(50, 15));
        assertEquals(0, ShareLogic.volumeIndex(50, 0));
        assertEquals(53, ShareLogic.volumePercent(8, 15));
        assertEquals(0, ShareLogic.volumePercent(3, 0));
    }

    @Test
    public void smsJsonMatchesTheProtocol() throws Exception {
        JSONObject thread = ShareLogic.smsThread("12", "+4512345678", "Mor", "Hej", 1760090000000L, 2);
        assertEquals("12", thread.getString("thread_id"));
        assertEquals("+4512345678", thread.getString("address"));
        assertEquals("Mor", thread.getString("name"));
        assertEquals("Hej", thread.getString("snippet"));
        assertEquals(1760090000000L, thread.getLong("time"));
        assertEquals(2, thread.getInt("unread"));

        JSONObject message = ShareLogic.smsMessage("77", "+4512345678", "Hej", 5L, true);
        assertEquals("77", message.getString("id"));
        assertTrue(message.getBoolean("outgoing"));

        JSONObject incoming = ShareLogic.smsIncoming("12", "+4512345678", "", "Hej", 5L);
        assertEquals("", incoming.getString("name"));
        assertEquals(5, incoming.length());
    }

    @Test
    public void smsFieldsAreClipped() throws Exception {
        String longText = new String(new char[5000]).replace('\0', 'y');
        JSONObject incoming = ShareLogic.smsIncoming("1", longText, longText, longText, 1L);
        assertEquals(64, incoming.getString("address").length());
        assertEquals(80, incoming.getString("name").length());
        assertEquals(4000, incoming.getString("body").length());
    }

    @Test
    public void onlyInboxIsIncoming() {
        assertFalse(ShareLogic.isOutgoing(ShareLogic.SMS_TYPE_INBOX));
        assertTrue(ShareLogic.isOutgoing(2));
        assertTrue(ShareLogic.isOutgoing(5));
    }

    @Test
    public void limitsFallBackAndCap() {
        assertEquals(50, ShareLogic.limit(0, 50, 200));
        assertEquals(50, ShareLogic.limit(-3, 50, 200));
        assertEquals(30, ShareLogic.limit(30, 50, 200));
        assertEquals(200, ShareLogic.limit(5000, 50, 200));
    }

    @Test
    public void phoneNumberValidation() {
        assertTrue(ShareLogic.validPhoneNumber("+45 12 34 56 78"));
        assertTrue(ShareLogic.validPhoneNumber("12345678"));
        assertFalse(ShareLogic.validPhoneNumber(""));
        assertFalse(ShareLogic.validPhoneNumber("Mor"));
        assertFalse(ShareLogic.validPhoneNumber("1;2"));
        assertFalse(ShareLogic.validPhoneNumber(null));
    }

    @Test
    public void screenshotNameFollowsTheProtocol() {
        assertTrue(ShareLogic.screenshotName(1760090000000L).matches("Skaermbillede-\\d{8}-\\d{6}\\.png"));
    }

    @Test
    public void sendToAllSummaryNamesTheFailures() {
        assertEquals("Sendt til 3 af 3", ShareLogic.allSummary(3, Collections.emptyList(), Collections.emptyList()));
        assertEquals("Sendt til 2 af 3 – Bærbar fejlede: timeout",
                ShareLogic.allSummary(3, List.of("Bærbar"), List.of("timeout")));
        assertEquals("Sendt til 1 af 3 – A fejlede; B fejlede: nej",
                ShareLogic.allSummary(3, List.of("A", "B"), List.of("", "nej")));
    }
}
