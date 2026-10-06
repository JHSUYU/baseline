package edu.uva.liftlab.graphchecker.runtime;

import java.io.File;
import java.lang.reflect.Method;

/** Check the stock GraphChecker trace reader accepts extra fault rows. */
public final class TraceParseSmoke {
    public static void main(String[] args) throws Exception {
        Method read = CausynthTraceRecorder.class.getDeclaredMethod(
                "readStateTrace", File.class, String.class);
        read.setAccessible(true);
        CausynthTraceRecorder.TraceData trace =
                (CausynthTraceRecorder.TraceData) read.invoke(null,
                        new File(args[0]), "FaultTrialWorkload#testDoorAndTarget");
        if (trace.methods.isEmpty() || trace.execution.isEmpty()) {
            throw new IllegalStateException("fault rows hid ordinary trace");
        }
        System.out.println("PASS trace parser: " + trace.methods.size()
                + " methods, " + trace.execution.size() + " execution rows");
    }
}
