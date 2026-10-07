# HBase namespace actor identity, V2 original-JUnit campaign

This standalone passive Java agent is a reusable identity layer for
HBASE-08, HBASE-21, and HBASE-22. It targets the unchanged HBase 2.6.6
production JAR and the original two-master `TestNamespaceAuditor` methods.
The isolated node1 staging directory ran two unchanged table and two
unchanged restore JUnit healthy seeds. HBASE-08 has completed and passed its
independent raw audit; HBASE-21 continues from its own checkpoint on node1.
HBASE-22 has two further unchanged table healthy seeds and its own checkpoint
on node0. Current counts and stop reasons are in each case's atomic
`campaigns/CASE/result.json`.

## Source relationship

At source revision `d5f63f523c065f963992ea4e74db268d17816631`,
`TableNamespaceManager` constructs its `ZKNamespaceManager` with
`masterServices.getZooKeeper()`; region servers also use
`ZKNamespaceManager`. Thus a znode path and call site alone can merge a
master's I/O with a region server's or the other master's I/O. The selected
`ClusterSchemaServiceImpl` and `NamespaceStateManager` instances each retain
their own `MasterServices`. HBASE-21's quota exception and HBASE-22's region
quota exception are already expected by their unchanged healthy JUnit tests;
an observed throw alone is not a bug.

The agent records the `Abortable` owner of each `ZKWatcher` at construction,
and records a `ZKNamespaceManager` identity for the same watcher. A distinct
replacement manager on the same watcher receives a fresh ID; the watcher is
then marked ambiguous and no further fault/target on it can be admitted,
because an old manager could still issue I/O through that watcher. At each
namespace-related `ZKUtil` API attempt it logs the current active/standby
master role or region-server role, the raw `ServerName`, the manager ID, the
watcher identity, the operation, znode path, production call site, and the
ordinal scoped to that watcher and point. It also logs whether the API
returned or threw. At each of the three selected target methods it logs the
same Master watcher, raw `ServerName`, and manager ID, plus the target
argument and exception outcome. The six intercepted ZK families are
`createWithParents`, `updateExistingNodeData`,
`getChildDataAndWatchForNewChildren`, `getDataAndWatch`,
`watchAndCheckExists`, and the two-argument `deleteNode`. The last two cover
`ZKNamespaceManager.start` and `deleteNamespace` paths missed by the first
pass. Passive `TableNamespaceManager.get(String)` and `getMaxRegions` hooks
emit `GUARD_OPERAND` only for the released HBASE-08 lookup immediately before
its null check (line 115), HBASE-21 quota predicate (line 128), or HBASE-22
quota predicate (line 166). The marker has its **own event sequence** plus
the enclosing target invocation's sequence, subject, and actor, even when an
HBASE-08 lookup is nested in an HBASE-21/22 invocation. `TARGET_EXIT outcome` distinguishes
HBASE-08's selected namespace-not-found throw, HBASE-21's selected region
count quota throw, and HBASE-22's selected table-region quota throw from
other exceptions in those methods. These are high-level ZooKeeper API attempts;
they do not assert that an underlying network packet was sent or persisted.

The optional `-Dns.actor.fault.plan` accepts semicolon-separated ordered
steps of `role~family~URL-safe-Base64(path)~site~ordinal~kind`, copied from
healthy `IO_ATTEMPT selector=` receipts and suffixed with
`CONNECTIONLOSS`, `OPERATIONTIMEOUT`, or `SYSTEMERROR`. With no property, the
agent is passive. Fault matching accepts only an `ACTIVE_MASTER` event with
a bound namespace manager and raw `ServerName`. Once the first fault applies,
all later faults must be on the **same raw Master and manager**. The agent
throws the selected `KeeperException` at the `ZKUtil` method entry and logs
each application; an unmatched step cannot be counted as applied. This
models a high-level API failure, which can bypass retries inside that API.
The agent JAR used by the node1 healthy seeds and fault trials has SHA-256
`f6ac63c8ad2e07499f99f93e1b04f9cf53c5f849274b98828277b3fc159b8601`.

The cross-run plan selector uses the observed role, I/O family, path,
call site, and per-watcher ordinal. A candidate is target-retaining only if
its postfault target receipt has the **same raw Master `ServerName` and
manager ID** as the injected event within that run. A healthy seed must show
that the chosen role selector uniquely selects the intended Master in the
two-master test before enabling any fault. If the active Master changes, the
new Master is a different actor and cannot satisfy this same-actor check.
The default run is passive; a fresh V2 checkpoint can use the optional fault
mode only after two original healthy seeds validate stable role selection.
At injection time, the agent also requires one distinct raw active Master
among all observed Master watchers. A matching selector with an ambiguous,
unassigned, or changed actor produces `FAULT_REJECTED` and applies no fault.
The old HBASE-08/21/22 coverage results remain historical and must not be
imported into a new V2 denominator.

## V2 controller and admission

`controller.py init HBASE-08 SEED1 SEED2` (likewise HBASE-21/22) starts a
fresh, case-specific checkpoint only after two independently completed,
unchanged original JUnit healthy runs. It intersects **same-actor pretarget**
I/O selectors across the seeds. If a selector maps to more than one
Master/manager within a seed, initialization excludes it. The case-specific
subjects are `TestNamespaceAuditor_np2` for HBASE-08,
`TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4` for HBASE-21,
and `TestNamespaceAuditor_np2:table2:5` for HBASE-22. Healthy JUnit must pass
and reach the selected check; for HBASE-21 and HBASE-22, their selected quota
throw is an expected healthy result.

`controller.py run CASE` draws ordered fault plans from the observed I/O
queue. A trial is effective only if every planned fault is applied in order
at its exact selector and the selected check's **guard operand event after
the final fault** has the same raw active Master and manager ID. This admits
a target method that entered before the fault but evaluated its check after
the fault. All three checks require a `GUARD_OPERAND` receipt for the exact
target invocation; HBASE-21 and HBASE-22 also require
JaCoCo coverage of the predicate line (128 or 166); otherwise the guard is unproven and
the trial is excluded. The HBASE-21 null-namespace early return is therefore
not mistaken for selected-predicate execution. Wrong-actor, unmatched,
target-lost, and guard-unproven trials keep their raw evidence and time but
do not contribute coverage/I/O feedback. Per-trial JaCoCo output counts
production methods and branches in four released classes; no graph or
GraphChecker artifact is used.

The queue retains every distinct observed selector, ordinal, fault kind, and
ordered prefix. Its current priority favors actual healthy I/O closer in
event order to the selected guard on the **same Master/manager**; every eighth
attempt uses the original I/O novelty priority for broader exploration.
Fresh I/O observed after an effective fault receives a separate recovery
priority. This changes only the order, not admission or the pending plan set.
HBASE-08 started with the original priority. After four completed attempted
trials, a safe checkpoint migration added this ordering and ingested the
already completed fifth raw run without replay. Case-local
`migration-before.json`, `migration-after.json`, and immutable checkpoint
copies record the old/new controller, queue, seen, and agent SHA-256 values.

HBASE-21 later had repeated exact `nodeDataChanged:131` faults whose selected
quota guard ran on a replacement Master/manager. Those trials failed the
same-actor gate. After attempt 21, its node1 runner blocked the already
selected attempt 22 **before** creating a run directory or JVM; the controller
was stopped with its completed 21-trial checkpoint intact. The new priority
penalizes a final fault's exact role/family/path/site only after at least
three strict target-losing trials at that site and no effective trial there.
It never deletes a plan, and every eighth attempt retains the original
exploration ordering. The first two postmigration original JUnit trials
(`r022`, `r023`) were both strict, same-actor, guard-after-fault, passed the
JUnit, and returned the healthy expected region quota signature. The pilot
used a temporary 23-attempt cap and then restored the original 320-attempt,
80-effective-trial budget without replay. The migration's before/after
checkpoints, raw pilot audit, queue/seen hashes, controller hashes, and
paused-but-unstarted selector are under `evidence/HBASE-21/`.

HBASE-22 runs on node0 with independent `runs/table-*` scratch, checkpoint,
and tmux. Both node0 healthy seeds passed the original table JUnit, reached
the exact selected quota guard once on the same active Master, and had JaCoCo
line 166 with two covered branch outcomes; the immutable receipt is
`evidence/healthy-node0-HBASE-22.json`. Its node0 runner uses the host-shared
`jvm-start.lock`: before each JUnit it requires at most three already running
Java processes and at least 3 GiB free, and holds the lock until the new Java
process appears. The node1 staging runner and HBASE-21 checkpoint remain
separate.

After HBASE-22 attempt 57, 15 strict trials at the final
`ACTIVE_MASTER/ZK_DATA_READ/nodeDataChanged:131` site had lost the selected
same-actor target. The node0 runner paused the already selected r058 before
creating a run directory or JVM. At this complete checkpoint, the controller
enabled the same bounded site-loss priority used for HBASE-21. It changes
only selection order: no exact plan is deleted, the queue and seen hashes,
57 completed trials, and original 80/8/320 budget are unchanged. Every eighth
attempt retains the unpenalized exploration order. The original r058 plan was
then executed exactly once as pilot r058, followed by r059. Both were strict
eight-fault trials, retained the selected guard on the same Master after the
last fault, and passed the unchanged `testTableOperations` JUnit with the
healthy expected table quota outcome. The two-round pilot temporarily capped
attempts at 59; its complete 59/44 checkpoint restored the 320-attempt cap
without replay. The pre/post checkpoint and SHA receipts, unstarted inflight,
and raw pilot receipt are in `evidence/HBASE-22/`. Before resuming r060, the
independent audit rechecked all 59 raw trials and their per-trial JaCoCo
selected-branch results with zero errors. A separate cumulative JaCoCo pass
matched the checkpoint's 60 covered production methods and 50 branch keys
across its 46 exec files. These audits did not rerun an original JUnit.

The default bound is **80 effective trials, at most eight ordered faults**.
If any of the final eight effective trials first adds a production method,
branch, or I/O family observed in at least two effective trials, the same
checkpoint extends to **128 effective trials and at most ten faults**. The
attempt cap is 320 (512 after extension), and natural queue exhaustion is
recorded separately from budget completion. Completed run directories have
immutable logs, JaCoCo data, plan, elapsed-time and exit receipts. The
controller stores an atomic `inflight.json` before launch and an atomic
checkpoint after ingestion. On resume it ingests an existing completed run
instead of rerunning it; an interrupted run without an exit receipt requires
manual process/raw-log audit before any retry. A new HBASE-08 selected
exception pauses at `candidate_review_pending_source_and_replay`; HBASE-21/22
quota signatures already present in healthy runs are recorded as expected
signatures, not automatically called new bugs. Every checkpoint also writes
an atomic case-local `campaigns/CASE/result.json` row with attempts, effective
trials, fault count, elapsed time, source file/function/guard line, coverage
and I/O gains, and stop reason;
the shared 102-case table can ingest this independently. These V2 counters start at
zero and never import the older unbound runs.

For an original JUnit with multiple selected target invocations, the oracle
retains **all** same-actor postfault outcomes and prefers any selected throw
over earlier normal outcomes. This was corrected at HBASE-08 attempt 34;
all 35 raw attempts through the in-flight r035 receipt were audited and had
zero non-normal selected target events. The r035 run was ingested from its
existing raw exit without replay. Case-local `oracle-before.json`,
`oracle-after.json`, and checkpoint copies preserve both controller versions
and the unchanged agent SHA-256.

## Offline checks

- Java 8 `javac` compiled the agent, coverage reporter, smoke, and
  original-JUnit launcher sources against the release distribution;
  `bash -n run.sh` and `python3 -m py_compile controller.py` passed.
- `NamespaceActorSmoke` loaded all six instrumented classes with the agent;
  no ByteBuddy transform error appeared. It exercised transformed ZK exists,
  delete, and max-region calls without a ZooKeeper connection, checking the
  Advice/helper package boundary at execution time. It also verified that a
  replacement manager receives a new ID and fail-closed watcher status.
  It started no HBase or ZooKeeper cluster.
- Sixteen offline controller tests passed, covering exact same-actor admission,
  wrong Master, manager, and target subject rejection, target order, missing
  fault, ambiguous healthy selector, postfault feedback actor filtering, and
  target entry before fault followed by guard after fault, HBASE-21 guard-line
  admission, normal-outcome exception accounting, healthy guard distance and
  near-target priority without dropping pending plans, a later selected throw
  after a normal invocation, and a zero-based V2 result
  row that excludes historical trial counts.
  A historical HBASE-22 JaCoCo file produced
  `NamespaceStateManager` branch line 166 with two covered outcomes; this
  checks the reporter against released bytecode without claiming a V2 run.
- ByteBuddy's class dump contains transformed `ZKWatcher`,
  `ZKNamespaceManager`, `ZKUtil`, `TableNamespaceManager`,
  `ClusterSchemaServiceImpl`, and `NamespaceStateManager`. `javap` confirmed
  the new ZK exists/delete entry hooks and direct public helper calls,
  without package-private `access$...` bridges. `ZKWatcher` needs retransformation because the
  agent's own type references cause it to load before the transformer is
  installed.

`bash run.sh build` regenerates the small local agent JAR; its timestamped
archive bytes can differ between builds, so each cluster seed should record
the JAR's SHA-256 in that seed's manifest.
The unchanged server and test JAR SHA-256 values are
`27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696`
and `b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5`.
The local JUnit Platform launcher is bundled under this directory with
SHA-256 `0b0beaeb6880a31149641d2d848b863712885469670c12099586d7f798522564`;
the runner does not depend on another case's working directory.

Each cluster seed captures a fresh scratch directory and Java agent output.
The two table seeds both passed the unchanged JUnit, reached HBASE-08 ten times
and HBASE-22 once per run, and showed 18 stable same-actor pretarget selectors
from five related ZK families. The two restore seeds both passed, reached
HBASE-21 once per run, and showed 21 stable same-actor pretarget selectors.
HBASE-21/22 quota exceptions occurred in the healthy JUnit and are expected.
HBASE-22's selected predicate is at
source lines 165–167; checklist line 172 belongs to its exception message.
`bash run.sh healthy table SEED` selects the original
`testTableOperations` workload for HBASE-08 and HBASE-22; `healthy restore
SEED` selects the original `testRestoreSnapshotQuotaExceed` workload for
HBASE-21. Each seed has a new scratch directory, 240-second bound, raw JUnit
log, exit receipt, and JaCoCo file. `bash run.sh trial KIND CASE-rNNN PLAN`
uses the same isolated runner and adds an ordered plan. These commands are
run in separate node1 scratch directories under a sequential MiniCluster
slot. New V2 counts never include the older unbound HBASE-08/21/22 runs.
