package org.greygraph.baseline.agent;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicInteger;

/** Correlates Hadoop IPC calls using the wire client ID and call ID. */
public final class HadoopRpcHooks {
    private static final AtomicInteger FAILURES = new AtomicInteger();

    private HadoopRpcHooks() { }

    public static void requestSend(Object connection, Object call) {
        try {
            Object client = field(connection, "this$0");
            Hook.messageSend("hadoop-rpc-request:" + key(
                    (byte[]) field(client, "clientId"),
                    (Integer) field(call, "id")));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("request send", error);
        }
    }

    public static void requestReceive(Object header) {
        try {
            byte[] clientId = (byte[]) call(call(header, "getClientId"),
                    "toByteArray");
            int callId = (Integer) call(header, "getCallId");
            Hook.messageReceive("hadoop-rpc-request:" + key(clientId, callId));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("request receive", error);
        }
    }

    public static void responseSend(Object call) {
        try {
            Hook.messageSend("hadoop-rpc-response:" + key(
                    (byte[]) field(call, "clientId"),
                    (Integer) field(call, "callId")));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("response send", error);
        }
    }

    public static void responseReceive(int callId, Object connection) {
        try {
            Object client = field(connection, "this$0");
            Hook.messageReceive("hadoop-rpc-response:" + key(
                    (byte[]) field(client, "clientId"), callId));
        } catch (ReflectiveOperationException | RuntimeException error) {
            report("response receive", error);
        }
    }

    private static String key(byte[] clientId, int callId) {
        StringBuilder result = new StringBuilder(clientId.length * 2 + 12);
        final char[] digits = "0123456789abcdef".toCharArray();
        for (byte value : clientId) {
            result.append(digits[(value >> 4) & 15]);
            result.append(digits[value & 15]);
        }
        return result.append(':').append(callId).toString();
    }

    private static Object call(Object receiver, String name)
            throws ReflectiveOperationException {
        Method method = receiver.getClass().getMethod(name);
        return method.invoke(receiver);
    }

    private static Object field(Object receiver, String name)
            throws ReflectiveOperationException {
        Class<?> type = receiver.getClass();
        while (type != null) {
            try {
                Field found = type.getDeclaredField(name);
                found.setAccessible(true);
                return found.get(receiver);
            } catch (NoSuchFieldException absent) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name + " in " + receiver.getClass());
    }

    private static void report(String operation, Exception error) {
        if (FAILURES.incrementAndGet() <= 10) {
            System.err.println("adhoc-crashfuzz: Hadoop RPC " + operation
                    + " correlation failed: " + error);
        }
    }
}
