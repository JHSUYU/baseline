package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.annotation.Debug;
import org.junit.Test;

import java.io.IOException;

/** One unchanged JUnit test body run in a healthy and a faulted JVM. */
public final class FaultTrialWorkload {
    private static final String METHOD = "<edu.uva.liftlab.graphchecker.runtime.FaultTrialWorkload: void testDoorAndTarget()>";
    private static final String MARKER = "FAULT:FIXTURE:REQUEST";

    @Test
    public void testDoorAndTarget() throws IOException {
        // These calls stand for GraphChecker instrumentation and its door.
        MessageDoors.registerSource(this, "EXTERNAL_APP", "fixture", "node1", 0L);
        MessageDoors.startRecording();
        try {
            // Same static region, separate request contexts. Their marker
            // ordinals must be independent and their addresses must not match.
            runRequest("trial");
            runRequest("trial");
        } finally {
            MessageDoors.stopRecording();
        }
    }

    private void runRequest(String api) throws IOException {
        long request = CausynthTraceRecorder.beginSourceRequest(this, api);
        long frame = CausynthTraceRecorder.enterMethodFrame(METHOD, this);
        CausynthTraceRecorder.enterMethod(METHOD, this, "REGION.fixture");
        try {
            String occurrence = CausynthTraceRecorder.enclosingOccurrences()
                    .get(0);
            System.out.println("FIXTURE_OCCURRENCE=" + occurrence);
            for (int attempt = 0; attempt < 2; attempt++) {
                long call = CausynthTraceRecorder.beginCall(0L, METHOD, 7,
                        "<edu.uva.liftlab.graphchecker.annotation.Debug: boolean makeSymbolicBoolean(java.lang.String)>",
                        null);
                boolean fault;
                try {
                    fault = Debug.makeSymbolicBoolean(MARKER);
                } finally {
                    CausynthTraceRecorder.endCall(call, null, "");
                }
                if (fault) {
                    try {
                        throw new IOException("fixture door fault " + attempt);
                    } catch (IOException injected) {
                        // The system's retry path still reaches target.
                    }
                }
            }
            CausynthTraceRecorder.recordBranch(0L, METHOD, 22,
                    "target still reached", true);
            System.out.println("FIXTURE_TARGET_REACHED=true");
        } finally {
            CausynthTraceRecorder.exitActiveMethod(null, "");
            CausynthTraceRecorder.exitMethodFrame(frame);
            CausynthTraceRecorder.endSourceRequest(request, api);
        }
    }
}
