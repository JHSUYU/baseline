package research.solraliasv2;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import org.apache.solr.client.solrj.SolrServerException;
import org.apache.solr.client.solrj.SolrRequest;
import org.apache.solr.client.solrj.impl.CloudHttp2SolrClient;
import org.apache.solr.common.util.Utils;

/** Receiver and destination aware LISTALIASES fault recorder. */
public final class Probe {
  private static final String ACTOR = "CLIENT/CloudHttp2SolrClientTest.httpBasedCloudSolrClient";
  private static final String SITE = "BaseHttpClusterStateProvider.getAliases:247";
  private static final String RESOURCE = "/admin/collections?action=LISTALIASES";
  private static final Map<Object, Integer> CLIENTS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Integer>());
  private static final Map<String, String> NODES = new HashMap<>();
  private static final Map<String, String> ROLES = new HashMap<>();
  private static final Map<Object, Integer> IO_ORDINALS = new IdentityHashMap<>();
  private static final ThreadLocal<Call> CURRENT = new ThreadLocal<>();
  private static final Properties PLAN = new Properties();
  private static BufferedWriter output;
  private static long seq;
  private static int nextStep = 1;
  private static int steps;

  private static final class Call {
    final Object provider;
    final boolean force;
    int ordinal;
    int attempt;
    Call(Object provider, boolean force) { this.provider = provider; this.force = force; }
  }

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solr01v2.trace", "");
    if (trace.isEmpty()) throw new IllegalArgumentException("solr01v2.trace required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solr01v2.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) { PLAN.load(input); }
        steps = Integer.parseInt(PLAN.getProperty("count", "0"));
        if (steps < 1 || steps > 10) throw new IllegalArgumentException("fault count must be 1..10");
        for (int i = 1; i <= steps; i++) {
          for (String field : new String[]{"actorKey", "destinationKey", "siteId",
              "resource", "callOrdinal", "attemptOrdinal", "kind"}) {
            if (PLAN.getProperty("step." + i + "." + field) == null)
              throw new IllegalArgumentException("missing plan step " + i + " " + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solr01v2-trace-close"));
    } catch (IOException failure) { throw new IllegalStateException(failure); }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", 0, 0, false,
        "applied=" + (nextStep - 1) + "/" + steps);
    try { output.flush(); output.close(); }
    catch (IOException failure) { failure.printStackTrace(System.err); }
    output = null;
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder out = new StringBuilder("\"");
    for (char c : value.toCharArray()) {
      if (c == '"' || c == '\\') out.append('\\').append(c);
      else if (c == '\n') out.append("\\n");
      else if (c == '\r') out.append("\\r");
      else if (c == '\t') out.append("\\t");
      else if (c < 0x20) out.append(String.format("\\u%04x", (int)c));
      else out.append(c);
    }
    return out.append('"').toString();
  }

  private static synchronized void emit(String event, String actor, String destination,
                                        String site, String resource, int call, int attempt,
                                        boolean applied, String detail) {
    if (output == null) return;
    String row = "{\"event\":" + quote(event) + ",\"seq\":" + (++seq)
        + ",\"threadId\":" + Thread.currentThread().getId()
        + ",\"actorKey\":" + quote(actor)
        + ",\"destinationKey\":" + quote(destination)
        + ",\"siteId\":" + quote(site)
        + ",\"resource\":" + quote(resource)
        + ",\"callOrdinal\":" + call
        + ",\"attemptOrdinal\":" + attempt
        + ",\"applied\":" + applied + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  private static String slot(String home) {
    if (home == null) return null;
    String path = home.replace('\\', '/');
    String last = path.substring(path.lastIndexOf('/') + 1);
    return last.matches("node[1-3]") ? "JETTY/" + last : null;
  }

  public static synchronized void bindNode(String nodeName, String solrHome) {
    if (nodeName == null || solrHome == null) return;
    String role = slot(solrHome);
    if (role == null) {
      emit("NODE_UNBOUND", "", "", "JettySolrRunner.getNodeName", "", 0, 0,
          false, "nodeName=" + nodeName + ";solrHome=" + solrHome);
      return;
    }
    String previous = NODES.putIfAbsent(nodeName, role);
    String otherNode = ROLES.putIfAbsent(role, nodeName);
    if ((previous != null && !previous.equals(role)) ||
        (otherNode != null && !otherNode.equals(nodeName))) {
      NODES.put(nodeName, "AMBIGUOUS");
      ROLES.put(role, "AMBIGUOUS");
      emit("NODE_AMBIGUOUS", "", role, "JettySolrRunner.getNodeName", "", 0, 0,
          false, "nodeName=" + nodeName + ";solrHome=" + solrHome);
      return;
    }
    emit("NODE_BIND", "", role, "JettySolrRunner.getNodeName", "", 0, 0,
        false, "nodeName=" + nodeName + ";solrHome=" + solrHome);
  }

  public static synchronized void bindSelectedClient(CloudHttp2SolrClient client) {
    if (client == null || client.getClusterStateProvider() == null)
      throw new IllegalStateException("getRandomClient returned no state provider");
    Object provider = client.getClusterStateProvider();
    if (!provider.getClass().getName().equals(
        "org.apache.solr.client.solrj.impl.Http2ClusterStateProvider"))
      throw new IllegalStateException("getRandomClient returned non-HTTP provider");
    int clientId = System.identityHashCode(client);
    Integer previous = CLIENTS.putIfAbsent(provider, clientId);
    if (previous != null && previous != clientId)
      throw new IllegalStateException("HTTP provider mapped to multiple clients");
    emit("CLIENT_BIND", ACTOR, "", "CloudHttp2SolrClientTest.getRandomClient", "", 0, 0,
        false, "clientIdentity=" + clientId + ";providerIdentity="
            + System.identityHashCode(provider));
  }

  public static synchronized void requestEnter(Object client, SolrRequest<?> request,
                                                String collection) {
    Object provider = client instanceof CloudHttp2SolrClient
        ? ((CloudHttp2SolrClient) client).getClusterStateProvider() : null;
    String selected = provider != null && CLIENTS.get(provider) != null
        && CLIENTS.get(provider) == System.identityHashCode(client) ? ACTOR :
        "UNBOUND:REQUEST_RECEIVER";
    emit("REQUEST_ENTER", selected, "", "BaseCloudSolrClient.request", collection,
        0, 0, false, "clientIdentity=" + System.identityHashCode(client)
            + ";providerIdentity=" + (provider == null ? "" : System.identityHashCode(provider))
            + ";requestClass=" + (request == null ? "" : request.getClass().getName()));
  }

  private static String actor(Object provider) {
    return CLIENTS.containsKey(provider) ? ACTOR : "UNBOUND:HTTP_PROVIDER";
  }

  public static synchronized void begin(Object provider, boolean force, Set<?> liveNodes) {
    CURRENT.set(new Call(provider, force));
    emit("TARGET_ENTER", actor(provider), "", "BaseHttpClusterStateProvider.getAliases",
        RESOURCE, 0, 0, false, "providerIdentity=" + System.identityHashCode(provider)
            + ";force=" + force + ";liveNodes=" + liveNodes);
  }

  private static String destination(String nodeName, String baseUrl) {
    String role = NODES.get(nodeName);
    if (role == null || "AMBIGUOUS".equals(role) ||
        !nodeName.equals(ROLES.get(role))) return "UNBOUND:NODE";
    String scheme = baseUrl.startsWith("https:") ? "https" : "http";
    if (!Utils.getBaseUrlForNodeName(nodeName, scheme).equals(baseUrl))
      return "UNBOUND:ENDPOINT_MISMATCH";
    return role;
  }

  static synchronized String smokeDestination(String nodeName, String baseUrl) {
    return destination(nodeName, baseUrl);
  }

  private static boolean matches(String actor, String destination, Call call, String kind) {
    if (!ACTOR.equals(actor) || !destination.startsWith("JETTY/")) return false;
    int step = nextStep;
    if (step > steps) return false;
    String prefix = "step." + step + ".";
    return actor.equals(PLAN.getProperty(prefix + "actorKey"))
        && destination.equals(PLAN.getProperty(prefix + "destinationKey"))
        && SITE.equals(PLAN.getProperty(prefix + "siteId"))
        && RESOURCE.equals(PLAN.getProperty(prefix + "resource"))
        && Integer.toString(call.ordinal).equals(PLAN.getProperty(prefix + "callOrdinal"))
        && Integer.toString(call.attempt).equals(PLAN.getProperty(prefix + "attemptOrdinal"))
        && kind.equals(PLAN.getProperty(prefix + "kind"));
  }

  static boolean smokeMatch(String actor, String destination, String kind) {
    PLAN.setProperty("step.1.actorKey", ACTOR);
    PLAN.setProperty("step.1.destinationKey", "JETTY/node2");
    PLAN.setProperty("step.1.siteId", SITE);
    PLAN.setProperty("step.1.resource", RESOURCE);
    PLAN.setProperty("step.1.callOrdinal", "1");
    PLAN.setProperty("step.1.attemptOrdinal", "2");
    PLAN.setProperty("step.1.kind", "IO_EXCEPTION");
    steps = 1;
    nextStep = 1;
    Call call = new Call(new Object(), true);
    call.ordinal = 1;
    call.attempt = 2;
    return matches(actor, destination, call, kind);
  }

  public static synchronized void io(Object provider, String nodeName, String baseUrl)
      throws IOException, SolrServerException {
    Call call = CURRENT.get();
    if (call == null || call.provider != provider)
      throw new IllegalStateException("LISTALIASES has wrong provider or no target call");
    if (call.ordinal == 0) {
      int next = IO_ORDINALS.containsKey(provider) ? IO_ORDINALS.get(provider) + 1 : 1;
      IO_ORDINALS.put(provider, next);
      call.ordinal = next;
    }
    call.attempt++;
    String actor = actor(provider);
    String destination = destination(nodeName, baseUrl);
    String detail = "providerIdentity=" + System.identityHashCode(provider)
        + ";clientIdentity=" + CLIENTS.get(provider)
        + ";nodeName=" + nodeName + ";baseUrl=" + baseUrl
        + ";force=" + call.force;
    emit("IO_OBSERVED", actor, destination, SITE, RESOURCE, call.ordinal,
        call.attempt, false, detail);
    String kind = PLAN.getProperty("step." + nextStep + ".kind", "");
    if (!matches(actor, destination, call, kind)) return;
    int index = nextStep++;
    emit("IO_APPLIED", actor, destination, SITE, RESOURCE, call.ordinal,
        call.attempt, true, detail + ";planStep=" + index + ";kind=" + kind);
    if ("SOLR_SERVER_EXCEPTION".equals(kind))
      throw new SolrServerException("Injected actor-bound LISTALIASES failure");
    if ("IO_EXCEPTION".equals(kind))
      throw new IOException("Injected actor-bound LISTALIASES failure");
    throw new IllegalStateException("unknown planned fault kind " + kind);
  }

  public static synchronized void check(Object provider, boolean failed, String nodeName) {
    Call call = CURRENT.get();
    if (call == null || call.provider != provider)
      throw new IllegalStateException("getAliases check has wrong provider");
    emit("TARGET_CHECK", actor(provider), nodeName == null ? "" : NODES.get(nodeName),
        "BaseHttpClusterStateProvider.getAliases:267", RESOURCE,
        call.ordinal, call.attempt, false,
        "providerIdentity=" + System.identityHashCode(provider)
            + ";clientIdentity=" + CLIENTS.get(provider)
            + ";failed=" + failed + ";nodeName=" + nodeName);
    if (failed) emit("TARGET_THROW", actor(provider), "",
        "BaseHttpClusterStateProvider.getAliases:267", RESOURCE,
        call.ordinal, call.attempt, false, "expected_all_live_nodes_failed");
    CURRENT.remove();
  }
}
