package edu.uva.liftlab.mallory.hbase.requestqualified;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.ArrayDeque;
import java.lang.reflect.Method;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** One request-qualified, named-actor I/O exception door for the selected HBase case. */
public final class RequestQualifiedRpcHooks {
  private static final String CASE = System.getProperty("mallory.hbase.rpc.door.case", "");
  private static final String RPC_METHOD = rpcMethod(CASE);
  private static final Pattern REGION_SERVER = Pattern.compile("rs[0-9]+");
  private static final Pattern MASTER = Pattern.compile("master[0-9]+");
  private static final Pattern TRANSPORTED_TASK = Pattern.compile("^.+:task:([1-9][0-9]*)$");
  private static final String SITE = RequestQualifiedRpcTransformer.BASE_SITE
      + ":rpc:" + RPC_METHOD;
  private static final ThreadLocal<ArrayDeque<RegionFrame>> ACTIVE_REGIONS =
      ThreadLocal.withInitial(ArrayDeque::new);

  private static final class RegionFrame {
    String region;
    String node;
    int epoch;
    String context;
  }

  private RequestQualifiedRpcHooks() { }

  /** One frame for each actual RpcServer.call, including unselected calls. */
  public static void enterMethod() {
    ACTIVE_REGIONS.get().push(new RegionFrame());
  }

  public static void beforeDispatch(Object rpcCall) {
    String site = selectedSiteFor(rpcCall, Probe.currentNode(), Probe.captureContext());
    if (site == null) return;
    RegionFrame frame = ACTIVE_REGIONS.get().peek();
    if (frame == null || frame.region != null) return;
    // Scope the actual RPC handler for every selected method. A target region
    // entered during callBlockingMethod now inherits this exact server call
    // occurrence, while the existing finally still emits the real response.
    String region = site + ":region";
    frame.node = Probe.currentNode();
    frame.epoch = Probe.currentEpoch();
    frame.context = Probe.captureContext();
    Probe.regionEnter(region);
    frame.region = region;
    Probe.beforeDoor(site, "java.io.IOException");
  }

  /** Preserve HBase's close/finally; exit the selected region exactly once. */
  public static void closeServerScope(Object scope) {
    ArrayDeque<RegionFrame> frames = ACTIVE_REGIONS.get();
    RegionFrame frame = frames.peek();
    try {
      if (!(scope instanceof AutoCloseable))
        throw new IllegalStateException("RpcServer scope is not closeable");
      ((AutoCloseable) scope).close();
    } catch (Exception failure) {
      RequestQualifiedRpcHooks.<RuntimeException>throwUnchecked(failure);
    } finally {
      if (frame != null) {
        frames.pop();
        if (frame.region != null) {
          // The base close already emitted the response and restored its node
          // and context. Restore only for the paired REGION_EXIT event.
          try (Probe.NodeScope node = Probe.withNode(frame.node, frame.epoch);
               Probe.ContextScope context = Probe.withCausalContext(frame.context)) {
            Probe.regionExit(frame.region);
          }
        }
      }
      if (frames.isEmpty()) ACTIVE_REGIONS.remove();
    }
  }

  @SuppressWarnings("unchecked")
  private static <E extends Throwable> void throwUnchecked(Throwable failure) throws E {
    throw (E) failure;
  }

  static String selectedSiteFor(Object rpcCall, String node, String requestToken) {
    if (RPC_METHOD == null || !namedRoleMatches(CASE, node)) return null;
    // The base HBase adapter has already entered the registered server and actual
    // transported request context. Unsupported method APIs fail closed.
    String observed = methodName(rpcCall);
    if (!RPC_METHOD.equals(observed)) return null;
    if (!"HBASE-02".equals(CASE)) return SITE;
    if (requestToken == null) return null;
    Matcher token = TRANSPORTED_TASK.matcher(requestToken);
    // The client-created Call token is transported with this RPC. Its numeric
    // sequence distinguishes the selected Get from startup Gets while the
    // serving RegionServer can change between MiniCluster runs.
    return token.matches() ? SITE + ":request:" + token.group(1) : null;
  }

  private static boolean namedRoleMatches(String caseId, String node) {
    if (node == null) return false;
    if ("HBASE-02".equals(caseId)) return REGION_SERVER.matcher(node).matches();
    if ("HBASE-10".equals(caseId) || "HBASE-12".equals(caseId))
      return MASTER.matcher(node).matches();
    return false;
  }

  private static String rpcMethod(String caseId) {
    if ("HBASE-02".equals(caseId)) return "hbase.pb.ClientService.Get";
    if ("HBASE-10".equals(caseId) || "HBASE-12".equals(caseId))
      return "hbase.pb.MasterService.UnassignRegion";
    return null;
  }

  private static String methodName(Object rpcCall) {
    if (rpcCall == null) return null;
    try {
      Method getMethod = rpcCall.getClass().getMethod("getMethod");
      Object descriptor = getMethod.invoke(rpcCall);
      if (descriptor == null) return null;
      Method getFullName = descriptor.getClass().getMethod("getFullName");
      Object name = getFullName.invoke(descriptor);
      return name instanceof String ? (String) name : null;
    } catch (ReflectiveOperationException | RuntimeException failure) {
      return null;
    }
  }
}
