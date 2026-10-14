package edu.uva.liftlab.graphchecker.runtime;

import static org.junit.Assert.assertEquals;

import edu.uva.liftlab.graphchecker.causynth.RuntimeSelectedRegionFinalizer;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

/** Locks the byte-level signature of all four recorded event families. */
public final class RuntimeRegionPlannerSignatureTest {
    @Test
    public void signaturePreservesRecordedOrderAndProtocolLegBytes()
            throws Exception {
        RuntimeRegionPlanner.MethodEvent method =
                new RuntimeRegionPlanner.MethodEvent(10L, "test", "thread",
                        1L, "<A: void é()>", 7, "A", 1L, 0L, 0L,
                        1L, 1L, 0L,
                        RuntimeRegionPlanner.UNREGISTERED_SOURCE, true,
                        "", "", "", false);
        RuntimeRegionPlanner.RuntimeEvent runtime =
                new RuntimeRegionPlanner.RuntimeEvent(13L, "BRANCH",
                        method.method, 1L, 0L, "s", "x", -1, "", 0,
                        "", true, 1, "IF", "");
        RuntimeRegionPlanner.FieldAccessEvent field =
                new RuntimeRegionPlanner.FieldAccessEvent(12L,
                        "FIELD_READ", method.method, 1L, -1, "f",
                        "<A: int f>", 7, 0, "42");
        RuntimeRegionPlanner.ProtocolEvent protocol =
                new RuntimeRegionPlanner.ProtocolEvent(11L, "RECEIVE",
                        "RPC", "corr", "a", "REQUEST", "thread", 1L,
                        method.method, 1L, 0L, "<RPC>", 1L, 1L, 0L,
                        RuntimeRegionPlanner.UNREGISTERED_SOURCE,
                        "", "", "", "");

        Class<?> indexType = Class.forName(RuntimeRegionPlanner.class.getName()
                + "$TraceIndex");
        Constructor<?> ctor = indexType.getDeclaredConstructor(
                Collection.class, Collection.class, Collection.class,
                Collection.class);
        ctor.setAccessible(true);
        Object index = ctor.newInstance(Collections.singletonList(method),
                Collections.singletonList(runtime),
                Collections.singletonList(field),
                Collections.singletonList(protocol));
        Map<String, Object> activation = new LinkedHashMap<>();
        activation.put("callIds", Collections.singletonList(1L));
        Method stamp = RuntimeRegionPlanner.class.getDeclaredMethod(
                "stampSignatures", Collection.class, indexType);
        stamp.setAccessible(true);
        stamp.invoke(null, Arrays.asList(activation), index);

        // SHA-256 first 16 bytes of the original GraphChecker event lines,
        // including the three-line protocol exchange leg and UTF-8 method.
        assertEquals("6582746aa698bfb17b60b8f40f08d10a",
                activation.get(RuntimeSelectedRegionFinalizer.SIGNATURE));
        assertEquals(10L,
                activation.get(RuntimeSelectedRegionFinalizer.FIRST_SEQ));
        assertEquals(13L,
                activation.get(RuntimeSelectedRegionFinalizer.LAST_SEQ));
    }
}
