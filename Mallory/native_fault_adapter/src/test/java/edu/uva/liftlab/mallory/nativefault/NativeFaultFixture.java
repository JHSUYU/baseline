package edu.uva.liftlab.mallory.nativefault;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import edu.uva.liftlab.graphchecker.runtime.Identity;
import org.junit.Test;

import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Paths;

/** An unchanged JUnit workload after its selected sites are woven. */
public final class NativeFaultFixture {
    @Test public void selectedIo() throws Exception {
        Object actor = new Object();
        MessageDoors.registerNode(actor, "FIXTURE", "SERVER", "fixture-node");
        RowRuntime.configure(Paths.get(System.getProperty("fixture.result")));
        long tick = MessageDoors.beginTick(actor, "FIXTURE_IO");
        try {
            try {
                io();
                RowRuntime.exported(Identity.currentOccurrence("fixture-node#epoch0"),
                        2L, "fixture-export-port", 1L, 0,
                        new JsonObject(), "Ljava/lang/String;", "fixture-value");
                RowRuntime.attachedAt(RowRuntime.nextEndpoint(
                                Identity.currentOccurrence("fixture-node#epoch0"),
                                "fixture-attach-port", 0),
                        3L, "fixture-attach-port", 1L, "", "fixture-symbol",
                        "Ljava/lang/String;", "", true, "fixture-value");
                RowRuntime.target(Identity.currentOccurrence("fixture-node#epoch0"),
                        1L, "fixture-target-anchor", new JsonObject(), false, false, true);
            } catch (IOException failedIo) {
                target(failedIo);
            }
        } finally {
            MessageDoors.endTick(tick);
            RowRuntime.closeSession();
        }
    }

    private static void io() throws IOException {
        try (FileOutputStream stream = new FileOutputStream(
                System.getProperty("fixture.file"))) {
            stream.write(new byte[] {1, 2, 3});
        }
    }

    private static void target(IOException failedIo) throws IOException {
        RowRuntime.target(Identity.currentOccurrence("fixture-node#epoch0"),
                1L, "fixture-target-anchor", new JsonObject(), true, true, true);
        throw new IOException("target after injected I/O", failedIo);
    }
}
