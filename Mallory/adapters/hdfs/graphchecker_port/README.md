# HDFS GraphChecker protocol port for Mallory

This directory is the HDFS-specific piece of Mallory's GraphChecker-style
runtime. It patches **copies** of Hadoop 3.4.3 bytecode into an isolated
classpath overlay. It does not modify the Hadoop source checkout or the
original JUnit method. The focused original selector is
`org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDfsAdminDeleteBlockPool`.

`MalloryEmbeddedIpcBridge` calls Mallory's port of GraphChecker `MessageDoors`.
It registers each NameNode after creation and each DataNode before its block
pool actors start, then refreshes server aliases after `waitActive`. A
`MiniDFSCluster.restartDataNode` call carries the stopped DataNode's logical
ID into its replacement and advances its epoch. The real Hadoop IPC server
object is a source alias. The DataNode construction scope is captured when a
`BPServiceActor` thread starts and restored in its run method. An actor
started later without that construction scope gets a separate named root and
an explicit gap. The two
`DFSAdmin -deleteBlockPool` commands have independent client roots that retain
the `force` argument. Requests and responses pair by the actual Hadoop
`clientId`, `callId`, and `retryCount`. No edge is inferred from timing or a
socket address.

For QJM mini clusters, the same adapter registers all `MiniJournalCluster`
JournalNodes after successful startup and their underlying Hadoop IPC servers
as source aliases. `restartJournalNode(i)` advances `jn{i}` to a new epoch.
Every `IPCLoggerChannel` submission to its single-thread or parallel
`ListeningExecutorService` carries the submitting request scope into the
worker; the ordinary IPC hook then exports requests only after transport
handoff and attaches them at the exact JournalNode server. These are generic
QJM and IPC boundaries, independent of a target check or selected fault site.

The original Hadoop IPC path has two stages. `Client$Connection.sendRpcRequest`
offers a `Pair<Call,ResponseBuffer>` to a `SynchronousQueue`, then
`RpcRequestSender` dequeues the pair and calls `IpcStreams.sendRequest`.
The bridge captures caller scope before the offer, prepares a request only
after the sender dequeues the exact pair, and calls `MessageDoors.sent` only
after `sendRequest` returns. The server can install that context only after
the confirmed send, immediately before invoking the real `Server.call`.
For the response, the bridge prepares before `Responder.doRespond` and
confirms after that call returns. The waiting client installs the response
context only for a returned value or Hadoop `RemoteException`. Unmatched or
unconfirmed handoffs produce explicit gaps and no guessed edge.

## Build an isolated overlay

Build `Mallory/graphchecker-runtime` first, then run:

```bash
Mallory/adapters/hdfs/graphchecker_port/install.sh \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-common/3.4.3/hadoop-common-3.4.3.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-hdfs/3.4.3/hadoop-hdfs-3.4.3.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-hdfs/3.4.3/hadoop-hdfs-3.4.3-tests.jar \
  /tmp/mallory-hdfs-graph-overlay
```

The output path must not exist. `JAVASSIST_JAR`, `ASM_JAR`, and
`COMMONS_LANG_JAR` and `HADOOP_GUAVA_JAR` can override the script's
Maven-cache defaults. The
overlay contains patched Hadoop classes, the bridge, and a SHA-256 manifest.
Put the overlay **before** the original Hadoop jars/classes in the workload
JVM's classpath; otherwise the JVM will load unpatched classes. The selected
test is available in the released HDFS test jar and can be driven by a
single-method JUnit runner with the ordinary Hadoop 3.4.3 test classpath.

The bridge is for a `MiniDFSCluster` in one JVM. For distinct JVMs, the same
context must be carried in a versioned Hadoop IPC header, as GraphChecker's
Hadoop shim does. This overlay does not claim that case. It also does not
patch HDFS data transfer SASL, file I/O, or every asynchronous HDFS handoff;
those need separate HDFS protocol adapters before their target closure can
be considered complete.

## Check the unchanged JUnit and trace

After building the overlay and the Hadoop HDFS module test classes, run:

```bash
Mallory/adapters/hdfs/graphchecker_port/check_original_junit.sh \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /path/to/hadoop-3.4.3 \
  /tmp/mallory-hdfs-graph-trace.jsonl
```

This executes only the original `TestDeleteBlockPool#testDfsAdminDeleteBlockPool`
method. The focused checker confirms that its two admin commands generate
distinct roots and exact request/response handoffs through the DataNode. It
also rejects an unbalanced request scope or an ambiguous wire export. The
trace can contain explicit gaps for asynchronous startup IPC with no carried
source scope; these messages are left unjoined.

The restart identity check uses another unmodified Hadoop JUnit method:

```bash
Mallory/adapters/hdfs/graphchecker_port/check_restart_junit.sh \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /path/to/hadoop-3.4.3 \
  /tmp/mallory-hdfs-restart-trace.jsonl
```

For JournalNode registration, request/response identity, and restart epochs,
run two unmodified QJM JUnit methods with the same overlay:

```bash
Mallory/adapters/hdfs/graphchecker_port/check_qjm_junit.sh \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs-qjm-proof
```

The check requires every request and response `ATTACH` to have an earlier
`EXPORT` with the same transported Hadoop IPC correlation and attempt, and
requires all three JournalNode identities before and after restart. In the
focused 2026-10-13 run, both original methods passed. `testSingleWriter`
had 36 exact request attachments, 36 response attachments, and zero gaps;
`testSelectViaRpcAfterJNRestart` had 42 of each, including `jn0` through
`jn2` at both epoch 0 and epoch 1, and zero gaps. This is a protocol-only
healthy gate; a candidate check still needs its generated static scope,
weave, target reach, and fault trials.

For this workspace, `/path/to/hadoop-3.4.3` is
`/users/ZhenyuLi/.mallory-worktrees/hdfs`. Both scripts use the existing
compiled HDFS main and test classes and Maven's test dependency classpath.
For example, the verified install and check commands here are:

```bash
Mallory/adapters/hdfs/graphchecker_port/install.sh \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-common/3.4.3/hadoop-common-3.4.3.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-hdfs/3.4.3/hadoop-hdfs-3.4.3.jar \
  ~/.m2/repository/org/apache/hadoop/hadoop-hdfs/3.4.3/hadoop-hdfs-3.4.3-tests.jar \
  /tmp/mallory-hdfs-graph-overlay
Mallory/adapters/hdfs/graphchecker_port/check_original_junit.sh \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs-graph-trace.jsonl
Mallory/adapters/hdfs/graphchecker_port/check_restart_junit.sh \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs-restart-trace.jsonl
```

## Join the static scope and original JUnit weave

The static planner and offline weaver must inspect **identical application
bytes**. Build a disposable merged copy of the HDFS main, HDFS client, and
Hadoop common class directories, then overlay their patched protocol classes
before running the planner. The full static scope can select `DFSAdmin` or
Hadoop IPC classes for weaving; original woven copies earlier on the
classpath would otherwise hide their request and response hooks. The client
RPC translator also lives in HDFS client, outside the HDFS main module:

```bash
Mallory/adapters/hdfs/graphchecker_port/prepare_static_classes.sh \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs-graph-overlay \
  /tmp/mallory-hdfs32-merged-classes
```

For a smaller diagnostic boundary, set `MALLORY_HDFS_INCLUDE_COMMON_CLASSES=0`
when preparing the merged copy. This still weaves HDFS main and HDFS client,
including the client translator's typed `ServiceException` RPC door, while
Hadoop common remains on the dependency classpath and its patched IPC hooks
still carry exact request and response identity. It does **not** select
Hadoop common fault sites such as `ProtobufRpcEngine2$Invoker.invoke ->
Client.call`, `Client.call -> Connection.sendRpcRequest`, server dispatch,
or `Client$IpcStreams.readResponse`. A result from this boundary only covers
the HDFS application/client translator fault scope, not the full three-module
scope.

For a reusable protocol-layer boundary, set `MALLORY_HDFS_COMMON_SCOPE=ipc`.
This includes every physical `org.apache.hadoop.ipc.*` class from Hadoop
common alongside HDFS main and HDFS client. It therefore keeps the IPC
request, response, dispatch, and socket-facing doors selected by Soot, while
leaving generic Hadoop common code such as `Configuration$Parser` on the
dependency classpath. The boundary applies to all HDFS targets that use
Hadoop IPC; it is not a list of hand-picked sites for this JUnit. File I/O and
other Hadoop common fault sites remain outside its instrumented scope.

Select the HDFS-32 target branch at `DataNode.deleteBlockPool:3819`
and set `analysis.source_owner_classes` to match `DataNode`, whose instance
identity the adapter registers. The planner writes `weave_manifest.json` and
`static_scope_map.jsonl` together. Neither file lists hand-picked HDFS fault
sites.

After building `Mallory/instrumentation/graphchecker_port`, run:

```bash
Mallory/adapters/hdfs/graphchecker_port/check_scoped_junit.sh \
  /path/to/static-output/weave_manifest.json \
  /path/to/merged-hdfs-classes \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs32-scoped-run
```

Set `MALLORY_GC_WEAVE_JAR` to an immutable build when comparing trials, for
example `/dev/shm/mallory-graphchecker-weave-7a96c0fde65c.jar`. The script
copies that jar and the graph runtime jar into the run directory and records
their SHA-256 hashes. It uses the same runtime jar for graph feedback. Fault
trials reuse those exact bytes.
If graph reconstruction has a separately optimized analyzer build, set
`MALLORY_HDFS_GRAPH_JAR` to that immutable jar. The script copies and hashes it
independently, while the static/weave classpath continues to use the pinned
instrumentation runtime jar.
Set `MALLORY_HDFS_DEPENDENCY_CP_FILE` to the classpath file used by
`ScopePlanner` to force byte-for-byte identical Soot dependency resolution;
the script saves the effective classpath alongside the trace. Missing
dependencies can shift Jimple unit indices even when `DataNode.class` itself
is unchanged.
The full static scope can create a large trace. The script bounds graph
reconstruction to 12 GB heap and 300 seconds by default; override those
limits with `MALLORY_HDFS_GRAPH_HEAP` and
`MALLORY_HDFS_GRAPH_TIMEOUT_SEC` for a measured run. The unchanged JUnit has
a 600-second timeout and 4 GB heap by default; the corresponding overrides
are `MALLORY_HDFS_JUNIT_TIMEOUT_SEC` and `MALLORY_HDFS_JUNIT_HEAP`.

The script rejects any manifest other than the generated HDFS-32 branch
target. It copies only classes named by the manifest into a new weave input,
keeps the adapter overlay for the remaining HDFS and IPC hooks, runs the
unchanged JUnit selector, validates exact IPC handoffs, and writes the trace,
graph, feedback, class list, and logs under the new run directory. The
comparison of patched HDFS and IPC class bytes prevents silently combining
a scope computed from original bytecode with an overlaid runtime. A runtime
`TARGET_CHECK`, `COVERAGE`, or `FAULT_DOOR` row is a concrete observation;
the static scope map alone is a may-reach set.

When healthy feedback has an observed injectable door in the target closure,
the native one-fault replay selects the first such door from the trace whose
occurrence precedes the target in that closure. It matches the exact `siteId`,
logical node, occurrence ID, and ordinal. It
rewrites only the generated manifest's controller setting; it does not add a
per-case door. Run it with:

```bash
Mallory/adapters/hdfs/graphchecker_port/run_scoped_fault.sh \
  /tmp/mallory-hdfs32-scoped-run \
  /tmp/mallory-hdfs-graph-overlay \
  Mallory/graphchecker-runtime/target/mallory-graphchecker-runtime-1.0-SNAPSHOT.jar \
  /users/ZhenyuLi/.mallory-worktrees/hdfs \
  /tmp/mallory-hdfs32-fault-1
```

The fault run records `FAULT_APPLIED` in the same GraphChecker trace when
the exact door reappears. A trial with no exact match, or one that loses the
target on the injected causal path, is reported as such and cannot establish
a target failure. A later, unrelated invocation of the same target does not
rescue a target-losing trial: `trial-status.json` records both run-global
target reach and whether the injected occurrence belongs to the pre-target
closure. The JUnit exit status is saved separately from target-check and
injection evidence.

## Prepare another HDFS check from the inventory

`prepare_case.py` reads `Mallory/cases/inventory.json`. It uses the recorded
original JUnit selector, the fatal throw's class/method/line and exception,
and the recorded guard lines. It declares no I/O door. Start from a fresh
merged `MALLORY_HDFS_COMMON_SCOPE=ipc` byte tree and the exact ordered
classpath used by both Soot and WeaveMain:

```bash
python3 Mallory/adapters/hdfs/graphchecker_port/prepare_case.py \
  --inventory Mallory/cases/inventory.json --case-id HDFS-32 \
  scope-input --classes /path/to/merged-protocol-classes \
  --classpath-file /path/to/exact-classpath.txt \
  --out /path/to/new-case/scope-input.json

java -Xmx4g -cp "/path/to/static-scope-classes:/path/to/static-scope-dependencies" \
  edu.uva.liftlab.mallory.scope.ScopePlanner \
  /path/to/new-case/scope-input.json /path/to/new-case/scope

python3 Mallory/adapters/hdfs/graphchecker_port/prepare_case.py \
  --inventory Mallory/cases/inventory.json --case-id HDFS-32 \
  campaign-config --scope-output /path/to/new-case/scope \
  --classpath-file /path/to/exact-classpath.txt \
  --weaver-deps-file /path/to/weaver-dependency-classpath.txt \
  --weaver-jar /path/to/pinned-weaver.jar \
  --runtime-jar /path/to/pinned-runtime.jar \
  --graph-jar /path/to/pinned-graph-analyzer.jar \
  --test-classes /path/to/hadoop-hdfs/target/test-classes \
  --hadoop-root /path/to/hadoop-3.4.3 \
  --java /path/to/java-8/bin/java \
  --out /path/to/new-case/HDFS-32.json
```

The script targets the **throw** for Soot's backward walk, so Soot retains
all controlling branches. In HDFS-09, HDFS-26, HDFS-37, and HDFS-48 the
inventory records two guard lines; neither is silently discarded. After the
scan, the script checks that the manifest contains every recorded guard and
the unique typed throw. It records all check site IDs in the config and uses
the planner's first controlling guard as the current trial graph anchor.
The generated classpath preserves the pinned weaver dependencies ahead of
Hadoop's libraries, which is necessary for Soot's ASM version. A missing
JUnit selector, ambiguous throw, lost guard, or classpath mismatch fails
before fuzzing. Each new case must still pass an unchanged healthy JUnit run
and reach its target before a fault campaign is considered valid.

For the HDFS-32 protocol pilot, the resumable campaign root and a copy of its
exact inputs are under
`/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs32-protocol-v1`. The checkpoint
and trial receipts are durable there. If a node restart removes its
`/dev/shm` or `/tmp` exact-classpath inputs, run:

```bash
python3 Mallory/adapters/hdfs/graphchecker_port/restore_snapshot.py \
  /proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs32-protocol-v1
```

It restores only absent pinned inputs and refuses to overwrite changed ones.
Then rerun the same `graphchecker_fuzzer` command and config; its checkpoint
resumes the unfinished trial without repeating completed trials.
