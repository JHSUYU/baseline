package edu.uva.liftlab.mallory.solr.solr39;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;

/** Fail-closed, run-local identity gate immediately before AliasesManager's getData. */
public final class PreemptiveGate {
  public static final String SITE = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
      + "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1";
  public static final String RESOURCE = "/aliases.json";
  public static final String MARKER = "SOLR39_PREFAULT_RESOURCE_MANAGER";
  private static final IdentityHashMap<Object, Boolean> PUBLISHED = new IdentityHashMap<Object, Boolean>();
  private static final IdentityHashMap<Object, Boolean> READ = new IdentityHashMap<Object, Boolean>();
  private static final Map<String, Integer> OCCURRENCES = new HashMap<String, Integer>();
  private static final Map<String, Boolean> SUPPRESSED = new HashMap<String, Boolean>();

  private PreemptiveGate() { }

  /** Called only after the synchronized setIfNewer method returned true. */
  public static synchronized void published(boolean updated, Object manager) {
    if (updated && manager != null) PUBLISHED.put(manager, Boolean.TRUE);
  }

  /** Called at getAliases return; before injection this attests a prior consumer. */
  public static synchronized void read(Object value, Object manager) {
    if (value != null && manager != null) READ.put(manager, Boolean.TRUE);
  }

  private static boolean selected(String actor, int ordinal) {
    String selected = System.getenv("MALLORY_SOLR39_SELECTED_DOORS");
    if (selected == null || selected.isEmpty()) return false;
    String needle = actor + ":" + ordinal;
    for (String item : selected.split(",")) if (needle.equals(item)) return true;
    return false;
  }

  /**
   * This receives the *actual* getData operand, the Java receiver, and the two
   * Probe arguments. A selected door is passed to Probe only after resource,
   * actor, epoch, manager history and causal context are known. The core plan
   * then checks the exact site/actor/epoch/ordinal. Suppressing a failed
   * selection also suppresses later doors on that actor to avoid ordinal drift.
   */
  public static synchronized void beforeDoor(Object manager, String resource,
      String site, String exceptionClass) {
    String selection = System.getenv("MALLORY_SOLR39_SELECTED_DOORS");
    if (selection == null || selection.isEmpty()) return;
    String node = Probe.currentNode();
    int epoch = Probe.currentEpoch();
    String actor = node + "@" + epoch;
    int ordinal = OCCURRENCES.containsKey(actor) ? OCCURRENCES.get(actor) + 1 : 1;
    OCCURRENCES.put(actor, ordinal);
    if (Boolean.TRUE.equals(SUPPRESSED.get(actor))) return;
    if (selected(actor, ordinal)) {
      String context = Probe.captureContext();
      boolean ready = manager != null && SITE.equals(site) && RESOURCE.equals(resource)
          && node != null && !"unknown".equals(node) && epoch >= 0
          && context != null && !context.isEmpty()
          && Boolean.TRUE.equals(PUBLISHED.get(manager))
          && Boolean.TRUE.equals(READ.get(manager));
      if (!ready) {
        SUPPRESSED.put(actor, Boolean.TRUE);
        return;
      }
      // This observation has the core's exact run-local manager token,
      // occurrence, node, epoch, thread, and timestamp. Audit requires it to
      // precede the matched/applied pair on that same context.
      Probe.stateRead(manager, resource, MARKER);
    }
    Probe.beforeDoor(site, exceptionClass);
  }
}
