# ZooKeeper causal protocol adapter for the Mallory baseline

This adapter is a **port inside `Mallory/`**, based on the ZooKeeper unit-test
branch of GraphChecker (`cf74a2e1d`, `66d9ff8ae`, `4d87a7c24`). It depends on
the Mallory-owned `mallory-graphchecker-runtime` module, not on a GraphChecker
checkout at run time. The original workload remains the cluster JUnit test.

## What is implemented

- `ZooKeeperWeave` inserts checked Soot hooks into the ZooKeeper 3.8.7
  production classes. It registers peer lifecycles and actor aliases; opens
  bounded peer, follower, learner-handler and `registerWithLeader` turns; and
  observes LEADERINFO and ACKEPOCH at their actual quorum socket operations.
  Every required anchor must match exactly once or the weave fails.
- `ZooKeeperTraceBridge` uses GraphChecker's `MessageDoors` causal context.
  A send reserves a directional socket FIFO identity before the write so a
  concurrently scheduled receiver can wait for it. A `SEND` is published only
  after a successful flush: LEADERINFO after `LearnerHandler` flushes, ACKEPOCH
  after `Learner.writePacketNow` returns normally with `flush=true`. The read
  must match the same connection, packet type, zxid and, for ACKEPOCH, epoch
  payload. Missing, mismatched or uncommitted sends create gaps, not edges.
- `PersistentFileTraceBridge` publishes successful `QuorumPeer` epoch reads
  and writes, plus successful `FileUtils.write` calls, as stored versions. A
  version key contains the canonical absolute path, complete bounded SHA-256,
  size, modification time and filesystem file key. Epoch reads additionally
  verify the value returned by ZooKeeper against the file's first line;
  writes verify its complete decimal content. An exception produces no
  successful version. The version is shared across peer restarts in the same
  JVM, while paths keep distinct peers' files separate.

The GraphChecker-style runtime recorder and the Soot caller that invokes
`ZooKeeperWeave.apply()` must be included in the Mallory JUnit pipeline.
Place the runtime and this adapter jars on both the instrumentation classpath
and the selected JUnit's runtime classpath. Run the unmodified JUnit in a
fresh JVM per trial, with recording opened before cluster setup and stopped
after teardown. The target site comes from the case's static analysis and
must be retained in every generated trial graph.

## Verify the pinned source and compile

```sh
python3 Mallory/adapters/zookeeper/graphchecker_port/verify_source.py \
  /path/to/pristine/zookeeper-3.8.7
mvn -q -f Mallory/graphchecker-runtime/pom.xml install
mvn -q -f Mallory/adapters/zookeeper/graphchecker_port/pom.xml \
  test dependency:build-classpath -Dmdep.outputFile=target/dependency-classpath.txt
python3 Mallory/adapters/zookeeper/graphchecker_port/run_original_junit_smoke.py \
  /path/to/pristine/zookeeper-3.8.7 \
  Mallory/adapters/zookeeper/graphchecker_port/target/zk07-smoke
```

`verify_source.py` is read-only. It checks the original
`QuorumRestartTest#testRollingRestart` workload and the exact source anchors
used by the weave. The weave also checks the corresponding Jimple sites.
The test uses ZooKeeper's original test class and method; there is no
replacement workload or manually chosen fault sequence here.
The smoke runner expects that ZooKeeper's original JUnit has already been
built and run once, so its Surefire XML records the complete test classpath.
It writes an isolated woven class directory, JUnit log and JSONL trace under
the requested scratch directory. Its trace check requires a completed
EXPORT before each quorum ATTACH and at least one versioned file read/write.
On the local ZooKeeper 3.8.7 build, this test completed with 12 matched
quorum messages, 20 file writes, 6 file reads and no gaps. Those counts can
change with scheduling; they are an observed run, not fixed assertions.

## Original-JUnit campaigns for quorum and epoch checks

`prepare_zk_campaign.py --case-id` supports ZOOKEEPER-05/06/07/11/12. It
reads each target method, throw line and unchanged JUnit selector from the
102-check inventory, verifies the pinned source hash, and asks the static
planner to find the matching check branch. The planner discovers candidate
I/O and coverage sites; this recipe declares none. For ZOOKEEPER-07, the
check is `Learner.registerWithLeader` line 515 and the exact selected throw is
line 525. Pass immutable tool jars and use a fresh scratch directory:

```sh
python3 Mallory/adapters/zookeeper/graphchecker_port/prepare_zk_campaign.py \
  /path/to/pristine/zookeeper-3.8.7 /path/to/fresh-scratch \
  --case-id ZOOKEEPER-07 \
  --scope-jar /path/to/mallory-static-scope.jar \
  --weaver-jar /path/to/mallory-graphchecker-weave.jar \
  --runtime-jar /path/to/mallory-graphchecker-runtime-all.jar \
  --analyzer-jar /path/to/mallory-graphchecker-analyzer-all.jar \
  --verified-constructor-doors \
  --fault-trials 8 --seconds 120 --max-faults 3
python3 -m Mallory.core.graphchecker_fuzzer \
  --config /path/to/fresh-scratch/campaign-config.json \
  --out /path/to/fresh-scratch/fuzz8
```

The campaign's `post_weave` pass gives `WeaveZooKeeperMain` the generated
manifest after the generic Soot probes, then hashes the final classes. The
ZooKeeper protocol scopes are reusable; a selected Leader or QuorumPeer target
gets its own exact method scope from the manifest. A Follower or Learner
target uses the existing protocol turn for that method. The same campaign root can be
resumed after interruption; its checkpoint prevents completed trials from
running again. In the integration pilot, one healthy trial reached the guard
twice, and one automatically selected closure I/O fault applied with exact
node, occurrence and ordinal identity. The target was reached after the fault;
its selected throw did not execute. This pilot does not establish a completed
fuzz campaign or a negative bug finding.

For a full per-case run, the current target-preserving budget is 64 fault
trials, 1,800 cumulative trial seconds and four faults per sequence. Pass
`--fault-trials 64 --seconds 1800 --max-faults 4` when preparing the config.
The optional `--adapter-classes` argument pins a built adapter class directory
for a persistent campaign. The recipe relocates original Surefire classpath
entries if the unchanged source build has been copied to persistent storage;
dependency JAR paths are kept as recorded by the JUnit run.

For an original JUnit that changes epoch files directly, preparation copies
the selected test's unchanged class files into a separate weave input. The
post-pass gives that test method a CLIENT occurrence and records a versioned
WRITE only after a successful `FileUtils.write(File, ...)` call. This rule
applies to the selected method's calls; helper methods outside the copied test
class still need an attributed hook. The file version combines canonical path,
size, modification time, file key and content digest. The common runtime puts
the version identity in each STATE endpoint's site index while retaining the
declared transport READ/WRITE port. A fresh ZOOKEEPER-11 original-JUnit pilot
passed 1/1 and recorded test writes to `currentEpoch` and `currentEpoch.tmp`
followed by their exact peer reads. Both STATE edges survived graph building;
only the `currentEpoch` read preceded and entered the target check's closure.
This pilot is not a completed per-case fuzz result.

The full static overapproximation also selects application work that has no
ZooKeeper peer source binding. Its trace reports those unattributed regions
and doors as gaps. Shared-field candidates currently report bounded
`STATE_ACCESS_UNHOOKED` gaps; they cannot be treated as proven state edges.
Only matching quorum envelope identities and exact file versions create
causal edges in this adapter.
The static `THIS` owner rule is restricted to actor classes registered by this
bridge: `QuorumPeer`, `Learner`, `Follower`, `Leader` and `LearnerHandler`.
Helper objects such as `MultipleAddresses` and `QuorumMaj` inherit the active
source if one exists, and otherwise produce an attribution gap. In an original
healthy JUnit pilot, this correction reduced `UNREGISTERED_SOURCE` rows from
22,326 to 11,900 while retaining four verified target-closure edges; other
background-thread gaps remain and are not silently converted to causal edges.

The first 64-trial release omitted `FileReader` construction and
`BufferedReader.readLine` in `QuorumPeer.readLongFromFile`; its receipt stays
preliminary. The newer planner selects `readLine`, and
`--verified-constructor-doors` enables only the verified external
`FileReader(File)` constructor pattern. The accepted rescan selects both
read-side sites from the static scope without a hand-written fault list.
The epoch flush is also selected and observed. It can remain outside the
exact dynamic closure when the target reads a cached `acceptedEpoch` field:
the adapter does not invent a file-to-field edge without a matching versioned
read or another observed causal path. The scheduler retains selected observed
doors as a weaker exploration tier.

The second frozen 64-trial release covered 28 distinct injected site IDs,
including both read-side sites, and reached the check after a fault in 37
trials. Its graph lacked a program-order edge between two completed
`registerWithLeader` turns on the same peer and thread. The third release
added a paired scope-exit-to-next-scope-entry edge and finished 64 trials:
62 strict injections, 43 injection-specific target reaches and no target
throw. Its first strict trial places the fault in the check's backward closure
through that edge, without asserting a read-from relation. The verified
`FileReader(File)` door was injected once, but `BufferedReader.readLine`
was not injected. The third release therefore remains preliminary. Its
receipt and the first two releases are archived separately; a larger fourth
campaign uses the generic scheduler to test further selected observed doors.

The original ZOOKEEPER-05 `Follower.followLeader` check runs after the
synchronous `registerWithLeader` call returns. Its first 64-trial receipt is
preliminary: the runtime recorded LEADERINFO EXPORT/ATTACH before the check,
but a fresh root for `registerWithLeader` cut that WIRE edge out of the outer
check's closure. The bridge now begins that nested same-peer turn as a
continuation. In an isolated unchanged-JUnit pilot, the healthy check was
reached six times and its closure gained six exact WIRE edges; one generic
fault trial strictly injected an IOException and retained the check with the
same six WIRE edges. No target throw occurred. A separate ZOOKEEPER-07
healthy pilot still reached its check twice and retained two WIRE edges.
These pilots do not replace the first ZOOKEEPER-05 campaign receipt.

## Boundaries to extend before using all ZooKeeper checks

This port's existing GraphChecker quorum bridge covers LEADERINFO and
ACKEPOCH in one-JVM MiniClusters. `applyRuntimeTargetScope()` reads the exact
selected target method from the generated static manifest. The same bridge
can prepare ZOOKEEPER-05/06/07/11/12 with their original JUnit selectors;
each still needs its own healthy trace and fault campaign before it is marked
complete. ZooKeeper client CONNECT/REQUEST handling,
follower-to-leader request packets, observer traffic and
`SessionTrackerImpl` ownership still need protocol adapters before their
checks can claim an observed end-to-end causal path. In a multi-JVM cluster,
the in-process socket FIFO map would have to be replaced by an actual
protocol-carried trace header. Existing Mallory adapters identify useful
production call sites, but their Probe string correlations are not used here.

The hook is called only for `Learner.writePacketNow` ACKEPOCH writes with
`flush=true`. A packet buffered with `flush=false` is marked as a gap until
the later successful flush is tracked. Fault attempts belong to the generic
Mallory fault-door trace; they never stand in for a completed SEND.
