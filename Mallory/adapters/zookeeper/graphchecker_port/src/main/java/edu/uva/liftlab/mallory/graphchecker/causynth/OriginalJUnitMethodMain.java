package edu.uva.liftlab.mallory.graphchecker.causynth;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.PrintWriter;
import java.lang.reflect.Method;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** One unmodified JUnit Jupiter workload method in the instrumented MiniCluster. */
public final class OriginalJUnitMethodMain {
    private OriginalJUnitMethodMain() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: OriginalJUnitMethodMain "
                    + "<test-class> <test-method>");
        }
        Method selected = null;
        Class<?> testClass = Class.forName(args[0]);
        for (Method method : testClass.getDeclaredMethods()) {
            if (!args[1].equals(method.getName())) continue;
            if (selected != null) throw new IllegalArgumentException(
                    "ambiguous original JUnit method: " + args[0] + "#" + args[1]);
            selected = method;
        }
        if (selected == null) throw new IllegalArgumentException(
                "missing original JUnit method: " + args[0] + "#" + args[1]);
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectMethod(testClass, selected))
                .build();
        Launcher launcher = LauncherFactory.create();
        SummaryGeneratingListener listener = new SummaryGeneratingListener();
        launcher.registerTestExecutionListeners(listener);
        MessageDoors.startRecording();
        try {
            launcher.execute(request);
        } finally {
            MessageDoors.stopRecording();
        }
        TestExecutionSummary summary = listener.getSummary();
        summary.printFailuresTo(new PrintWriter(System.err, true));
        System.out.println("Original JUnit: tests=" + summary.getTestsSucceededCount()
                + " failures=" + summary.getTestsFailedCount()
                + " skipped=" + summary.getTestsSkippedCount());
        // A selected original @ParameterizedTest may expand into multiple
        // invocations. Every invocation must pass; the source is unchanged.
        if (summary.getTestsSucceededCount() < 1
                || summary.getTestsFailedCount() != 0
                || summary.getTestsSkippedCount() != 0) {
            System.exit(1);
        }
        // MiniCluster may leave non-daemon cleanup threads alive.  Surefire
        // ends its fork after the method; this standalone runner must too.
        System.exit(0);
    }
}
