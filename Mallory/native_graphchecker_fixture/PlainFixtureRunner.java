package edu.uva.liftlab.graphchecker.runtime;

import org.junit.runner.JUnitCore;
import org.junit.runner.Result;

/** External session harness; the original JUnit source stays unchanged. */
public final class PlainFixtureRunner {
    public static void main(String[] args) {
        String opened = ConcolicRegionRuntime.openWorkloadSession();
        if (!opened.isEmpty()) throw new IllegalStateException(opened);
        Object source = new Object();
        RuntimeTraceContext.registerSource(source,
                new SourceRef("SYSTEM", "SERVER", "dn0", 0));
        RecordingWindow.open();
        long request = RuntimeTraceContext.beginRequest(source, "plain-junit");
        long frame = Identity.enterFrame("plain-junit", source);
        System.out.println("NATIVE_RUNNER_SOURCE " + Identity.currentOccurrence("dn0#epoch0"));
        try {
            Result result = JUnitCore.runClasses(PlainFixtureTest.class);
            if (result.getRunCount() != 1 || !result.wasSuccessful()) {
                throw new IllegalStateException("unchanged JUnit failed: "
                        + result.getFailures());
            }
        } finally {
            for (ConcolicTaskPlan.RefusedCandidate reason
                    : ConcolicTaskPlan.configuration().tasks.get(0).unaddressedReasons) {
                System.out.println("NATIVE_UNADDRESSED " + reason.render(
                        ConcolicTaskPlan.configuration().tasks.get(0)));
            }
            Identity.exitFrame(frame);
            RuntimeTraceContext.endRequest(request);
            RecordingWindow.close();
            String closed = ConcolicRegionRuntime.closeWorkloadSession();
            if (!closed.isEmpty()) throw new IllegalStateException(closed);
            RowRuntime.closeSession();
        }
    }
}
