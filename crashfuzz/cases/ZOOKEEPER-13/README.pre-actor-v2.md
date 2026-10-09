# ZOOKEEPER-13: read-only global-session renewal

> **Actor identity recheck pending.** The earlier I/O fault selector used a global call-site ordinal and did not bind the peer/client/socket or file owner. Its raw trials, coverage, and elapsed time are preserved as historical selector-level evidence in `result.json`, but are excluded from the current actor-matched budget. See [independent audit](../../audits/zookeeper-terminal-actor-identity-2026-10-07.md).

The selected production check is `ReadOnlyZooKeeperServer.validateSession` in
ZooKeeper 3.8.7 (`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`). Its guard at
line 123 calls `LearnerSessionTracker.isGlobalSession(sessionId)`. The selected
`ATHROW` at line 126 constructs `ServerCnxn.CloseRequestException` with
`RENEW_GLOBAL_SESSION_IN_RO_MODE`. `ZooKeeperServer.processConnectRequest`
calls this override while processing a client connect request. The target is a
protective rejection.

The unchanged embedded-cluster JUnit
`org.apache.zookeeper.test.ReadOnlyModeTest#testGlobalSessionInRO` is the
workload. It starts a quorum, shuts down a peer, expects a global session
renewal and creation to time out in read-only mode, and then checks local
session creation. Its normal `@BeforeEach`, `@AfterEach`, and JUnit timeout
remain active. Healthy execution passed in 65.277 seconds, with nine exact
guard hits and nine exact selected throws. These throws are expected by the
original test and alone are not bug evidence.

`evidence/agent/src/zk13` is a case-local ASM agent built from its source.
`evidence/runner/src/zk13` is a case-local pure JUnit Platform launcher.
The original 3.8.7 source and original compiled test and production classes
are in `/users/ZhenyuLi/zk13-unit`; dependencies come from the original
Surefire classpath. The executable classpath is checked to contain neither
GraphChecker nor skeleton. No GraphChecker graph, closure, or static analysis
artifact is consulted for selector choice. The agent observes exact target
branch and throw events, selected production line coverage, and direct
socket/file I/O invocations. Raw JVM runs are in `/users/ZhenyuLi/zk13-runs`.
`evidence/runtime-provenance.json` records the source commit, local compiled
class hashes, current agent and runner hashes, and the forbidden-classpath
check. The agent was upgraded after trial 004 to include request context; the
earlier local JAR was overwritten, so its hash is unavailable.

`evidence/campaign.py` builds selector sequences from observed I/O. A trial is
strict only when every selector matches and applies in order. It counts as
target-retaining only when the same production check executes after the final
fault. `evidence/trials.jsonl` records each run; the atomic
`evidence/campaign-checkpoint.json` resumes without rerunning completed trials.
`evidence/source-audit.json` independently recomputes strictness and target
retention from raw events and compares the post-fault exception class, reason,
session ID, and remote address with the original test's created global session.
The first four runs predate the request-context probe upgrade and have no
recorded session ID; their raw event and JUnit logs remain available.
The case `result.json` is updated after each run and drives the 102-case table.
The current budget is 128 trials and ten ordered faults. The initial 64/six
budget became 80/eight after 16 completed attempts. Trial 082, the last of
the 80 accepted attempts, newly reached `NIOServerCnxn.close:603` and
`NIOServerCnxnFactory.removeCnxn:766` in a strict, target-retaining eight
fault sequence. Source inspection shows these lines are exclusive bodies of
the two connection-removal failure branches, so this is evidence of two new
production branch outcomes. The probe measures production lines and methods;
the branch conclusion is limited to these source-reviewed exclusive bodies.
The 80 completed attempts remain in the checkpoint without rerunning them.

After the initial sequential runs, the same original JUnit is scheduled on
two independent JVM workers by `evidence/campaign_parallel.py`. ZooKeeper's
original `PortAssignment` divides the test port range across eight process
slots; this case uses slots 7 and 8, with separate run directories. The
coordinator alone writes the checkpoint and case result after each completed
trial. Ordered selector matching and post-fault target checks remain mandatory
for each worker, and recovery reuses any completed run output.
The scheduler reserves one of every three new attempts for a distinct
one-fault selector from the healthy trace when those selectors remain; the
other slots choose the deepest target-retaining sequences observed so far.
Coordinator restarts that interrupted JVMs with exit code 130 are excluded
from the trial budget and valid coverage. Their raw outputs are archived under
`/users/ZhenyuLi/zk13-runs/archived-invalid-attempts`, and selectors derived
only from those incomplete traces are removed. The checkpoint lists each
archived attempt; eligible plans are rerun from the checkpoint.

## Final result

The 128 completed fault attempts include 116 fully applied ordered sequences
and 103 that also revisit the selected target after the last fault. The
deepest validated sequence has ten faults. Healthy execution and 124 fault
attempts pass the original JUnit; four one-fault attempts fail while injected
epoch-file I/O prevents cluster startup, before the selected check. The union
of valid target-retaining production line coverage adds ten lines relative to
healthy execution, including one newly covered method and the two
source-reviewed connection-removal branch bodies above.

`evidence/source-audit.json` independently reproduces all 128 strictness and
target-retention decisions from raw events. All observed selected throws have
the expected exception class and source-site reason. Of 868 post-fault throws,
863 have a recorded session ID identical to the global session created by
that run's original JUnit; five early throws predate the entry-context probe
and lack that ID. No different session ID was observed. The selected rejection
already occurs in healthy execution, so repeated throws are not marked as a
new bug. The full wall time was 5,446.568 seconds; summed JVM run times were
8,399.489 seconds because two workers overlapped.

The final raw-run archive is `evidence/zk13-raw-runs.tar.gz` (SHA-256
`63ef1963c39e6f3facdd97a25083d08c861c5421fc01852ee2c3285ebd4b4212`). It
contains the healthy run, all 128 completed attempts, the five archived
invalid orchestration attempts, and the coordinator log.
