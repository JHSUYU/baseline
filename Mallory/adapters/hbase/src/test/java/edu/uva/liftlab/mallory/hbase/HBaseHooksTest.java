package edu.uva.liftlab.mallory.hbase;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertEquals;
import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.concurrent.Callable;
import org.junit.Test;

/** Cluster startup legitimately schedules scans before a logical actor is registered. */
public class HBaseHooksTest {
  @Test public void unboundScannerTaskDoesNotAbortClusterStartup() {
    Object future = new Object();
    HBaseHooks.scannerTaskSubmitted(future);
    try (HBaseHooks.Scope scope = HBaseHooks.enterScannerTask(future)) {
      assertNotNull(scope);
    }
  }

  @Test public void constructorPreflightUsesExplicitMasterEnvironment() {
    Object master = new Object();
    Probe.registerNode(master, "master0", 0);
    String previous = Probe.currentNode();
    try (HBaseHooks.Scope scope = HBaseHooks.enterMasterEnvironment(new Object(),
        new FakeMasterEnvironment(master))) {
      assertEquals("master0", Probe.currentNode());
    }
    assertEquals(previous, Probe.currentNode());
  }

  public static final class FakeMasterEnvironment {
    private final Object master;
    FakeMasterEnvironment(Object master) { this.master = master; }
    public Object getMasterServices() { return master; }
  }

  @Test public void miniClusterConstructorIndexBindsStartupActor() {
    String previous = Probe.currentNode();
    Object server = new Object();
    HBaseHooks.registerRegionServer(server, 2);
    try (HBaseHooks.Scope scope = HBaseHooks.enterMiniClusterActor(server)) {
      assertEquals("rs2", Probe.currentNode());
    }
    Object master = new Object();
    HBaseHooks.registerMaster(master, 1);
    try (HBaseHooks.Scope scope = HBaseHooks.enterMiniClusterActor(master)) {
      assertEquals("master1", Probe.currentNode());
    }
    assertEquals(previous, Probe.currentNode());
  }

  @Test public void procedureRolesUseExplicitNames() {
    String previous = Probe.currentNode();
    Object member = new Object();
    Object coordinator = new Object();
    HBaseHooks.registerZkMember(member, "one");
    HBaseHooks.registerZkCoordinator(coordinator, "controller");
    try (HBaseHooks.Scope scope = HBaseHooks.enterZkActor(member)) {
      assertEquals("zk-member:one", Probe.currentNode());
    }
    try (HBaseHooks.Scope scope = HBaseHooks.enterZkActor(coordinator)) {
      assertEquals("zk-coordinator:controller", Probe.currentNode());
    }
    assertEquals(previous, Probe.currentNode());
  }

  @Test public void procedureClaimsOneDistinctTokenPerSchedulerAttempt() {
    Object master = new Object();
    Object scheduler = new Object();
    Object procedure = new Object();
    Probe.registerNode(master, "master0", 0);
    FakeProcedureEnvironment environment = new FakeProcedureEnvironment(master, scheduler);
    HBaseHooks.registerProcedureScheduler(environment);
    FakeProcedureExecutor executor = new FakeProcedureExecutor(environment);
    String previousNode = Probe.currentNode();
    String previousContext = Probe.captureContext();

    HBaseHooks.procedureEnqueued(scheduler, procedure, false);
    HBaseHooks.procedurePolled(scheduler, procedure);
    String first;
    try (HBaseHooks.Scope scope = HBaseHooks.enterProcedure(executor, procedure)) {
      assertEquals("master0", Probe.currentNode());
      first = Probe.captureContext();
    }
    assertEquals(previousContext, Probe.captureContext());

    HBaseHooks.procedureEnqueued(scheduler, procedure, true);
    HBaseHooks.procedurePolled(scheduler, procedure);
    String second;
    try (HBaseHooks.Scope scope = HBaseHooks.enterProcedure(executor, procedure)) {
      second = Probe.captureContext();
    }
    org.junit.Assert.assertNotEquals(first, second);
    assertEquals(previousNode, Probe.currentNode());
    assertEquals(previousContext, Probe.captureContext());
  }

  public static final class FakeProcedureEnvironment {
    private final Object master;
    private final Object scheduler;
    FakeProcedureEnvironment(Object master, Object scheduler) {
      this.master = master;
      this.scheduler = scheduler;
    }
    public Object getMasterServices() { return master; }
    public Object getProcedureScheduler() { return scheduler; }
  }

  public static final class FakeProcedureExecutor {
    private final Object environment;
    FakeProcedureExecutor(Object environment) { this.environment = environment; }
    public Object getEnvironment() { return environment; }
  }

  public static final class FakeCoordinator {
    private final Object rpcs;
    FakeCoordinator(Object rpcs) { this.rpcs = rpcs; }
  }

  @Test public void coordinatorSubmissionsCarryDistinctExactTokensToWorkers() throws Exception {
    Object rpcs = new Object();
    Probe.registerNode(rpcs, "zk-coordinator:controller", 0);
    FakeCoordinator coordinator = new FakeCoordinator(rpcs);
    String previousNode = Probe.currentNode();
    String previousContext = Probe.captureContext();
    Callable<String> task = new Callable<String>() {
      @Override public String call() {
        assertEquals("zk-coordinator:controller", Probe.currentNode());
        return Probe.captureContext();
      }
    };
    Callable<?> first = HBaseHooks.coordinatorCallable(coordinator, task);
    Callable<?> second = HBaseHooks.coordinatorCallable(coordinator, task);
    assertNotNull(first);
    assertNotNull(second);
    String firstToken = (String) first.call();
    String secondToken = (String) second.call();
    org.junit.Assert.assertNotEquals(firstToken, secondToken);
    org.junit.Assert.assertNotEquals("root", firstToken);
    assertEquals(previousNode, Probe.currentNode());
    assertEquals(previousContext, Probe.captureContext());
  }
}
