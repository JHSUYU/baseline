# HBase namespace actor identity, offline V2 preparation

This standalone passive Java agent is a reusable identity layer for
HBASE-08, HBASE-21, and HBASE-22. It targets the unchanged HBase 2.6.6
production JAR and the original two-master `TestNamespaceAuditor` methods.
It has not run a cluster JUnit, injected a fault, or contributed a V2 trial
to any of the three case counters.

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
No fault plan has been exercised yet.

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
- Twelve offline controller tests passed, covering exact same-actor admission,
  wrong Master, manager, and target subject rejection, target order, missing
  fault, ambiguous healthy selector, postfault feedback actor filtering, and
  target entry before fault followed by guard after fault, HBASE-21 guard-line
  admission, and a zero-based V2 result row that excludes
  historical trial counts.
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

Before running a cluster seed, capture a fresh scratch directory and Java
agent output for each case. Verify actor and manager binding in at least two
healthy repetitions, actual pre-target I/O families, source-specific target
arguments, and unchanged JUnit pass. HBASE-22's selected predicate is at
source lines 165–167; checklist line 172 belongs to its exception message.
The prepared `bash run.sh healthy table SEED` selects the original
`testTableOperations` workload for HBASE-08 and HBASE-22; `healthy restore
SEED` selects the original `testRestoreSnapshotQuotaExceed` workload for
HBASE-21. Each seed has a new scratch directory, 240-second bound, raw JUnit
log, exit receipt, and JaCoCo file. `bash run.sh trial KIND CASE-rNNN PLAN`
uses the same isolated runner and adds an ordered plan. These commands are
**prepared only**; no V2 cluster JUnit or injection was run while shared
cluster slots were busy. Two healthy runs of `testTableOperations` and two
of `testRestoreSnapshotQuotaExceed` are still needed before campaigns start.
