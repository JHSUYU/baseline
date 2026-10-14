package edu.uva.liftlab.graphchecker.causynth;

import edu.uva.liftlab.graphchecker.plan.CommunicationCatalogContract;
import edu.uva.liftlab.graphchecker.plan.LoopBoundPolicy;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class StaticProgramServiceLoopEvidenceTest {
    @Test
    public void indexedCandidatesMatchTheOriginalScanInRetainedOrder()
            throws Exception {
        List<Map<String, Object>> loops = new ArrayList<>();
        for (int header = 0; header < 100; header += 2) {
            loops.add(loop("M", header, header + 4,
                    LoopBoundPolicy.LOOP_FIXED_COUNT_INDEXED));
        }
        loops.add(loop("M", 110, 111,
                LoopBoundPolicy.LOOP_CONDITION_BOUNDED));
        loops.add(loop("M", 112, 115, "UNKNOWN"));
        loops.add(loop("D", 15, 20,
                LoopBoundPolicy.LOOP_FIXED_COUNT_INDEXED));
        Map<String, Object> malformed = loop("M", 120, 125,
                LoopBoundPolicy.LOOP_FIXED_COUNT_INDEXED);
        malformed.put(LoopBoundPolicy.RUNTIME_LOOP_ID, "M#loop:missing");
        loops.add(malformed);

        List<Map<String, Object>> ports = Arrays.asList(
                port("D", "Frame", 99),
                port("M", "Frame", 17),
                port("D", "M", 26),
                port("E", "M", 52),
                port("D", "D", 18));
        StaticProgram.RegionRow skeleton = skeleton(loops, ports);
        StaticProgram program = new StaticProgram();
        program.skeletons.put(skeleton.regionId, skeleton);
        List<Map<String, Object>> graph = new ArrayList<>();
        for (int unit = 0; unit < 100; unit++) {
            graph.add(edge("M", unit, "LOCAL", "local", ""));
        }
        graph.add(edge("M", 4, "CALL", "", "D"));
        graph.add(edge("M", 24, "CALL", "", "D"));
        graph.add(edge("M", 30, "HEAP_WRITE", "<A: int f>", ""));
        graph.add(edge("M", 35, "HEAP_WRITE", "local", ""));
        graph.add(edge("M", 52, "CALL", "", "E"));
        graph.add(edge("D", 18, "CALL", "", "D"));
        graph.add(edge("M", 70, "DYNAMIC_DISPATCH", "", ""));
        graph.get(graph.size() - 1).put("kind", "dispatch_activation");
        graph.get(graph.size() - 1).put("toCell", "D.activation");
        graph.add(graph.get(30));
        program.graph = graph;

        Map<String, List<Map<String, Object>>> expected =
                new LinkedHashMap<>();
        for (Map<String, Object> loop : loops) {
            String owner = MapFields.text(loop.get("enclosingMethod"));
            if (legacyCandidate(program, skeleton, loop, owner)) {
                expected.computeIfAbsent(owner,
                        ignored -> new ArrayList<>()).add(loop);
            }
        }
        Method serviceLoops = StaticProgram.class.getDeclaredMethod(
                "serviceLoops", StaticProgram.RegionRow.class);
        serviceLoops.setAccessible(true);
        @SuppressWarnings("unchecked")
        Map<String, List<Map<String, Object>>> actual =
                (Map<String, List<Map<String, Object>>>) serviceLoops.invoke(
                        program, skeleton);
        assertEquals(expected, actual);
        assertEquals(new ArrayList<>(expected.keySet()),
                new ArrayList<>(actual.keySet()));
        assertEquals(false, actual.get("M").contains(loops.get(26)));
        assertEquals(true, actual.get("M").contains(loops.get(8)));
        assertEquals(true, actual.get("M").contains(loops.get(15)));
        assertEquals(true, actual.get("M").contains(loops.get(35)));
    }

    /** The former per-loop edge scan is the reference for this index. */
    private static boolean legacyCandidate(StaticProgram program,
            StaticProgram.RegionRow skeleton, Map<String, Object> loop,
            String owner) {
        String classification = MapFields.text(loop.get(
                LoopBoundPolicy.LOOP_CLASSIFICATION));
        if (LoopBoundPolicy.LOOP_CONDITION_BOUNDED.equals(classification)) {
            return true;
        }
        if (!LoopBoundPolicy.LOOP_FIXED_COUNT_INDEXED.equals(classification)) {
            return false;
        }
        Set<String> calledInLoop = new LinkedHashSet<>();
        for (Map<String, Object> edge : program.regionGraphInMethod(
                skeleton.regionId, owner)) {
            if (!StaticProgram.loopContains(loop,
                    MapFields.number(edge.get("unitIndex"), -1))) continue;
            String callee = StaticProgram.invocationTarget(edge);
            if (!callee.isEmpty()) calledInLoop.add(callee);
            if ("HEAP_WRITE".equals(MapFields.text(edge.get("transferKind")))
                    && StaticProgram.declaredField(MapFields.text(
                            edge.get("toCell")))) return true;
        }
        for (Map<String, Object> port : skeleton.communicationPorts) {
            String definition = MapFields.text(port.get(
                    CommunicationCatalogContract.PORT_DEFINITION_METHOD));
            if (definition.isEmpty() || owner.equals(MapFields.text(port.get(
                    CommunicationCatalogContract.PORT_FRAME_METHOD)))) {
                continue;
            }
            if (calledInLoop.contains(definition)) return true;
            if (owner.equals(definition) && StaticProgram.loopContains(loop,
                    MapFields.number(port.get(CommunicationCatalogContract
                            .PORT_DEFINITION_UNIT_INDEX), -1))) return true;
        }
        return false;
    }

    private static StaticProgram.RegionRow skeleton(
            List<Map<String, Object>> loops,
            List<Map<String, Object>> ports) {
        Map<String, Object> row = row("schemaVersion",
                RuntimeSelectedRegionFinalizer.REGION_SCHEMA_VERSION,
                "kind", RuntimeSelectedRegionFinalizer.SKELETON_KIND,
                "regionId", "r", "rootMethod", "M", "anchorMethod", "M",
                "methods", Arrays.asList("M", "D"),
                RuntimeSelectedRegionFinalizer.RETAINED_LOOPS, loops,
                RuntimeSelectedRegionFinalizer.COMMUNICATION_PORTS, ports);
        return StaticProgram.regionRows(Collections.singletonList(row),
                RuntimeSelectedRegionFinalizer.SKELETON_KIND, "fixture")
                .get(0);
    }

    private static Map<String, Object> loop(String owner, int header, int end,
                                             String classification) {
        return row("enclosingMethod", owner,
                LoopBoundPolicy.RUNTIME_LOOP_ID, owner + "#loop:u" + header,
                LoopBoundPolicy.LOOP_LATCH_UNIT_INDEX, end,
                LoopBoundPolicy.LOOP_CONTROL_SITE_IDS,
                Collections.singletonList(owner + "#u" + end),
                LoopBoundPolicy.LOOP_CLASSIFICATION, classification);
    }

    private static Map<String, Object> port(String definition, String frame,
                                             int unit) {
        return row(CommunicationCatalogContract.PORT_DEFINITION_METHOD,
                definition, CommunicationCatalogContract.PORT_FRAME_METHOD,
                frame, CommunicationCatalogContract.PORT_DEFINITION_UNIT_INDEX,
                unit);
    }

    private static Map<String, Object> edge(String method, int unit,
            String transfer, String toCell, String invoke) {
        return row("method", method, "unitIndex", unit,
                "transferKind", transfer, "toCell", toCell,
                "invoke", invoke);
    }

    private static Map<String, Object> row(Object... fields) {
        Map<String, Object> row = new LinkedHashMap<>();
        for (int i = 0; i < fields.length; i += 2) {
            row.put((String) fields[i], fields[i + 1]);
        }
        return row;
    }
}
