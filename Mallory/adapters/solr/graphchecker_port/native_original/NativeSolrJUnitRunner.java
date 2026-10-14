package edu.uva.liftlab.mallory.solr;

import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Opens an original GraphChecker recording window around one original JUnit 4 test. */
public final class NativeSolrJUnitRunner {
    private NativeSolrJUnitRunner() { }

    private static int expectedRuns(Class<?> clazz, String method) throws Exception {
        Method test = clazz.getMethod(method);
        for (Annotation annotation : test.getAnnotations()) {
            if (annotation.annotationType().getName().equals(
                    "com.carrotsearch.randomizedtesting.annotations.Repeat")) {
                Object iterations = annotation.annotationType().getMethod("iterations")
                        .invoke(annotation);
                if (!(iterations instanceof Integer) || (Integer) iterations < 1) {
                    throw new IllegalArgumentException("invalid original @Repeat iterations");
                }
                return (Integer) iterations;
            }
        }
        return 1;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected original JUnit class and method");
        }
        Class<?> clazz = Class.forName(args[0], true,
                Thread.currentThread().getContextClassLoader());
        String method = args[1];
        int expected = expectedRuns(clazz, method);
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
            status = result.getRunCount() == expected && result.getFailureCount() == 0
                    && result.getIgnoreCount() == 0 ? 0 : 1;
            System.out.println("NATIVE_SOLR_JUNIT_RESULT run=" + result.getRunCount()
                    + " failures=" + result.getFailureCount()
                    + " ignored=" + result.getIgnoreCount()
                    + " expected=" + expected);
        } finally {
            MessageDoors.endRequest(request, method);
            MessageDoors.stopRecording();
        }
        // MiniSolrCloudCluster can retain non-daemon server threads after JUnit teardown.
        System.exit(status);
    }
}
