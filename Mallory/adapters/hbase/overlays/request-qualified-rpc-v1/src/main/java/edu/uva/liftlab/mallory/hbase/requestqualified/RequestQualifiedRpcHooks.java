package edu.uva.liftlab.mallory.hbase.requestqualified;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Method;

/** One request-qualified, named-actor I/O exception door for the selected HBase case. */
public final class RequestQualifiedRpcHooks {
  private static final String CASE = System.getProperty("mallory.hbase.rpc.door.case", "");
  private static final String RPC_METHOD = rpcMethod(CASE);
  private static final String NODE = "HBASE-02".equals(CASE) ? "rs0" : "master0";
  private static final String SITE = RequestQualifiedRpcTransformer.BASE_SITE
      + ":rpc:" + RPC_METHOD;

  private RequestQualifiedRpcHooks() { }

  public static void beforeDispatch(Object rpcCall) {
    String site = selectedSiteFor(rpcCall, Probe.currentNode());
    if (site != null) Probe.beforeDoor(site, "java.io.IOException");
  }

  static String selectedSiteFor(Object rpcCall, String node) {
    if (RPC_METHOD == null || !NODE.equals(node)) return null;
    // The base HBase adapter has already entered the registered server and actual
    // transported request context. Unsupported method APIs fail closed.
    String observed = methodName(rpcCall);
    return RPC_METHOD.equals(observed) ? SITE : null;
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
