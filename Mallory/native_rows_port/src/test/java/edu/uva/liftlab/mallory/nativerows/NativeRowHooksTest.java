package edu.uva.liftlab.mallory.nativerows;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.CausalContext;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.LocationKind;
import edu.uva.liftlab.graphchecker.contract.NodeId;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.Role;
import edu.uva.liftlab.graphchecker.contract.SessionReader;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;
import static org.junit.Assert.*;

public class NativeRowHooksTest {
    @Test public void publishesOriginalRowsWithExactStateVersionAndWirePair() throws Exception {
        Path iteration = Files.createTempDirectory("native-rows-")
                .resolve("iteration-0001");
        Path result = iteration.resolve("worker").resolve("result.json");
        NativeRowHooks hooks = NativeRowHooks.open(result);
        OccurrenceAddress address = OccurrenceAddress.of(
                NodeId.parse("test/node#epoch0"), "REGION.test",
                CausalContext.of(Role.CLIENT, "", 1),
                ExecutionIndex.parse("Worker.run()#u1@0"));
        hooks.activation(address.render(), "task-1", "main#1", true,
                true, null);
        JsonObject value = symbol("Y_I_7", "I");
        JsonObject predicate = symbol("M_Z_check", "Z");
        LocationId location = LocationId.of(LocationKind.INSTANCE, "17", "3");
        String writeSite = Endpoint.stateSite("Worker", "step", "()V", 10, true);
        String readSite = Endpoint.stateSite("Worker", "step", "()V", 12, false);
        hooks.write(address.render(), 10, writeSite, location, 4,
                value, "I", "Worker.run()#u1@0");
        try {
            hooks.write(address.render(), 10, writeSite, location, 5,
                    null, "I", "Worker.run()#u1@0");
            fail("a write without a captured expression must be refused");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("captured VM expression"));
        }
        hooks.read(address.render(), 11, readSite, location, 4,
                "M_I_read", "I", "7", "Worker.run()#u1@0");
        try {
            hooks.read(address.render(), 11, readSite, location, -1,
                    "M_I_read", "I", "7", "Worker.run()#u1@0");
            fail("a read without its observed version must be refused");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("exact location"));
        }
        hooks.decision(address.render(), 12, "Worker.step#u13", 1,
                false, predicate);
        hooks.target(address.render(), 13, "Worker.step#u20",
                predicate, true, false);
        Endpoint producer = Endpoint.of(address, "XCH.test.send",
                ExecutionIndex.parse("Worker.run()#u1@0"), 0);
        Endpoint consumer = Endpoint.of(address, "XCH.test.receive",
                ExecutionIndex.parse("Worker.run()#u2@0"), 0);
        hooks.export(producer, 14, value, "I", 42, "7");
        hooks.attach(consumer, producer, 15, "M_I_handoff", "I",
                "7", "rpc-1", "HANDLE");
        RowRuntime.closeSession();

        SessionReader session = SessionReader.read(iteration, hooks.sessionId());
        assertEquals("", session.incomplete());
        assertEquals(1, session.activations().size());
        assertEquals(1, session.decisions().size());
        assertEquals(1, session.writes().size());
        assertEquals(1, session.reads().size());
        assertEquals(4, session.reads().get(0).observedVersion());
        assertEquals(session.writes().get(0).location(), session.reads().get(0).location());
        assertEquals(1, session.targets().size());
        assertEquals(1, session.exports().size());
        assertEquals(1, session.attaches().size());
        assertEquals(session.exports().get(0).endpoint(),
                session.attaches().get(0).producer());
    }

    private static JsonObject symbol(String name, String type) {
        JsonObject value = new JsonObject();
        value.addProperty("_type", "SymbolExpression");
        value.addProperty("_java_type", type);
        value.addProperty("_exp", name);
        return value;
    }
}
