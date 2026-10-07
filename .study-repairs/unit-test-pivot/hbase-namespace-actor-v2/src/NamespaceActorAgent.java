import java.lang.instrument.Instrumentation;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
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
  private static final Map<ZKWatcher, Object> MANAGER_OBJECTS = new IdentityHashMap<>();
  private static final Set<ZKWatcher> AMBIGUOUS_WATCHERS =
      Collections.newSetFromMap(new IdentityHashMap<ZKWatcher, Boolean>());
  private static final Map<ZKWatcher, Map<String, Integer>> HITS = new IdentityHashMap<>();
  private static final ThreadLocal<Deque<String>> TARGET_STACK = new ThreadLocal<Deque<String>>() {
    @Override protected Deque<String> initialValue() { return new ArrayDeque<>(); }
  };
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
        .visit(Advice.to(ZkData.class).on(named("getDataAndWatch").and(takesArguments(2))))
        .visit(Advice.to(ZkExists.class).on(named("watchAndCheckExists").and(takesArguments(2))))
        .visit(Advice.to(ZkDelete.class).on(named("deleteNode").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default().with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
      .type(named("org.apache.hadoop.hbase.master.TableNamespaceManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MaxRegionsOperand.class).on(named("getMaxRegions").and(takesArguments(1))))
        .visit(Advice.to(NamespaceGetOperand.class).on(named("get").and(takesArguments(1))
            .and(takesArgument(0, named("java.lang.String"))))))
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

  public static synchronized void owner(ZKWatcher watcher, Abortable abortable) {
    OWNERS.put(watcher, abortable);
    System.err.println("NSACTOR WATCHER watcher=" + System.identityHashCode(watcher)
        + " owner_type=" + (abortable == null ? "null" : abortable.getClass().getName()));
  }

  public static synchronized void manager(Object manager, ZKWatcher watcher) {
    Integer id = MANAGERS.get(watcher);
    Object old = MANAGER_OBJECTS.get(watcher);
    if (id == null || old != manager) {
      id = ++nextManager;
      MANAGERS.put(watcher, id);
      MANAGER_OBJECTS.put(watcher, manager);
      // The old instance could still issue I/O using this watcher. Without a
      // per-call instance tag, attribution would be ambiguous after rotation.
      if (old != null) AMBIGUOUS_WATCHERS.add(watcher);
    }
    System.err.println("NSACTOR MANAGER manager=" + id + " object="
        + System.identityHashCode(manager) + " watcher=" + System.identityHashCode(watcher)
        + " replaced=" + (old != null && old != manager)
        + " ambiguous=" + AMBIGUOUS_WATCHERS.contains(watcher));
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
    Integer manager = AMBIGUOUS_WATCHERS.contains(watcher) ? null : MANAGERS.get(watcher);
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

  /** Require one raw active Master across all observed watchers at injection time. */
  private static boolean uniqueActiveMaster(String raw) {
    String seen = null;
    for (Abortable owner : OWNERS.values()) {
      if (!(owner instanceof HMaster)) continue;
      HMaster master = (HMaster) owner;
      if (!master.isActiveMaster()) continue;
      ServerName name = master.getServerName();
      if (name == null) return false;
      String current = name.getServerName();
      if (seen != null && !seen.equals(current)) return false;
      seen = current;
    }
    return raw.equals(seen);
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

  public static synchronized long ioStart(String family, ZKWatcher watcher, String path)
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
      if (split > 0 && selector.equals(planned.substring(0, split))) {
        if (!actor.role.equals("ACTIVE_MASTER") || actor.manager == 0
            || actor.raw.equals("unassigned") || !uniqueActiveMaster(actor.raw)
            || (boundActorRaw != null &&
                (!boundActorRaw.equals(actor.raw) || boundManager != actor.manager))) {
          System.err.println("NSACTOR FAULT_REJECTED seq=" + event
              + " reason=actor_binding role=" + actor.role + " actor_raw=" + actor.raw
              + " manager=" + actor.manager + " bound_actor_raw=" + boundActorRaw
              + " bound_manager=" + boundManager);
          return event;
        }
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

  public static void ioEnd(long event, Throwable thrown) {
    if (event != 0) System.err.println("NSACTOR IO_END seq=" + event + " outcome="
        + (thrown == null ? "returned" : thrown.getClass().getName()));
  }

  public static synchronized String target(String point, MasterServices master, String subject) {
    ZKWatcher watcher = master.getZooKeeper();
    Actor actor = actor(watcher);
    String tag = "seq=" + (++nextEvent) + " point=" + point + " subject=" + subject
        + " role=" + actor.role
        + " actor_raw=" + actor.raw + " manager=" + actor.manager
        + " watcher=" + System.identityHashCode(watcher)
        + " bound_match=" + (boundActorRaw != null && boundActorRaw.equals(actor.raw)
            && boundManager == actor.manager);
    TARGET_STACK.get().push(tag);
    System.err.println("NSACTOR TARGET_ENTER " + tag);
    return tag;
  }

  /** Marks the exact predicate operand in its selected invocation. */
  public static synchronized void guardOperand(String source) {
    Deque<String> stack = TARGET_STACK.get();
    if (stack.isEmpty()) return;
    String tag = stack.peek();
    boolean lookup = tag.contains("point=HBASE-08 ") && source.equals("NAMESPACE_GET");
    boolean region = tag.contains("point=HBASE-21 ");
    boolean table = tag.contains("point=HBASE-22 ");
    if (!lookup && !(source.equals("MAX_REGIONS") && (region || table))) return;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if ((lookup && frame.getClassName().equals("org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl")
          && frame.getMethodName().equals("getNamespace") && frame.getLineNumber() == 115)
          || (region && frame.getClassName().equals("org.apache.hadoop.hbase.namespace.NamespaceStateManager")
          && frame.getMethodName().equals("checkAndUpdateNamespaceRegionCount")
          && frame.getLineNumber() == 128)
          || (table && frame.getClassName().equals("org.apache.hadoop.hbase.namespace.NamespaceStateManager")
          && frame.getMethodName().equals("checkAndUpdateNamespaceTableCount")
          && frame.getLineNumber() == 166)) {
        System.err.println("NSACTOR GUARD_OPERAND event_seq=" + (++nextEvent) + " " + tag + " site="
            + frame.getMethodName() + ":" + frame.getLineNumber());
        return;
      }
    }
  }

  public static void targetEnd(String tag, Throwable thrown) {
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
    Deque<String> stack = TARGET_STACK.get();
    if (!stack.isEmpty() && tag.equals(stack.peek())) stack.pop();
    else {
      System.err.println("NSACTOR TARGET_STACK_MISMATCH " + tag);
      stack.clear();
    }
    if (stack.isEmpty()) TARGET_STACK.remove();
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
  public static final class ZkExists {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_EXISTS", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class ZkDelete {
    @Advice.OnMethodEnter
    public static long enter(@Advice.Argument(0) ZKWatcher watcher, @Advice.Argument(1) String path)
        throws KeeperException {
      return ioStart("ZK_DELETE", watcher, path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter long event, @Advice.Thrown Throwable thrown) {
      ioEnd(event, thrown);
    }
  }
  public static final class MaxRegionsOperand {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      if (thrown == null) guardOperand("MAX_REGIONS");
    }
  }
  public static final class NamespaceGetOperand {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      if (thrown == null) guardOperand("NAMESPACE_GET");
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
