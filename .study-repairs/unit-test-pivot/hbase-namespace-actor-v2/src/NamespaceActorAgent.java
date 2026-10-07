import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Base64;
import java.nio.charset.StandardCharsets;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hadoop.hbase.Abortable;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.MasterServices;
import org.apache.hadoop.hbase.regionserver.HRegionServer;
import org.apache.hadoop.hbase.zookeeper.ZKWatcher;
import org.apache.zookeeper.KeeperException;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Passive, actor-aware namespace probes for the original HBase 2.6.6 cluster tests. */
public final class NamespaceActorAgent {
  private static final Map<ZKWatcher, Abortable> OWNERS = new IdentityHashMap<>();
  private static final Map<ZKWatcher, Integer> MANAGERS = new IdentityHashMap<>();
  private static final Map<ZKWatcher, Map<String, Integer>> HITS = new IdentityHashMap<>();
  private static final String[] PLAN = System.getProperty("ns.actor.fault.plan", "").split(";");
  private static int nextManager;
  private static long nextEvent;
  private static int nextFault;
  private static volatile String boundActorRaw;
  private static volatile int boundManager;

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
      .with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKWatcher"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(WatcherConstructed.class).on(isConstructor())))
      .installOn(inst);
    new AgentBuilder.Default().with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.ZKNamespaceManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ManagerConstructed.class).on(isConstructor().and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default().with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ZkCreate.class).on(named("createWithParents").and(takesArguments(2))))
        .visit(Advice.to(ZkWrite.class).on(named("updateExistingNodeData").and(takesArguments(4))))
        .visit(Advice.to(ZkChildren.class).on(named("getChildDataAndWatchForNewChildren").and(takesArguments(2))))
        .visit(Advice.to(ZkData.class).on(named("getDataAndWatch").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default().with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(NamespaceLookup.class).on(named("getNamespace").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default().with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.namespace.NamespaceStateManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(RegionCount.class).on(named("checkAndUpdateNamespaceRegionCount").and(takesArguments(2))))
        .visit(Advice.to(TableCount.class).on(named("checkAndUpdateNamespaceTableCount").and(takesArguments(2)))))
      .installOn(inst);
  }

  private static synchronized void owner(ZKWatcher watcher, Abortable abortable) {
    OWNERS.put(watcher, abortable);
    System.err.println("NSACTOR WATCHER watcher=" + System.identityHashCode(watcher)
        + " owner_type=" + (abortable == null ? "null" : abortable.getClass().getName()));
  }

  private static synchronized void manager(Object manager, ZKWatcher watcher) {
    Integer id = MANAGERS.get(watcher);
    if (id == null) {
      id = ++nextManager;
      MANAGERS.put(watcher, id);
    }
    System.err.println("NSACTOR MANAGER manager=" + id + " object="
        + System.identityHashCode(manager) + " watcher=" + System.identityHashCode(watcher));
  }

  private static final class Actor {
    final String role;
    final String raw;
    final int manager;
    Actor(String role, String raw, int manager) {
      this.role = role;
      this.raw = raw;
      this.manager = manager;
    }
  }

  private static synchronized Actor actor(ZKWatcher watcher) {
    Abortable owner = OWNERS.get(watcher);
    Integer manager = MANAGERS.get(watcher);
    if (owner instanceof HMaster) {
      HMaster master = (HMaster) owner;
      ServerName name = master.getServerName();
      return new Actor(master.isActiveMaster() ? "ACTIVE_MASTER" : "STANDBY_MASTER",
          name == null ? "unassigned" : name.getServerName(), manager == null ? 0 : manager);
    }
    if (owner instanceof HRegionServer) {
      HRegionServer server = (HRegionServer) owner;
      ServerName name = server.getServerName();
      return new Actor("REGION_SERVER", name == null ? "unassigned" : name.getServerName(),
          manager == null ? 0 : manager);
    }
    return new Actor("UNKNOWN", "unassigned", manager == null ? 0 : manager);
  }

  private static String namespaceSite() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.ZKNamespaceManager"))
        return frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return null;
  }

  private static String encoded(String value) {
    return Base64.getUrlEncoder().withoutPadding()
        .encodeToString(value.getBytes(StandardCharsets.UTF_8));
  }

  private static synchronized long ioStart(String family, ZKWatcher watcher, String path)
      throws KeeperException {
    String site = namespaceSite();
    if (site == null) return 0;
    Actor actor = actor(watcher);
    Map<String, Integer> counts = HITS.get(watcher);
    if (counts == null) {
      counts = new HashMap<>();
      HITS.put(watcher, counts);
    }
    String point = family + "~" + path + "~" + site;
    int hit = counts.containsKey(point) ? counts.get(point) + 1 : 1;
    counts.put(point, hit);
    long event = ++nextEvent;
    String selector = actor.role + "~" + family + "~" + encoded(path) + "~" + site + "~" + hit;
    // role is a cross-run selector candidate; raw server and manager must be
    // equal between an injected event and the later selected target in a run.
    System.err.println("NSACTOR IO_ATTEMPT seq=" + event + " role=" + actor.role
        + " actor_raw=" + actor.raw + " manager=" + actor.manager
        + " watcher=" + System.identityHashCode(watcher) + " family=" + family
        + " path=" + path + " site=" + site + " ordinal=" + hit
        + " selector=" + selector);
    if (nextFault < PLAN.length && !PLAN[nextFault].isEmpty()) {
      String planned = PLAN[nextFault];
      int split = planned.lastIndexOf('~');
      if (split > 0 && selector.equals(planned.substring(0, split))
          && actor.role.equals("ACTIVE_MASTER") && actor.manager != 0
          && !actor.raw.equals("unassigned")
          && (boundActorRaw == null ||
              (boundActorRaw.equals(actor.raw) && boundManager == actor.manager))) {
        String kind = planned.substring(split + 1);
        KeeperException.Code code;
        if (kind.equals("CONNECTIONLOSS")) code = KeeperException.Code.CONNECTIONLOSS;
        else if (kind.equals("OPERATIONTIMEOUT")) code = KeeperException.Code.OPERATIONTIMEOUT;
        else if (kind.equals("SYSTEMERROR")) code = KeeperException.Code.SYSTEMERROR;
        else throw new IllegalArgumentException("Unsupported fault kind: " + kind);
        if (boundActorRaw == null) {
          boundActorRaw = actor.raw;
          boundManager = actor.manager;
        }
        ++nextFault;
        System.err.println("NSACTOR FAULT_APPLIED seq=" + event + " step=" + nextFault
            + " actor_raw=" + actor.raw + " manager=" + actor.manager
            + " selector=" + selector + " kind=" + kind);
        throw KeeperException.create(code, path);
      }
    }
    return event;
  }

  private static void ioEnd(long event, Throwable thrown) {
    if (event != 0) System.err.println("NSACTOR IO_END seq=" + event + " outcome="
        + (thrown == null ? "returned" : thrown.getClass().getName()));
  }

  private static synchronized String target(String point, MasterServices master, String subject) {
    ZKWatcher watcher = master.getZooKeeper();
    Actor actor = actor(watcher);
    String tag = "seq=" + (++nextEvent) + " point=" + point + " subject=" + subject
        + " role=" + actor.role
        + " actor_raw=" + actor.raw + " manager=" + actor.manager
        + " watcher=" + System.identityHashCode(watcher)
        + " bound_match=" + (boundActorRaw != null && boundActorRaw.equals(actor.raw)
            && boundManager == actor.manager);
    System.err.println("NSACTOR TARGET_ENTER " + tag);
    return tag;
  }

  private static void targetEnd(String tag, Throwable thrown) {
    String outcome = "normal";
    if (thrown != null) {
      String name = thrown.getClass().getName();
      String message = String.valueOf(thrown.getMessage());
      if (tag.contains("point=HBASE-08 ")
          && name.equals("org.apache.hadoop.hbase.NamespaceNotFoundException")) {
        outcome = "selected_namespace_not_found";
      } else if (tag.contains("point=HBASE-21 ")
          && name.equals("org.apache.hadoop.hbase.quotas.QuotaExceededException")
          && message.contains(" region count cannot be updated ")) {
        outcome = "selected_region_count_quota";
      } else if (tag.contains("point=HBASE-22 ")
          && name.equals("org.apache.hadoop.hbase.quotas.QuotaExceededException")
          && message.contains(" is not allowed to have ")
          && message.contains(" regions. The total number of regions permitted is only ")) {
        outcome = "selected_table_region_quota";
      } else {
        outcome = "other_exception";
      }
    }
    System.err.println("NSACTOR TARGET_EXIT " + tag + " exception="
        + (thrown == null ? "none" : thrown.getClass().getName())
        + " outcome=" + outcome);
  }

  public static final class WatcherConstructed {
    @Advice.OnMethodExit
    public static void exit(@Advice.This ZKWatcher watcher,
                            @Advice.Argument(2) Abortable abortable) {
      owner(watcher, abortable);
    }
  }
  public static final class ManagerConstructed {
    @Advice.OnMethodExit
    public static void exit(@Advice.This Object manager, @Advice.Argument(0) ZKWatcher watcher) {
      manager(manager, watcher);
    }
  }
  public static final class ZkCreate {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_CREATE", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class ZkWrite {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_WRITE", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class ZkChildren {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_CHILDREN_READ", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class ZkData {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_DATA_READ", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class NamespaceLookup {
    @Advice.OnMethodEnter
    public static String enter(@Advice.FieldValue("masterServices") MasterServices master,
                               @Advice.Argument(0) String name) {
      return target("HBASE-08", master, name);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter String tag, @Advice.Thrown Throwable thrown) {
      targetEnd(tag, thrown);
    }
  }
  public static final class RegionCount {
    @Advice.OnMethodEnter
    public static String enter(@Advice.FieldValue("master") MasterServices master,
                               @Advice.Argument(0) TableName table, @Advice.Argument(1) int regions) {
      return target("HBASE-21", master, table.getNameAsString() + ":" + regions);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter String tag, @Advice.Thrown Throwable thrown) {
      targetEnd(tag, thrown);
    }
  }
  public static final class TableCount {
    @Advice.OnMethodEnter
    public static String enter(@Advice.FieldValue("master") MasterServices master,
                               @Advice.Argument(0) TableName table, @Advice.Argument(1) int regions) {
      return target("HBASE-22", master, table.getNameAsString() + ":" + regions);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter String tag, @Advice.Thrown Throwable thrown) {
      targetEnd(tag, thrown);
    }
  }
}
