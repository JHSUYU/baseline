package baseline.solr01;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.apache.solr.client.solrj.SolrServerException;

/** Case-local observation at the original LISTALIASES HTTP callsite. */
public final class FeedbackProbe {
  private static final String OPERATION = "LISTALIASES_HTTP";
  private static final String RESOURCE = "/admin/collections?action=LISTALIASES";

  private static final class Fault {
    final String operation;
    final String resource;
    final int callOrdinal;
    final int attemptOrdinal;
    final String kind;
    Fault(String spec) {
      String[] fields = spec.split("\\|", -1);
      if (fields.length != 5) throw new IllegalArgumentException("Invalid fault: " + spec);
      operation = fields[0];
      resource = fields[1];
      callOrdinal = Integer.parseInt(fields[2]);
      attemptOrdinal = Integer.parseInt(fields[3]);
      kind = fields[4];
      if (!OPERATION.equals(operation) || !RESOURCE.equals(resource) ||
          callOrdinal <= 0 || attemptOrdinal <= 0 ||
          !(kind.equals("IO_EXCEPTION") || kind.equals("SOLR_SERVER_EXCEPTION")))
        throw new IllegalArgumentException("Invalid fault identity: " + spec);
    }
  }

  private static final class Call {
    final int ordinal;
    int ioOrdinal;
    int attempts;
    Call(int ordinal) { this.ordinal = ordinal; }
  }

  private static final List<Fault> FAULTS = parseFaults();
  private static final BufferedWriter TRACE = openTrace();
  private static final ThreadLocal<Call> CURRENT = new ThreadLocal<>();
  private static long sequence;
  private static int nextFault;
  private static int nextCall;
  private static int nextIoCall;

  private FeedbackProbe() {}

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr01.faults", "");
    if (!value.isEmpty()) for (String spec : value.split(";")) faults.add(new Fault(spec));
    return faults;
  }

  private static BufferedWriter openTrace() {
    String path = System.getProperty("solr01.trace", "");
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

  public static synchronized void begin(boolean forceFetch, String liveNodes) {
    Call call = new Call(++nextCall);
    CURRENT.set(call);
    event("TARGET_ENTER", "SOLR-01\tcall=" + call.ordinal + "\tforce=" + forceFetch
        + "\tlive_nodes=" + safe(liveNodes));
  }

  public static synchronized void io(String baseUrl) throws IOException, SolrServerException {
    Call call = CURRENT.get();
    if (call == null) throw new IllegalStateException("LISTALIASES outside getAliases");
    if (call.ioOrdinal == 0) call.ioOrdinal = ++nextIoCall;
    int attempt = ++call.attempts;
    String detail = OPERATION + "\t" + RESOURCE
        + "\tcaller=org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider#getAliases"
        + "\tcall=" + call.ioOrdinal + "\tattempt=" + attempt
        + "\tendpoint=" + safe(baseUrl);
    event("IO_OBSERVED", detail);
    if (nextFault >= FAULTS.size()) return;
    Fault fault = FAULTS.get(nextFault);
    if (!fault.operation.equals(OPERATION) || !fault.resource.equals(RESOURCE) ||
        fault.callOrdinal != call.ioOrdinal || fault.attemptOrdinal != attempt) return;
    String metadata = detail + "\tfault_id=F" + nextFault
        + "\tprevious_fault_id=" + (nextFault == 0 ? "<none>" : "F" + (nextFault - 1))
        + "\tplan_index=" + nextFault + "\tfault_kind=" + fault.kind;
    event("IO_MATCHED", metadata);
    event("IO_APPLIED", metadata);
    nextFault++;
    if (fault.kind.equals("SOLR_SERVER_EXCEPTION"))
      throw new SolrServerException("Injected LISTALIASES HTTP server failure");
    throw new IOException("Injected LISTALIASES HTTP I/O failure");
  }

  public static synchronized void targetCheck(boolean allFailed, String context) {
    Call call = CURRENT.get();
    event("TARGET_CHECK", (allFailed ? "missing" : "present") + "\tSOLR-01"
        + "\tcall=" + (call == null ? -1 : call.ioOrdinal)
        + "\tcontext=" + safe(context));
    if (allFailed) event("TARGET_EXCEPTION", "SOLR-01\tcall=" + (call == null ? -1 : call.ordinal));
  }
}
