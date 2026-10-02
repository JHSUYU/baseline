package org.greygraph.baseline.agent;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.util.concurrent.atomic.AtomicInteger;

/** Version-pinned HBase 2.4.8 transport adapter; graph semantics stay generic. */
public final class HBase248RpcHooks {
    private static final AtomicInteger FAILURES = new AtomicInteger();

    private HBase248RpcHooks() { }

    public static void requestSend(Object context, Object call) {
        try {
            Hook.messageSend("hbase-request:" + clientEndpoint(context) + ":"
                    + field(call, "id"));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("request send", error);
        }
    }

    public static void requestReceive(int id, Object connection) {
        try {
            Hook.messageReceive("hbase-request:" + serverEndpoint(connection)
                    + ":" + id);
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("request receive", error);
        }
    }

    public static void responseSend(Object call) {
        try {
            Object connection = field(call, "connection");
            Hook.messageSend("hbase-response:" + serverEndpoint(connection)
                    + ":" + field(call, "id"));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("response send", error);
        }
    }

    public static void responseReceive(int id, Object context) {
        try {
            Hook.messageReceive("hbase-response:" + clientEndpoint(context)
                    + ":" + id);
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("response receive", error);
        }
    }

    private static String clientEndpoint(Object context)
            throws ReflectiveOperationException {
        Object channel = call(context, "channel");
        SocketAddress address = (SocketAddress) call(channel, "localAddress");
        if (!(address instanceof InetSocketAddress)) {
            throw new IllegalArgumentException("unsupported client address " + address);
        }
        InetSocketAddress socket = (InetSocketAddress) address;
        return socket.getAddress().getHostAddress() + ":" + socket.getPort();
    }

    private static String serverEndpoint(Object connection)
            throws ReflectiveOperationException {
        return call(connection, "getHostAddress") + ":"
                + call(connection, "getRemotePort");
    }

    private static Object call(Object receiver, String name)
            throws ReflectiveOperationException {
        if (receiver == null) throw new IllegalArgumentException(name + " on null");
        Class<?> type = receiver.getClass();
        while (type != null) {
            try {
                Method method = type.getDeclaredMethod(name);
                method.setAccessible(true);
                return method.invoke(receiver);
            } catch (NoSuchMethodException absent) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchMethodException(name + " in " + receiver.getClass());
    }

    private static Object field(Object receiver, String name)
            throws ReflectiveOperationException {
        if (receiver == null) throw new IllegalArgumentException(name + " on null");
        Class<?> type = receiver.getClass();
        while (type != null) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(receiver);
            } catch (NoSuchFieldException absent) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name + " in " + receiver.getClass());
    }

    private static void report(String operation, Exception error) {
        int count = FAILURES.incrementAndGet();
        if (count <= 10) {
            System.err.println("adhoc-crashfuzz: HBase RPC " + operation
                    + " correlation failed: " + error);
        }
    }
}
