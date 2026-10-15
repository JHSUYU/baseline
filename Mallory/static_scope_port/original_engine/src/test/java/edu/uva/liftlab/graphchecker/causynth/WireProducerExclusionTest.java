package edu.uva.liftlab.graphchecker.causynth;

import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** A target on another node may still be the measured wire producer. */
public final class WireProducerExclusionTest {
    private static final String CONSUMER =
            "dn1#epoch1/region/REGION.target/ctx:Root:CLIENT/test#1/idx:";
    private static final String PRODUCER =
            "dn0#epoch1/region/REGION.target/ctx:Root:CLIENT/test#1/idx:";
    private static final String UNRELATED =
            "dn2#epoch1/region/REGION.target/ctx:Root:CLIENT/test#1/idx:";

    @Test public void excludedTargetCanBeARealWireProducer() throws Exception {
        Fixture f = new Fixture();
        assertTrue(f.cross("corr\n1\nREQUEST"));
        assertEquals("WIRE_SESSION_PRODUCER_V1", f.producer.get(
                "admissionBasis"));
        assertFalse(f.unrelated.containsKey("admissionBasis"));
        assertFalse(f.consumer.containsKey("admissionBasis"));
    }

    @Test public void excludedTargetWithoutMatchingPortStaysOut()
            throws Exception {
        Fixture f = new Fixture();
        assertFalse(f.cross("other\n1\nREQUEST"));
        assertFalse(f.producer.containsKey("admissionBasis"));
        assertFalse(f.unrelated.containsKey("admissionBasis"));
    }

    private static final class Fixture {
        private final StaticProgram program = new StaticProgram();
        private final Map<String, Object> consumer = new LinkedHashMap<>();
        private final Map<String, Object> producer = new LinkedHashMap<>();
        private final Map<String, Object> unrelated = new LinkedHashMap<>();
        private final Object walk;
        private final Method cross;

        private Fixture() throws Exception {
            producer.put("observedCommunicationCaptures", Collections
                    .singletonList(capture("port", "corr\n1\nREQUEST")));
            unrelated.put("observedCommunicationCaptures", Collections
                    .singletonList(capture("other-port", "corr\n1\nREQUEST")));
            program.activations.put(CONSUMER, consumer);
            program.activations.put(PRODUCER, producer);
            program.activations.put(UNRELATED, unrelated);
            Class<?> type = Class.forName(RuntimeSelectedRegionFinalizer.class
                    .getName() + "$DemandWalk");
            Class<?> demandIndex = Class.forName(
                    RuntimeSelectedRegionFinalizer.class.getName()
                            + "$RegionDemandIndex");
            Constructor<?> constructor = type.getDeclaredConstructor(
                    StaticProgram.class, demandIndex, StaticScopeMap.class,
                    Map.class, java.util.Set.class);
            constructor.setAccessible(true);
            walk = constructor.newInstance(program, null,
                    StaticScopeMap.empty(), Collections.emptyMap(),
                    new java.util.LinkedHashSet<>(Arrays.asList(
                            PRODUCER, UNRELATED)));
            cross = type.getDeclaredMethod("crossMessageOnLeg", String.class,
                    String.class, String.class, String.class, Consumer.class);
            cross.setAccessible(true);
        }

        private boolean cross(String leg) throws Exception {
            return (Boolean) cross.invoke(walk, CONSUMER, "port", leg,
                    "WIRE_SESSION_PRODUCER_V1", (Consumer<Object>) ignored -> {});
        }

        private Map<String, Object> capture(String port, String leg) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("side", "OUT");
            row.put("portId", port);
            row.put("exchangeLeg", leg);
            return row;
        }
    }
}
