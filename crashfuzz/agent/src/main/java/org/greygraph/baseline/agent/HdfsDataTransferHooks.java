package org.greygraph.baseline.agent;

import java.lang.reflect.Method;
import java.net.Socket;
import java.net.SocketAddress;
import java.util.concurrent.atomic.AtomicInteger;

/** Correlates the two ends of a HDFS data-transfer SASL connection. */
public final class HdfsDataTransferHooks {
    private static final AtomicInteger FAILURES = new AtomicInteger();

    private HdfsDataTransferHooks() { }

    public static void socketSend(Object socket) {
        emit("request", true, socketEndpoint(socket));
    }

    public static void peerSend(Object peer) {
        emit("request", true, peerEndpoint(peer, "getLocalAddressString"));
    }

    public static void serverReceive(Object peer) {
        emit("request", false, peerEndpoint(peer, "getRemoteAddressString"));
    }

    public static void serverResponse(Object peer) {
        emit("response", true, peerEndpoint(peer, "getRemoteAddressString"));
    }

    public static void socketResponse(Object socket) {
        emit("response", false, socketEndpoint(socket));
    }

    public static void peerResponse(Object peer) {
        emit("response", false, peerEndpoint(peer, "getLocalAddressString"));
    }

    private static String socketEndpoint(Object value) {
        if (!(value instanceof Socket)) return null;
        SocketAddress address = ((Socket) value).getLocalSocketAddress();
        return address == null ? null : address.toString();
    }

    private static String peerEndpoint(Object peer, String method) {
        if (peer == null) return null;
        try {
            Method getter = peer.getClass().getMethod(method);
            Object address = getter.invoke(peer);
            return address == null ? null : address.toString();
        } catch (ReflectiveOperationException | RuntimeException error) {
            report(error);
            return null;
        }
    }

    private static void emit(String direction, boolean send, String endpoint) {
        if (endpoint == null || endpoint.isEmpty()) return;
        // SocketAddress and Peer use the same client-side TCP endpoint. The
        // endpoint includes the ephemeral port, so concurrent transfers do
        // not collapse into one message producer.
        int slash = endpoint.lastIndexOf('/');
        String normalized = slash < 0 ? endpoint : endpoint.substring(slash + 1);
        String key = "hdfs-dt-" + direction + ":" + normalized;
        if (send) Hook.messageSend(key);
        else Hook.messageReceive(key);
    }

    private static void report(Exception error) {
        if (FAILURES.incrementAndGet() <= 10) {
            System.err.println("adhoc-crashfuzz: HDFS data-transfer correlation failed: "
                    + error);
        }
    }
}
