package org.greygraph.baseline.agent;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** Correlate a ZooKeeper client's session/xid with server request processing. */
public final class ZooKeeperRpcHooks {
    private static final AtomicInteger FAILURES = new AtomicInteger();
    private static final Set<String> SENT = ConcurrentHashMap.newKeySet();

    private ZooKeeperRpcHooks() { }

    public static void requestSend(Object client, Object packet) {
        try {
            Object header = field(packet, "requestHeader");
            if (header == null) return; // connection and auth packets have no xid
            int xid = ((Number) call(header, "getXid")).intValue();
            if (xid < 0) return; // ping/auth are not workload requests
            long session = ((Number) call(client, "getSessionId")).longValue();
            if (session == 0) return;
            String correlation = key(session, xid);
            if (SENT.add(correlation)) Hook.messageSend(correlation);
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("send", error);
        }
    }

    public static void requestReceive(Object request) {
        try {
            int xid = ((Number) field(request, "cxid")).intValue();
            if (xid < 0) return;
            long session = ((Number) field(request, "sessionId")).longValue();
            if (session == 0) return;
            Hook.messageReceive(key(session, xid));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("receive", error);
        }
    }

    private static String key(long session, int xid) {
        return "zookeeper-request:" + Long.toHexString(session) + ":" + xid;
    }

    private static Object field(Object receiver, String name)
            throws ReflectiveOperationException {
        if (receiver == null) throw new IllegalArgumentException(name + " on null");
        Class<?> type = receiver.getClass();
        while (type != null) {
            try {
                Field slot = type.getDeclaredField(name);
                slot.setAccessible(true);
                return slot.get(receiver);
            } catch (NoSuchFieldException absent) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name + " in " + receiver.getClass());
    }

    private static Object call(Object receiver, String name)
            throws ReflectiveOperationException {
        Method method = receiver.getClass().getMethod(name);
        return method.invoke(receiver);
    }

    private static void report(String operation, Exception error) {
        if (FAILURES.incrementAndGet() <= 10)
            System.err.println("adhoc-crashfuzz: ZooKeeper RPC " + operation
                    + " correlation failed: " + error);
    }
}
