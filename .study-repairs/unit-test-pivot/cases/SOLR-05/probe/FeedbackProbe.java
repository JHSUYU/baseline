package baseline.solr05;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.apache.zookeeper.KeeperException;

/** Exact I/O identity and selected-check events for the original cluster JUnit. */
public final class FeedbackProbe {
  private static final class Fault {
    final String operation;
    final String pathPart;
    final int ordinal;
    final boolean relative;
    final String afterFaultId;
    final int seedGlobalOrdinal;
    int seen;
    int globalSeen;
    boolean applied;

    Fault(String spec) {
      String[] parts = spec.split("\\|", -1);
      if (parts.length != 3 && parts.length != 5)
        throw new IllegalArgumentException("Invalid fault: " + spec);
      operation = parts[0];
      pathPart = parts[1];
      relative = parts[2].startsWith("@");
      ordinal = Integer.parseInt(relative ? parts[2].substring(1) : parts[2]);
      if (ordinal <= 0) throw new IllegalArgumentException("ordinal must be positive");
      if (relative != (parts.length == 5))
        throw new IllegalArgumentException("Relative fault needs phase anchor: " + spec);
      afterFaultId = relative ? parts[3].replaceFirst("^after=", "") : "";
      seedGlobalOrdinal = relative ? Integer.parseInt(parts[4].replaceFirst("^seed_global=", "")) : 0;
      if (relative && (!parts[3].startsWith("after=F") ||
          !parts[4].startsWith("seed_global=") || seedGlobalOrdinal <= 0))
        throw new IllegalArgumentException("Invalid relative fault anchor: " + spec);
    }
  }

  private static final List<Fault> FAULTS = parseFaults();
  private static final BufferedWriter TRACE = openTrace();
  private static long sequence;
  private static int nextFault;
  private static String lastAppliedFaultId = "<none>";

  private FeedbackProbe() {}

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr05.faults", "");
    if (!value.isEmpty()) for (String item : value.split(";")) faults.add(new Fault(item));
    return faults;
  }

  private static BufferedWriter openTrace() {
    String path = System.getProperty("solr05.trace", "");
    if (path.isEmpty()) return null;
    try { return new BufferedWriter(new FileWriter(path)); }
    catch (IOException error) { throw new ExceptionInInitializerError(error); }
  }

  private static void event(String kind, String payload) {
    long current = ++sequence;
    if (TRACE == null) return;
    try {
      TRACE.write(current + "\t" + System.nanoTime() + "\t" + kind + "\t" + payload + "\n");
      TRACE.flush();
    } catch (IOException error) { throw new IllegalStateException(error); }
  }

  private static String safe(String text) {
    return text == null ? "<null>" : text.replace('\t', '_').replace('\n', '_');
  }

  private static String stableCaller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String className = frame.getClassName();
      if (className.startsWith("org.apache.solr.") &&
          !className.equals("org.apache.solr.common.cloud.SolrZkClient")) {
        return className + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
      }
    }
    return "<external>";
  }

  public static synchronized void io(String operation, String path)
      throws KeeperException.ConnectionLossException {
    String identity = operation + "\t" + safe(path);
    String callsite = "caller=" + stableCaller();
    event("IO_OBSERVED", identity + "\t" + callsite);
    int activeFault = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (operation.equals(fault.operation) && path != null
          && path.equals(fault.pathPart)) {
        fault.globalSeen++;
        if (!fault.relative || index == activeFault) fault.seen++;
      }
    }
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (operation.equals(fault.operation) && path != null
          && path.equals(fault.pathPart) && fault.seen == fault.ordinal) {
        if (fault.relative && !fault.afterFaultId.equals(lastAppliedFaultId))
          throw new IllegalStateException("Fault phase anchor mismatch: " + fault.afterFaultId);
        fault.applied = true;
        String details = identity + "\tordinal="
            + (fault.relative ? "@" : "") + fault.ordinal
            + "\trelative_count=" + (fault.relative ? fault.seen : 0)
            + "\tglobal_hit_ordinal=" + fault.globalSeen
            + "\tseed_global=" + fault.seedGlobalOrdinal
            + "\tprevious_fault_id=" + lastAppliedFaultId
            + "\tfault_id=F" + nextFault
            + "\tplan_index=" + nextFault + "\t" + callsite;
        event("IO_MATCHED", details);
        event("IO_APPLIED_CONNECTION_LOSS", details);
        lastAppliedFaultId = "F" + nextFault;
        nextFault++;
        throw new KeeperException.ConnectionLossException();
      }
    }
  }

  public static synchronized void targetCheck(boolean missing, String collection,
                                                String shard, String coreNode) {
    String identity = safe(collection) + "\t" + safe(shard) + "\t" + safe(coreNode);
    event("TARGET_CHECK", (missing ? "missing" : "present") + "\t" + identity);
    if (missing) event("TARGET_EXCEPTION", identity);
  }
}
