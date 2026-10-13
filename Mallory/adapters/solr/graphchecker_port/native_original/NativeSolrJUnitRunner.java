package edu.uva.liftlab.mallory.solr;

import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Opens an original GraphChecker recording window around one original JUnit 4 test. */
public final class NativeSolrJUnitRunner {
    private NativeSolrJUnitRunner() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected original JUnit class and method");
        }
        Class<?> clazz = Class.forName(args[0], true,
                Thread.currentThread().getContextClassLoader());
        String method = args[1];
        Object client = new Object();
        MessageDoors.registerNode(client, "EXTERNAL_APP", "CLIENT",
                clazz.getName() + "#" + method);
        int status = 1;
        MessageDoors.startRecording();
        long request = MessageDoors.beginRequest(client, method);
        try {
            Result result = new JUnitCore().run(Request.method(clazz, method));
            for (Failure failure : result.getFailures()) {
                System.err.println(failure.getTrace());
            }
            status = result.getRunCount() == 1 && result.getFailureCount() == 0
                    && result.getIgnoreCount() == 0 ? 0 : 1;
            System.out.println("NATIVE_SOLR_JUNIT_RESULT run=" + result.getRunCount()
                    + " failures=" + result.getFailureCount()
                    + " ignored=" + result.getIgnoreCount());
        } finally {
            MessageDoors.endRequest(request, method);
            MessageDoors.stopRecording();
        }
        // MiniSolrCloudCluster can retain non-daemon server threads after JUnit teardown.
        System.exit(status);
    }
}
