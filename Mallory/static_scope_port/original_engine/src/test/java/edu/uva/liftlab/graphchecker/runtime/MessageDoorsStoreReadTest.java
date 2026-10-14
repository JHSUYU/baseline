package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.io.BufferedWriter;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

/** A polling read observes a version without becoming a watch receipt. */
public class MessageDoorsStoreReadTest {
    @Test public void pollingReadRecordsExactVersionWithoutInboundContext()
            throws Exception {
        String key = "/store-read-test-" + System.nanoTime() + "@17";
        String missing = key + "-unfiled";
        String createWithLaterExists = key + "-create";
        Object node = new Object();
        MessageDoors.registerSource(node, "SOLR", "OVERSEER", "store-read-test", 0L);
        CausynthTraceRecorder.startRecording();
        long request = MessageDoors.beginRequest(node, "testStoreRead");
        try {
            MessageDoors.storedVersionedValue("ZOOKEEPER", key, node);
            MessageDoors.fetched("ZOOKEEPER", key, node);
            MessageDoors.fetched("ZOOKEEPER", missing, node);
            // A create adapter may learn a Stat only by a later exists call.
            // Its version is not a proved exact result of the create.
            MessageDoors.stored("ZOOKEEPER", createWithLaterExists, node);
            MessageDoors.fetched("ZOOKEEPER", createWithLaterExists, node);
        } finally {
            MessageDoors.endRequest(request, "testStoreRead");
            CausynthTraceRecorder.stopRecording();
        }
        // The streaming recorder normally flushes on JVM shutdown. Flush
        // under its own lock so this test can inspect the same raw trace.
        Field lockField = CausynthTraceRecorder.class.getDeclaredField("LOCK");
        Field writerField = CausynthTraceRecorder.class.getDeclaredField("traceWriter");
        lockField.setAccessible(true);
        writerField.setAccessible(true);
        synchronized (lockField.get(null)) {
            ((BufferedWriter) writerField.get(null)).flush();
        }
        String output = System.getenv("CAUSYNTH_TRACE_OUTPUT_DIR");
        Path trace = Paths.get(output == null || output.isEmpty()
                ? "target/causynth-trace" : output, "runtime_trace.jsonl");
        List<String> lines = Files.readAllLines(trace, StandardCharsets.UTF_8);
        int reads = 0;
        int receives = 0;
        for (String line : lines) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String event = row.get("event").getAsString();
            if ("EXCHANGE_RECEIVE".equals(event)) receives++;
            if (!"STORE_VERSION_READ".equals(event)) continue;
            reads++;
            assertEquals(key, row.get("correlationId").getAsString());
            assertEquals("ZOOKEEPER", row.get("transport").getAsString());
            assertFalse(row.get("producerEndpointId").getAsString().isEmpty());
        }
        assertEquals(1, reads);
        assertEquals(0, receives);
    }
}
