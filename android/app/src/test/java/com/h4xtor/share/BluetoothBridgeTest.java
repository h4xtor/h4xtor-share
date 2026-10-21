package com.h4xtor.share;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.DataInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Random;
import java.util.concurrent.atomic.AtomicReference;

public class BluetoothBridgeTest {
    /** Each accepted connection gets a tag, then an echo of everything it sends. */
    private static ServerSocket echo(String tag) throws Exception {
        ServerSocket server = new ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"));
        Thread thread = new Thread(() -> {
            while (!server.isClosed()) {
                try {
                    Socket socket = server.accept();
                    new Thread(() -> {
                        try (Socket s = socket) {
                            OutputStream out = s.getOutputStream();
                            out.write(tag.getBytes(StandardCharsets.US_ASCII));
                            InputStream in = s.getInputStream();
                            byte[] buffer = new byte[65536];
                            int count;
                            while ((count = in.read(buffer)) > 0) {
                                out.write(buffer, 0, count);
                            }
                        } catch (Exception ignored) {
                            // Test client went away.
                        }
                    }).start();
                } catch (Exception ignored) {
                    return;
                }
            }
        });
        thread.setDaemon(true);
        thread.start();
        return server;
    }

    private static byte[] roundtrip(int port, byte[] payload, String tag) throws Exception {
        try (Socket socket = new Socket("127.0.0.1", port)) {
            socket.setSoTimeout(15_000);
            DataInputStream in = new DataInputStream(socket.getInputStream());
            byte[] head = new byte[tag.length()];
            in.readFully(head);
            assertEquals(tag, new String(head, StandardCharsets.US_ASCII));
            Thread writer = new Thread(() -> {
                try {
                    socket.getOutputStream().write(payload);
                } catch (Exception ignored) {
                    // Reader reports the failure.
                }
            });
            writer.start();
            byte[] back = new byte[payload.length];
            in.readFully(back);
            writer.join();
            return back;
        }
    }

    @Test
    public void frameBytesMatchThePcBridge() {
        // Same bytes as tests/test_bluetooth.py::test_frame_bytes_match_the_android_bridge.
        byte[] hi = "hi".getBytes(StandardCharsets.US_ASCII);
        assertEquals("0200000007000000026869", hex(BluetoothBridge.encode(BluetoothBridge.DATA, 7, hi, 2)));
        assertEquals("030000000200000000", hex(BluetoothBridge.encode(BluetoothBridge.CLOSE, 2, null, 0)));
    }

    @Test
    public void streamsFlowBothWaysAndLinkLossClosesAll() throws Exception {
        ServerSocket pcServer = echo("PC:");
        ServerSocket phoneServer = echo("PHONE:");
        ServerSocket linkServer = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
        Socket pcLink = new Socket("127.0.0.1", linkServer.getLocalPort());
        Socket phoneLink = linkServer.accept();
        AtomicReference<BluetoothBridge> closed = new AtomicReference<>();

        BluetoothBridge pc = new BluetoothBridge(pcLink.getInputStream(), pcLink.getOutputStream(), pcLink,
                "pc-id", pcServer.getLocalPort(), true, null).start();
        BluetoothBridge phone = new BluetoothBridge(phoneLink.getInputStream(), phoneLink.getOutputStream(),
                phoneLink, "phone-id", phoneServer.getLocalPort(), false, closed::set).start();
        assertEquals("phone-id", pc.awaitHello(5_000));
        assertEquals("pc-id", phone.awaitHello(5_000));

        byte[] big = new byte[2 * 1024 * 1024];
        new Random(7).nextBytes(big);
        assertArrayEquals(big, roundtrip(pc.port(), big, "PHONE:"));      // PC app -> phone server
        byte[] text = "hej fra telefonen".getBytes(StandardCharsets.UTF_8);
        assertArrayEquals(text, roundtrip(phone.port(), text, "PC:"));    // phone app -> PC server
        assertEquals(2, pc.opened.get());
        assertEquals(2, phone.opened.get());

        pc.close(); // e.g. the PC walks out of range
        long deadline = System.currentTimeMillis() + 5_000;
        while (closed.get() == null && System.currentTimeMillis() < deadline) {
            Thread.sleep(50);
        }
        assertTrue(phone.isClosed());
        assertEquals(phone, closed.get());
        pcServer.close();
        phoneServer.close();
        linkServer.close();
    }

    @Test
    public void otherServicesAreRefused() throws Exception {
        ServerSocket linkServer = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
        Socket ours = new Socket("127.0.0.1", linkServer.getLocalPort());
        Socket theirs = linkServer.accept();
        byte[] wrong = "{\"magic\":\"something-else\"}".getBytes(StandardCharsets.UTF_8);
        theirs.getOutputStream().write(BluetoothBridge.encode(BluetoothBridge.HELLO, 0, wrong, wrong.length));
        BluetoothBridge bridge = new BluetoothBridge(ours.getInputStream(), ours.getOutputStream(), ours,
                "phone-id", 1, false, null).start();
        assertNull(bridge.awaitHello(5_000));
        assertTrue(bridge.isClosed());
        theirs.close();
        linkServer.close();
    }

    private static String hex(byte[] bytes) {
        StringBuilder builder = new StringBuilder();
        for (byte value : bytes) {
            builder.append(String.format("%02x", value));
        }
        return builder.toString();
    }
}
