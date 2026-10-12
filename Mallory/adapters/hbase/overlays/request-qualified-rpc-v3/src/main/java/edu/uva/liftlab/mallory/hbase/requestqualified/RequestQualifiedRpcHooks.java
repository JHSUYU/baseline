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
  private static final ThreadLocal<ArrayDeque<String>> ACTIVE_REGIONS =
      ThreadLocal.withInitial(ArrayDeque::new);

  private RequestQualifiedRpcHooks() { }

  public static void beforeDispatch(Object rpcCall) {
    String site = selectedSiteFor(rpcCall, Probe.currentNode(), Probe.captureContext());
    if (site == null) return;
    if ("HBASE-02".equals(CASE)) {
      // This region remains open through the actual response SEND emitted by
      // HBaseHooks.Scope.close. The overlay closes it at that SEND callsite.
      String region = site + ":region";
      Probe.regionEnter(region);
      ACTIVE_REGIONS.get().push(region);
      Probe.beforeDoor(site, "java.io.IOException");
    } else {
      Probe.beforeDoor(site, "java.io.IOException");
    }
  }

  /** Called after the real response SEND, before the server node scope closes. */
  public static void afterResponseSend() {
    ArrayDeque<String> regions = ACTIVE_REGIONS.get();
    if (regions.isEmpty()) return;
    Probe.regionExit(regions.pop());
    if (regions.isEmpty()) ACTIVE_REGIONS.remove();
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
