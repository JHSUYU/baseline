package edu.uva.liftlab.graphchecker.runtime;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

/** The physical message leg remains exact; a later frame may influence a port. */
public final class RuntimeRegionPlannerSessionPortTest {
    private static final String CAPTURES =
            "observedCommunicationCaptures";
    private static final SourceRef CLIENT =
            new SourceRef("CLIENT", "client", "client", 0);
    private static final SourceRef SERVER =
            new SourceRef("SERVER", "server", "server", 1);

    @Test public void uniqueOrderedFramesCarrySessionInfluence() {
        Fixture f = new Fixture();
        f.bind();
        assertEquals("corr\n2\nREQUEST", f.boundIn.get("exchangeLeg"));
        assertEquals("corr\n1\nREQUEST", f.boundIn.get("sessionInfluenceLeg"));
        assertEquals("ORDERED_UNIQUE_MULTI_FRAME_V1",
                f.boundIn.get("sessionInfluenceKind"));
    }

    @Test public void exactFramePrecedesSessionFallback() {
        Fixture f = new Fixture();
        f.out.put("eventSeq", 35L);
        f.bind();
        assertEquals("corr\n2\nREQUEST", f.boundIn.get("exchangeLeg"));
        assertEquals("corr\n2\nREQUEST", f.boundOut.get("exchangeLeg"));
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    @Test public void differentCorrelationDoesNotCross() {
        Fixture f = new Fixture();
        f.send2 = f.event(40, "SEND", "other", "2", CLIENT,
                11, 0, "p2");
        f.receive2 = f.event(50, "RECEIVE", "other", "2", SERVER,
                22, 11, "p2");
        f.bind();
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    @Test public void differentPeerDoesNotCross() {
        Fixture f = new Fixture();
        SourceRef other = new SourceRef("SERVER", "server", "other", 1);
        f.receive2 = f.event(50, "RECEIVE", "corr", "2", other,
                22, 11, "p2");
        f.bind();
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    @Test public void ambiguousProducerDoesNotCross() {
        Fixture f = new Fixture();
        f.outCaptures.add(f.capture("OUT", 12));
        f.bind();
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    @Test public void overlappingFramesDoNotCross() {
        Fixture f = new Fixture();
        f.receive1 = f.event(45, "RECEIVE", "corr", "1", SERVER,
                22, 11, "p1");
        f.bind();
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    @Test public void unmatchedWireReceiptDoesNotCross() {
        Fixture f = new Fixture();
        f.receive1 = f.event(30, "RECEIVE", "corr", "1", SERVER,
                22, 11, "wrong-endpoint");
        f.bind();
        assertFalse(f.boundIn.containsKey("sessionInfluenceLeg"));
    }

    private static final class Fixture {
        private final Map<String, Object> out = capture("OUT", 10);
        private final Map<String, Object> in = capture("IN", 60);
        private final List<Map<String, Object>> outCaptures =
                new ArrayList<>(Arrays.asList(out));
        private Map<String, Object> boundIn;
        private Map<String, Object> boundOut;
        private RuntimeRegionPlanner.ProtocolEvent send1 = event(20, "SEND",
                "corr", "1", CLIENT, 11, 0, "p1");
        private RuntimeRegionPlanner.ProtocolEvent receive1 = event(30,
                "RECEIVE", "corr", "1", SERVER, 22, 11, "p1");
        private RuntimeRegionPlanner.ProtocolEvent send2 = event(40, "SEND",
                "corr", "2", CLIENT, 11, 0, "p2");
        private RuntimeRegionPlanner.ProtocolEvent receive2 = event(50,
                "RECEIVE", "corr", "2", SERVER, 22, 11, "p2");

        private void bind() {
            Map<String, Object> source = new LinkedHashMap<>();
            source.put("rootCallId", 1L);
            source.put("laneId", 11L);
            source.put(CAPTURES, outCaptures);
            Map<String, Object> target = new LinkedHashMap<>();
            target.put("rootCallId", 2L);
            target.put("laneId", 22L);
            target.put(CAPTURES, Arrays.asList(in));
            List<RuntimeRegionPlanner.ProtocolEvent> events = Arrays.asList(
                    send1, receive1, send2, receive2);
            Map<Long, List<RuntimeRegionPlanner.ProtocolEvent>> byRoot =
                    new HashMap<>();
            byRoot.put(1L, Arrays.asList(send1, send2));
            byRoot.put(2L, Arrays.asList(receive1, receive2));
            RuntimeRegionPlanner.bindObservedCommunicationCaptures(
                    Arrays.asList(source, target), byRoot, events);
            boundOut = firstCapture(source);
            boundIn = firstCapture(target);
        }

        @SuppressWarnings("unchecked")
        private static Map<String, Object> firstCapture(Map<String, Object> row) {
            return ((List<Map<String, Object>>) row.get(CAPTURES)).get(0);
        }

        private static Map<String, Object> capture(String side, long seq) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("side", side);
            row.put("portId", "port");
            row.put("eventSeq", seq);
            return row;
        }

        private static RuntimeRegionPlanner.ProtocolEvent event(long seq,
                String direction, String correlation, String attempt,
                SourceRef source, long lane, long remoteSpan, String endpoint) {
            return new RuntimeRegionPlanner.ProtocolEvent(seq, direction,
                    "WIRE", correlation, attempt, "REQUEST", "thread", 1L,
                    "method", seq, seq, "", lane, lane, remoteSpan, source,
                    "request", "api", endpoint, "endpoint/" + endpoint);
        }
    }
}
