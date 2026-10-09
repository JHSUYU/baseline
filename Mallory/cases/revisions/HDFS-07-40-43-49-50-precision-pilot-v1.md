# HDFS-07/40/43/49/50: precision pilot plan (v1)

Read-only source and archived-trace review, 2026-10-09. The five canonical
campaigns each completed 80 fault trials, with no exact target throw. Their
`data/mallory/quality_reviews/causal_precision_v2/<ID>.json` sidecars classify
them as `root_free_door_unmatched`: a reached target after *some* fault is not
evidence that an effective fault on a healthy, root-free target path reached
that target. No bug is claimed here. The existing campaigns, checklist, and
frozen release must remain unchanged.

## Why the existing plans missed

The healthy root-free doors are the entry to the very RPC that executes the
selected check, except for three `Journal.persistPaxosData` doors in HDFS-07.
An entry `IOException` prevents that request from executing its check. The
old scheduler **did** select exact healthy root-free points in 11, 17, 1, 8,
and 8 trials for HDFS-07/40/43/49/50 respectively. Every *effective* such
trial lost the target; the other exact-point attempts were unmatched or had
incomplete weaving. The old `strict_target_trials` counts (8, 13, 11, 8, 7)
are checks on later, different RPC contexts. Each sidecar records zero
same-actor, same-epoch, same-occurrence postfault checks and zero qualifying
root-free trials. This is primarily **fault timing and operation identity**,
not failure to inject or a missing MiniCluster test. Global door ordinal alone
is especially unstable for the random many-block HDFS-43 workload.

| Case | Exact target in HDFS 3.4.3 | Existing MiniCluster JUnit | Healthy root-free door(s) and trace anchor |
| --- | --- | --- | --- |
| HDFS-07 | `Journal.acceptRecovery`, `Journal.java:924-933`, committed transaction containment assertion | `TestQuorumJournalManager#testRecoverAfterIncompleteRecovery` | `jn0/e0` RPC ordinal 13 → target event 1435; `jn2/e1` RPC ordinal 4 → target 1905; `jn0/e0` `persistPaxosData` callsites 1109/1110/1111 after target 1435, before the later recovery |
| HDFS-40 | `FSDirAppendOp.appendFile`, `FSDirAppendOp.java:131-139`, COMMITTED / insufficient replication checks | `TestFileAppend#testFailedAppendBlockRejection` | `nn0/e0` append RPC ordinals 9, 16, 22 → target events 848, 1249, 1570 |
| HDFS-43 | `FSDirTruncateOp.truncate`, `FSDirTruncateOp.java:113-119`, in-progress truncate length comparison | `TestFileTruncate#testMultipleTruncate` | `nn0/e0` second truncate RPC ordinal 418 → target event 31385; first truncate is ordinal 417, events 31300–31357 |
| HDFS-49 | `DirectorySnapshottableFeature.addSnapshot`, `DirectorySnapshottableFeature.java:188-191`, snapshot quota | `TestSnapshot#testUpdateDirectory` | `nn0/e0` createSnapshot RPC ordinal 44 → target event 1857; allowSnapshot is preceding RPC ordinal 43 |
| HDFS-50 | `DirectorySnapshottableFeature.addSnapshot`, `DirectorySnapshottableFeature.java:197-200`, duplicate snapshot name | `TestSnapshotCommands#testSnapshotCommandsWithURI` | `nn0/e0` createSnapshot RPC ordinals 18 and 31 → target events 507 and 997 (`sn1`, then `sn2`) |

The exact branch IDs and compiled class hashes are in each archived
`data/mallory/cases/<ID>/config.json`. Event IDs above identify the archived
healthy `trials/r0000/events.jsonl.gz`; they are **not** replay selectors.

## Small, isolated pilots

For each pilot, create a new versioned agent/config/healthy seed/output
directory. Preserve the same JUnit selector and compiled target. Select by a
parsed operation plus runtime node, epoch, request token, and phase; use a
global ordinal only as a diagnostic. Collect `FAULT_APPLIED`, exception
effect, the target's named occurrence, and a directed time-respecting path
from the applied event to a *later* `TARGET_CHECK`, with no unscoped actor root
as the connecting edge. A separately witnessed retry edge may connect two
request tokens. Require the JUnit XML and a fresh offline audit. Start with
one fault at each proposed door; expand only if one pilot retains the target
with that precise path. If the JUnit stops before the target, record
`target_lost` and stop that door; do not spend another 80-trial budget.

1. **HDFS-07 — durable recovery write, then second recovery.** The test
   constructs unequal journal lengths, deliberately fails finalization,
   restarts `jn2`, and then recovers again (`TestQuorumJournalManager.java:540-570`).
   The existing `persistPaxosData` doors are *before* `AtomicFileOutputStream`
   closes (`Journal.java:1097-1120`), so an exception there can prevent the
   state needed by the second recovery. Add one method-specific IOException
   door **after successful atomic close** of the first recovery's paxos file
   on named `jn0/e0`, before its RPC response, and observe whether the second
   `jn2/e1` `acceptRecovery` check still runs. Preserve the test's deliberate
   finalization fault and its assertion that the caught error contains
   `injected`; if the added error changes that outcome and aborts the test,
   classify this seed as unsuitable for that door. A `jn2/e1` RPC-entry fault
   cannot count because it suppresses its own check. Any cross-node claim
   requires actual response/request handoffs, not a shared client root.

2. **HDFS-40 — block report before append.** The test closes a file, stops a
   DataNode, appends twice, restarts the DataNode, and checks that its stale
   replica is not advertised (`TestFileAppend.java:540-587`). In the healthy
   trace, named `nn0` `blockReceivedAndDeleted` requests occur before append
   ordinals 9/16/22 (for example ordinals 5–7 before append 9). Pilot one
   IOException on the *response side* of a parsed
   `NameNodeRpcServer.blockReceivedAndDeleted` request **after** its
   `BlockManager.enqueueBlockOp` calls (`NameNodeRpcServer.java:1690-1717`),
   bound to the actual DataNode report token. This is a narrower, potentially
   tolerable I/O failure than aborting `append`. The existing block-op
   submit/claim hooks should be checked, and a path into the later append's
   `BlockInfo` read must be witnessed; if it needs state tracking, use the
   concrete block identity/version rather than an actor-wide root. A later
   append on `nn0` alone does not establish this dependency.

3. **HDFS-43 — two truncate requests and a random ordinal.**
   `testMultipleTruncate` sends a first `fs.truncate(p,newLength)`, then an
   idempotence call with the **same** length; it waits for block recovery
   before choosing the next random length (`TestFileTruncate.java:172-195`).
   The healthy target occurs in the second request, immediately after the
   first response; no currently instrumented I/O door lies between those two
   requests (healthy trace events 31357–31366). First run a healthy-only
   method-specific client transport probe for the second `truncate` send,
   labeling request method and retry token; then pilot one client-send
   `IOException` only if the client has a real retry continuation. An applied
   fault must lead to an observed retry SEND → matched server RECV → selected
   check. If no retry occurs, this workload/fault model cannot retain that
   target through this window. The different-length
   `testTruncateTwiceTogether` intentionally expects the exception and would
   be a known-path control, not evidence of a new bug.

4. **HDFS-49 — quota path has one snapshot creation.** `testUpdateDirectory`
   performs `allowSnapshot`, creates just `s1`, and then updates a directory
   timestamp (`TestSnapshot.java:308-325`). Its only root-free current door
   is the `createSnapshot` RPC entry, so an entry error necessarily loses
   the quota check. A feasibility pilot can tag the **post-success
   `allowSnapshot` response** I/O, after the edit-log sync in
   `FSNamesystem.allowSnapshot` (`FSNamesystem.java:7137-7150`), and see if
   retry/continuation reaches `createSnapshot` through exact transport
   tokens. If the JUnit aborts, record this as a workload limit. The default
   one-snapshot workload also has no quota-boundary state; IOException alone
   must not be claimed to trigger the quota exception.

5. **HDFS-50 — distinct names and retry-cache check.** The existing test
   creates `sn1` and `sn2`, then renames/deletes them
   (`TestSnapshotCommands.java:197-225`); it never intentionally requests a
   duplicate. Pilot a method-specific response-I/O fault **after the first
   `NameNodeRpcServer.createSnapshot` succeeds**, scoped to the `sn1` RPC
   token, and observe whether the client retries and what the NameNode retry
   cache does. The source explicitly returns a successful cached payload
   before `namesystem.createSnapshot` on a recognized retry
   (`NameNodeRpcServer.java:1932-1956`). A cached response, aborted CLI, or
   target on later `sn2` does **not** qualify as a postfault duplicate-name
   check. If the test cannot issue an actual duplicate after fault, mark the
   current workload incapable of exercising this failure branch under the
   exception-only model; do not alter arguments or call a routine duplicate
   rejection a new bug.

The first pilot may establish only feasibility or a limitation. Promotion
requires a qualifying fault-to-target path and source/replay confirmation of
any exact target exception. Existing 80-trial results remain available as
coverage data but should not be cited as root-free fault-to-target evidence.
