# Mallory instrumentation

This module is an independent Java 8 agent for the Mallory ad hoc check baseline. It records selected bytecode sites during existing MiniCluster or cluster based JUnit tests. It does not depend on GraphChecker or the original Mallory code.

## Build and launch

```sh
cd Mallory/instrumentation
mvn test package
java -javaagent:/absolute/path/Mallory/instrumentation/target/mallory-agent.jar=config=/absolute/path/agent.properties \
     -cp '<system test classpath>' org.junit.runner.JUnitCore example.ClusterTest
```

The shaded agent jar contains ASM and Gson. Put **only the shaded agent jar** in `-javaagent`; do not put this module's unshaded `target/classes` ahead of it on the application classpath. The test driver can launch its own JUnit method instead of `JUnitCore`.

Example `agent.properties`:

```properties
run.id=HDFS-28-seed
events=/absolute/path/trial/events.jsonl
site.catalog=/absolute/path/trial/sites.jsonl
include=org.apache.hadoop.hdfs.,org.apache.hadoop.ipc.
site.file=/absolute/path/case/sites.json
fault.plan=/absolute/path/trial/plan.json
auto.io.doors=false
coverage.methods=true
coverage.branches=true
state.fields=false
state.maps=false
adapter.transformer=example.system.MiniClusterTransformer
adapter.jar=/absolute/path/system-adapter.jar
```

`MALLORY_RUN_ID`, `MALLORY_EVENT_FILE`, `MALLORY_SITE_CATALOG`, `MALLORY_SITE_FILE`, and `MALLORY_PLAN_FILE` override their matching properties. A healthy seed omits `fault.plan`. The event path is required. The agent opens it freshly for every JVM trial.

`include` limits transformed classes. A full class name is an **exact** match; a trailing `.` or `/` selects a package prefix, and a trailing `*` selects an explicit class-name prefix. With no `include`, only the classes named in `sites.json` are transformed. Add a related inner/helper class explicitly when its I/O matters; for example, `QuorumPeer,QuorumPeer$2` includes both but excludes `QuorumPeerConfig`. Broad field and branch tracing can produce very large traces.

`adapter.transformer` (or a comma-separated `adapter.transformers`) loads a no-argument `ClassFileTransformer`. `adapter.jar` (or CSV `adapter.jars`) appends separate adapter jars to the system class loader before that load; this works with Maven Surefire's fixed test classpath. The generic Mallory transformer runs first, and system adapters run afterward, so an adapter can insert its node-entry hook ahead of a generic region-entry probe. `MALLORY_ADAPTER_TRANSFORMERS` and `MALLORY_ADAPTER_JARS` override those properties. A system adapter jar can compile against the shaded agent jar's public `Probe` class and should bundle its own bytecode dependencies. Do not place the instrumentation module's unshaded `target/classes` on the target JVM classpath.

Example `sites.json`:

```json
{
  "targets": [{"class":"org.apache.hadoop.hdfs.server.datanode.DataNode", "method":"retrieveDataEncryptionKey", "line":1234}],
  "doors": [{"class":"org.apache.hadoop.hdfs.server.datanode.DataNode", "method":"retrieveDataEncryptionKey", "line":1220, "callee":"java.io.FileInputStream#read()I", "exception_class":"java.io.IOException"}],
  "regions": [{"class":"org.apache.hadoop.hdfs.server.datanode.DataNode", "method":"retrieveDataEncryptionKey"}],
  "nodeBindings": [{"class":"org.apache.zookeeper.server.quorum.QuorumPeer", "method":"loadDataBase", "field":"myid", "prefix":"zk"}],
  "async": [{"class":"example.Server", "method":"dispatch", "callee":"java.util.concurrent.ExecutorService#submit(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;"}]
}
```

The numbers and methods above illustrate the format; they are not a case configuration. `descriptor` can select an overloaded method using its JVM descriptor. `callee` selects the invoked method with its full JVM descriptor. To instrument both a guard and a `throw` on different lines, use two `targets` entries. A `targets` entry with `callee` observes an exception from that exact invocation, including calls such as `Preconditions.checkState`; for example `{"class":"example.Owner","method":"check","line":42,"callee":"com.google.common.base.Preconditions#checkState(Z)V","exception_class":"java.lang.IllegalStateException"}`. It rethrows the original exception object, preserving surrounding catch behavior. `regions` are method scopes; their selectors should omit `line`. `auto.io.doors=true` additionally enables a limited set of Java file/socket and Hadoop/HBase/Solr RPC callsites. Explicit `doors` provide the repeatable site set for a study.

`sites.jsonl` lists the **successfully woven sites in classes actually loaded in that JVM**. It includes `TARGET_THROW` sites even if the healthy run never throws. It is not a whole-program static analysis. Site IDs have the shape `dotted.Class#method(JVM_DESCRIPTOR)@line:branch:N`, `...@line:throw:N`, `...@line:callthrow:N`, or `...@line:door:N`. For `callthrow`, `N` counts all method invocations in bytecode order in that method, including constructor initialization calls. The selected region site is `dotted.Class#method(JVM_DESCRIPTOR)`.

`nodeBindings` reads a concrete numeric instance field at the selected method entry. It may instead use `"getter":"getServerId"` for a zero-argument numeric instance method. The selected field or getter must actually identify the node; the agent does not infer identity from thread names. For each distinct receiver and logical ID, it assigns an epoch starting at zero, retaining the same epoch for repeat calls on that receiver. An unreadable member produces `NODE_IDENTITY_GAP` and `node=unknown`. `async` wraps a selected single-argument `Runnable` or `Callable` submission and emits a paired `TASK_SUBMIT`/`TASK_CLAIM` token while preserving the explicitly bound node. Other scheduling APIs need a system adapter.

## Fault plan and event records

Example `plan.json` constructed from a healthy `DOOR_OBSERVED` event:

```json
{
  "schema_version": 1,
  "faults": [{
    "fault_id": "trial-4-fault-1",
    "point": {"site":"exact observed door site", "node":"dn1", "epoch":0, "hit":1},
    "fault_type":"EXCEPTION",
    "exception_class":"java.io.IOException"
  }]
}
```

The matcher uses every supplied `point` field: `site` is required; `node`, `epoch`, `occurrence`, `hit`, and `door_ordinal` are optional. A missing field is a wildcard. `door_ordinal` is a one-based count for the same logical node, epoch, and site in one trial. It supports replay when an RPC token changes between JVM runs: the controller can use `{site,node,epoch,door_ordinal}` and omit the unstable `occurrence`. Concurrent calls at the same site can still reorder, so `FAULT_MATCHED`/`FAULT_APPLIED` remain required evidence. Faults are one shot and are applied **before** the selected invocation. Supported `fault_type` values are `EXCEPTION`, `IO_EXCEPTION`, and `RUNTIME_EXCEPTION`. An explicit door rule may declare `exception_class`; the site catalog and `DOOR_OBSERVED` record it, and injection defaults to it. If neither the door nor plan specifies a class, injection defaults to `java.io.IOException`. A plan entry that never matches yields no `FAULT_APPLIED`. The controller should account for unmatched faults and retry or discard that trial explicitly.

Every JSONL event contains `type`, `id`, `seq`, `node`, `epoch`, `occurrence`, and `site`. The agent emits `COVERAGE_SUMMARY`, `TARGET_CHECK`, `TARGET_THROW`, `DOOR_OBSERVED`, `FAULT_MATCHED`, `FAULT_APPLIED`, `REGION_ENTER`, and `REGION_EXIT`. Branch outcomes include `TAKEN`, `FALLTHROUGH`, `CASE:<value>`, or `DEFAULT`. `TARGET_THROW` records the exception class at the selected `ATHROW` or selected callsite, not a generic failed JUnit result. A fault event is evidence of effective injection, not evidence that the target check failed.

The compact coverage agent records each method or branch coverage ID once per `(node, epoch, occurrence)`. At JVM exit it writes a `COVERAGE_DEF` for each unique ID, assigning a collision-free integer `coverage_ref`, then one `COVERAGE_SUMMARY` per occurrence with sorted integer `coverage_refs`. `TARGET_CHECK` is still emitted at every target branch visit. This avoids repeated coverage strings in long tests and keeps target-closure coverage: a branch first reached outside the closure can still appear in a later closure occurrence. The agent flushes before replacing an installed sink in tests. The versioned core loader resolves definitions before summaries, rejects undefined or conflicting references, and supports older summaries with string `coverage_ids` as well as individual `METHOD`/`BRANCH` events. Summary events appear after the runtime events they summarize, so their sequence number does not represent the execution order of each covered method or branch.

The optional field and Map probes emit `STATE_READ` and `STATE_WRITE` with per-JVM object ID, key, and a `version`. `version=-1` means no instrumented writer has been observed. These probes run just after the Java access, so concurrent access can occur between the operation and probe. Every such event carries `version_confidence:"sampled"`; graph construction must treat versions as candidate evidence, not an exact read-from relation.

`max.events` (default 1,000,000) and `max.bytes` (default 100 MiB) bound each trial's raw event file. At the first limit, the sink emits `TRACE_TRUNCATED` with the reason and stops writing. The controller must mark that trial incomplete and exclude it from target and coverage conclusions. The site catalog is separate from this limit.

Each site catalog row also carries `class_name`, `bytecode_sha256` of the original bytes delivered to this transformer, `instrumented_sha256` of its output, and `class_loader_id`. Compare `bytecode_sha256` with the expected target class from the case's exact compiled artifact before accepting a healthy seed. A later system adapter may further transform the class; its own output is outside `instrumented_sha256`. Multiple class loaders can each load the same target; the catalog retains separate rows and the controller should reject an ambiguous target binding.

## Logical nodes and causal handoffs

MiniCluster nodes often share one JVM. The agent cannot infer which logical node owns an arbitrary worker thread. A small system adapter must set node identity at known handlers:

```java
try (Probe.NodeScope ignored = Probe.withNode("dn1", epoch)) {
    // Existing handler body.
}
```

The adapter can propagate a request or task token using `Probe.taskSubmit(token, site)` and `try (Probe.ContextScope ignored = Probe.taskClaim(token, site)) { ... }`. For a synchronous completion consumed in an already active region, `Probe.taskObserve(token, site)` records `TASK_CLAIM` in that region without changing its context. For RPC handlers use `Probe.send(transport, correlation, port, site)` and `Probe.receiveScope(transport, correlation, port, site)` in a scoped handler. `Probe.receive(...)` records arrival without changing the thread's current context. The token must come from a real header, queue item, or another explicit handoff. No correlation is inferred from timestamps. Every independently selected region entry gets an occurrence identity under the current logical node, epoch, and causal context.

Adapters can register a concrete server object using `Probe.registerNode(receiver, node, epoch)` and enter its scope with `Probe.withRegisteredNode(receiver)`. `Probe.currentNode()` and `Probe.currentEpoch()` let an adapter preserve a source node already established by an outer handler. An unregistered receiver produces `NODE_IDENTITY_GAP` and an unknown node.
For an explicit queued task, `Probe.registerCurrentNode(task)` stores the current named node on the task object, and `Probe.newTaskToken()` makes a distinct token for `taskSubmit` and `taskClaim`. Registering a task from an unknown node is rejected.

`pilots/zookeeper11/run_healthy.py` runs an unchanged three-peer ZooKeeper JUnit with this agent and a receiver-field binding. Its output is explicitly a healthy instrumentation pilot, not one of the 102 completed Mallory campaigns.

The agent does not reconstruct GraphChecker's custom JVM expression DAG or exact memory versions. It also does not automatically patch the four systems' RPC headers or cover every exceptional callsite. A case is suitable for causal feedback only after its healthy seed reaches the exact selected target, its system adapter preserves node and handoff identity, and the trace records any missing relation as a gap. If the target exception arises only inside an uninstrumented library method, select the exact callsite in the caller with a `targets` rule containing `callee`, or add a system-specific hook where needed.
