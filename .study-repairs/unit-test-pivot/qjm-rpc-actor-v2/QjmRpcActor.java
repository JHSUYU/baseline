import java.io.File;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Runtime port to JournalNode binding for the original MiniJournalCluster. */
public final class QjmRpcActor {
  private static final Pattern NODE = Pattern.compile("(?:^|[/\\\\])journalnode-(\\d+)(?:[/\\\\]|$)");
  private static final Map<Integer, String> PORTS = new HashMap<>();
  private static final Set<Integer> AMBIGUOUS = new HashSet<>();
  private static final ThreadLocal<String> TARGET = new ThreadLocal<>();

  private QjmRpcActor() { }

  static String actor(String storageRoot) {
    Matcher match = NODE.matcher(storageRoot == null ? "" : storageRoot);
    return match.find() ? "journalnode-" + match.group(1) : null;
  }

  public static synchronized void registerPort(int port, String storageRoot) {
    String actor = actor(storageRoot);
    if (port <= 0 || actor == null) return; // Unknown bindings never become selectors.
    if (AMBIGUOUS.contains(port)) return;
    String prior = PORTS.get(port);
    if (prior != null && !prior.equals(actor)) {
      PORTS.remove(port); // A conflicting/reused port is ambiguous for this process.
      AMBIGUOUS.add(port);
      return;
    }
    PORTS.put(port, actor);
  }

  public static synchronized String resolve(int port) {
    return PORTS.get(port);
  }

  public static void bindTarget(File storageRoot) {
    TARGET.set(storageRoot == null ? null : actor(storageRoot.getAbsolutePath()));
  }

  public static String targetActor() {
    return TARGET.get();
  }

  // Only the offline smoke uses this; every JUnit executes in a fresh JVM.
  static synchronized void resetForSmoke() {
    PORTS.clear();
    AMBIGUOUS.clear();
    TARGET.remove();
  }
}
