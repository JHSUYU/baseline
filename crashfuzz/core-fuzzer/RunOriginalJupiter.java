import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;
import java.lang.reflect.Method;

/** Run one unchanged JUnit Jupiter method with its native test fixture. */
public final class RunOriginalJupiter {
  public static void main(String[] args) {
    if (args.length != 2) throw new IllegalArgumentException("test class and method required");
    String parameterTypes = null;
    try {
      Class<?> testClass = Class.forName(args[0], false,
          Thread.currentThread().getContextClassLoader());
      for (Method candidate : testClass.getMethods()) {
        if (!candidate.getName().equals(args[1])) continue;
        if (parameterTypes != null)
          throw new IllegalArgumentException("ambiguous JUnit method: " + args[1]);
        StringBuilder signature = new StringBuilder();
        for (Class<?> parameter : candidate.getParameterTypes()) {
          if (signature.length() > 0) signature.append(',');
          signature.append(parameter.getTypeName());
        }
        parameterTypes = signature.toString();
      }
    } catch (ClassNotFoundException error) {
      throw new IllegalArgumentException("JUnit class not found: " + args[0], error);
    }
    if (parameterTypes == null)
      throw new IllegalArgumentException("JUnit method not found: " + args[1]);
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(LauncherDiscoveryRequestBuilder.request()
        .selectors(DiscoverySelectors.selectMethod(args[0], args[1], parameterTypes))
        .build());
    TestExecutionSummary summary = listener.getSummary();
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    System.out.println("JUnit original method: found=" + summary.getTestsFoundCount()
        + " succeeded=" + summary.getTestsSucceededCount()
        + " failed=" + summary.getTestsFailedCount());
    if (summary.getTestsFoundCount() < 1 || summary.getTestsFailedCount() != 0)
      System.exit(1);
    System.exit(0);
  }
}
