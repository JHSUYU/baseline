package org.greygraph.baseline.agent;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicInteger;

/** Match workload HTTP request IDs with Solr's server-side call scope. */
public final class SolrHttpHooks {
    private static final AtomicInteger FAILURES = new AtomicInteger();

    private SolrHttpHooks() { }

    public static void requestReceive(Object call) {
        try {
            Object request = field(call, "req");
            Method getHeader = request.getClass().getMethod("getHeader", String.class);
            String correlation = (String) getHeader.invoke(request, "X-Adhoc-Request-ID");
            if (correlation != null && !correlation.isEmpty())
                Hook.messageReceive("solr-http:" + correlation);
        } catch (ReflectiveOperationException | RuntimeException error) {
            if (FAILURES.incrementAndGet() <= 10)
                System.err.println("adhoc-crashfuzz: Solr HTTP correlation failed: "
                        + error);
        }
    }

    private static Object field(Object receiver, String name)
            throws ReflectiveOperationException {
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
}
