package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class OperationHintTest {
    /** The recorder has static writer state, so exercise it in an isolated JVM. */
    public static final class Harness {
        public static void main(String[] args) {
            System.setProperty("mallory.graphchecker.trace.file", args[0]);
            Object owner = new Object();
            MessageDoors.registerSource(owner, "test", "client", "hint-client", 0);
            long request = MessageDoors.beginRequest(owner, "send");
            MessageDoors.FaultDoorHit hit;
            MessageDoors.Outbound outbound;
            try (MessageDoors.OperationScope ignored = MessageDoors.operationScope(
                    "POST", "/admin/cores?action=CREATE&secret=hidden", "CREATE")) {
                hit = MessageDoors.faultDoorHit("http-send", owner);
                outbound = MessageDoors.prepareOutbound("SOLR_HTTP", "hint-1", "1",
                        MessageDoors.REQUEST, owner, null);
            }
            // Fault and send callbacks may run after the lexical request scope.
            MessageDoors.faultApplied(hit, "java.io.IOException");
            MessageDoors.sent(outbound);
            MessageDoors.endRequest(request, "send");
            long nested = MessageDoors.beginRequest(owner, "nested");
            try (MessageDoors.OperationScope outer = MessageDoors.operationScope(
                    "GET", "/outer", "LIST")) {
                try (MessageDoors.OperationScope inner = MessageDoors.operationScope(
                        "POST\r\nX-Evil: yes", "//host/private?token=hidden", "bad action")) {
                    MessageDoors.faultDoorHit("inner", owner);
                }
                MessageDoors.faultDoorHit("outer", owner);
            }
            MessageDoors.faultDoorHit("plain", owner);
            MessageDoors.endRequest(nested, "nested");
            assertTrue(hit.occurrenceId.length() > 0);
            assertTrue(hit.replayOccurrenceId.length() > 0);
            assertEquals("hint-1", outbound.correlationId);
        }
    }

    @Test public void hintDecoratesFaultAndWireWithoutChangingIdentity() throws Exception {
        Path trace = Files.createTempFile("mallory-operation-hint-", ".jsonl");
        String java = Paths.get(System.getProperty("java.home"), "bin", "java").toString();
        String classpath = System.getProperty("surefire.test.class.path",
                System.getProperty("java.class.path"));
        Process process = new ProcessBuilder(java, "-cp", classpath,
                Harness.class.getName(), trace.toString()).redirectErrorStream(true).start();
        byte[] output = new byte[8192];
        int used = process.getInputStream().read(output);
        assertEquals(used < 0 ? "" : new String(output, 0, used, StandardCharsets.UTF_8),
                0, process.waitFor());
        List<String> lines = Files.readAllLines(trace, StandardCharsets.UTF_8);
        for (String kind : new String[] {"FAULT_DOOR", "FAULT_APPLIED",
                "WIRE_PREPARED", "EXPORT"}) {
            JsonObject row = lines.stream().filter(line -> line.contains("\"kind\":\""
                    + kind + "\"") && (line.contains("http-send") ||
                    line.contains("hint-1"))).map(line -> new JsonParser().parse(line)
                    .getAsJsonObject()).findFirst().get();
            assertEquals("POST", row.get("operationMethod").getAsString());
            assertEquals("/admin/cores", row.get("operationPath").getAsString());
            assertEquals("CREATE", row.get("operationAction").getAsString());
            assertFalse(row.toString().contains("secret"));
        }
        String inner = lines.stream().filter(line -> line.contains("\"siteId\":\"inner\"")).findFirst().get();
        String outer = lines.stream().filter(line -> line.contains("\"siteId\":\"outer\"")).findFirst().get();
        String plain = lines.stream().filter(line -> line.contains("\"siteId\":\"plain\"")).findFirst().get();
        assertFalse(inner.contains("operationMethod"));
        assertFalse(inner.contains("operationPath"));
        assertFalse(inner.contains("operationAction"));
        assertTrue(outer.contains("\"operationPath\":\"/outer\""));
        assertFalse(plain.contains("operationPath"));
    }
}
