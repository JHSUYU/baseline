package edu.uva.liftlab.graphchecker.runtime;

/** Minimal exercise of the original native row, branch, and root contracts. */
public final class NativeGraphCheckerSmoke {
    private static final String METHOD = "<edu.uva.liftlab.graphchecker.runtime.NativeGraphCheckerSmoke: void run()>";
    private static final String SITE = METHOD + "#u4";
    private static final String GROUP = "METHOD\nREGION.1\n" + METHOD;
    private static final String FIELD = "<edu.uva.liftlab.graphchecker.runtime.NativeGraphCheckerSmoke$Input: int value>";

    static final class Input { int value = 1; }

    public static void main(String[] args) {
        String opened = ConcolicRegionRuntime.openWorkloadSession();
        if (!opened.isEmpty()) throw new IllegalStateException(opened);
        Input input = new Input();
        RuntimeTraceContext.registerSource(input, new SourceRef("SYSTEM", "SERVER", "dn0", 0));
        RecordingWindow.open();
        long request = RuntimeTraceContext.beginRequest(input, "smoke");
        long frame = Identity.enterFrame(METHOD + "#u0", input);
        long entry = ConcolicRegionRuntime.enterRegionEntry("REGION.1", METHOD, input);
        long active = ConcolicRegionRuntime.enterRegionFrame(GROUP, METHOD, input, new Object[0]);
        try {
            if (active <= 0) throw new IllegalStateException("planned root was not admitted");
            ConcolicRegionRuntime.observeTrackedSite(SITE, FIELD, input);
            System.symbolizeField(input, "value", "smoke_value");
            long prepared = ConcolicRegionRuntime.prepareBranch(METHOD, 4, "value <= 0");
            long vmEvent = System.markConcolicBranch(SITE, 1);
            boolean outcome = input.value > 0;
            ConcolicRegionRuntime.resolveBranch(prepared, vmEvent, METHOD, 4, "value <= 0", !outcome);
            if (vmEvent <= 0) throw new IllegalStateException("native branch marker was not observed");
        } finally {
            ConcolicRegionRuntime.exitRegionFrame(GROUP, METHOD);
            ConcolicRegionRuntime.exitRegionEntry(entry);
            Identity.exitFrame(frame);
            RuntimeTraceContext.endRequest(request);
            RecordingWindow.close();
            String closed = ConcolicRegionRuntime.closeWorkloadSession();
            if (!closed.isEmpty()) throw new IllegalStateException(closed);
            RowRuntime.closeSession();
        }
    }
}
