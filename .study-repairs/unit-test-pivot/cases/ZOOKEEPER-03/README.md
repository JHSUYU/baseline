# ZOOKEEPER-03: `SessionTrackerImpl.setOwner`

**Current 102-check status: quality_complete.** The independent recorder replay
below completed 80 new fault trials. The 96 trials in the historical section
remain in `legacy-graph-result.json` and are excluded from current counts
because their runtime recorder used a precomputed identity skeleton.

## Independent recorder replay

The unchanged ZooKeeper 3.8.7 `QuorumTest.testSessionMoved` passed under a pure JUnit Platform launcher and a case-local ASM agent rebuilt from source. The healthy run took 3.931 seconds, evaluated the exact `SessionTrackerImpl.setOwner` guard at line 329 eleven times for the same session ID, and did not execute the line 330 `KeeperException.SessionExpiredException` throw. No original JUnit positive control for this specific `setOwner` throw was found; the exact guard and throw bytecode were reviewed against the source line table. The class files were copied from the original build at commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae` into this case's clean worktree. The independent classpath, agent, and launcher contain no GraphChecker or skeleton component; `evidence/independent/audit.json` verifies their hashes and rechecks every trial from raw JVM events.

The new campaign completed 80 original cluster JUnit fault trials with a maximum of eight ordered I/O faults. All 80 plans matched and applied in order, totaling 376 fault applications. Thirty-one trials reached the exact `setOwner` guard after their final fault; their JUnit runs passed, and none reached the selected throw. Forty-nine JUnit runs failed after losing the target path: 22 connection losses while creating `/sessionMoveTest`, 16 connection losses during later `/` operations, seven failed sync assertions, and four injected epoch-file startup failures. No target-retaining JUnit failure was observed. The admitted faulted runs added eight production lines, from `NIOServerCnxn` I/O exception handling and `SessionTrackerImpl` shutdown handling; source review found no new failure of the selected session-owner check.

The final eight target-retaining trials added no new production line, method, or stable target-pre I/O family, so the conditional 128-trial extension was not triggered. The recorder observed 217 distinct target-pre I/O site and ordinal positions. At the 80-trial ceiling, 415 feedback-generated plans remained queued; the result is budget complete and does not claim selector-frontier exhaustion. `evidence/independent/trial-summary.csv` lists each ordered plan, elapsed time, exact match, target retention, and outcome. The raw 81-JVM archive is `evidence/independent/raw-runs.tar.gz` (SHA-256 `8d5c82ba483aa97584734b48ed566b9a1714425617627d45f7e307edfd14b9f9`). The fault JVMs took 535.583 seconds in aggregate and 274.083 seconds of wall time across two workers; including the healthy JVM, the recorded total is 539.514 seconds. No new target exception or source-supported bug was found.

## Historical campaign

The selected check is at `zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java:330`:

```java
if (session == null || session.isClosing()) {
    throw new KeeperException.SessionExpiredException();
}
```

The originally mapped three-peer cluster test, `SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLearner`, passed five existing healthy runs but emitted zero client I/O fault markers; its `learnerId > 0` condition skipped the relevant workload in those elections. Its previous instrumentation recorded only a coarse `setOwner` method frame, so the absence of a detailed method event is not used as proof by itself. The unchanged original embedded-cluster `QuorumTest#testSessionMoved` passed and executed the selected `setOwner` guard 11 times under this case's exact target probe, all on the nonfatal path. That test is used for fault trials; its method is unchanged.

The case-local `install_probe.py` compiles a small target probe in an isolated ZooKeeper source copy on node2. It records exact `METHOD_ENTER`, branch `#u12`, and explicit throw `#u13` events. The existing runtime recorder supplies exact client TCP and quorum response I/O point identities plus production method and branch coverage. Each faulted run uses the same original JUnit test. The copied low-level recorder and prewoven classes still depend on a precomputed scope/identity skeleton from the earlier ZooKeeper instrumentation. This case did not reconstruct a graph, compute a closure, or rerun static analysis during fuzzing; replacing that legacy recorder dependency remains a separate instrumentation task.

The campaign uses the shared coverage/I/O fuzzer with exact identity matching, one-fault sequence mutation, and replay/source review for any exact exception candidate. Its initial 48-trial/four-fault budget completed in 183.515 measured seconds: 48 exact injections, 18 post-fault target reaches, 24 multi-fault sequences, and no selected target exception. The combined feedback gained 1,039 IDs at that point; the production code coverage gain is 44 methods plus 114 branch outcomes. The other 881 IDs are call-site return/throw feedback, reported separately. Trial 38 still added two call-site feedback IDs, and no depth-four sequence had been tried. The same checkpoint was therefore reopened at 96 trials/six faults to exercise larger I/O fault combinations; the first 48 sequences are retained and are not rerun.

During the run, `result.json` was mirrored atomically after each completed trial, so the 102-case checklist kept updating while node2's `zk03-fuzz` tmux session ran. The full checkpoint and traces remain at `/users/ZhenyuLi/zk03-case/campaign/ZOOKEEPER-03` on node2 for audit or later budget extension.

## Final result and source review

The extended campaign completed **96 fault sequences in 396.469 measured seconds** (4.027-second healthy seed plus 392.442 seconds across 108 trial attempts). Twelve sequences needed a second exact-match attempt. The unchanged original JUnit exited successfully in all 96 sequences. Ninety-five sequences applied every requested fault in order; one two-fault sequence applied only its first fault and was recorded as unmatched. Sixty-four strict sequences lost the selected check after injection and contributed no feedback. The remaining **31 strict sequences reached `setOwner` after the final fault**: 22 with one fault and nine with two. All post-fault `#u12` outcomes were nonfatal. No exact `#u13` `SessionExpiredException` was recorded.

The source condition rejects an absent or closing session before assigning its owner. `PrepRequestProcessor.pRequest2Txn` first calls `trackSession` and then `zks.setOwner` for `createSession`; `LeaderSessionTracker` and `LearnerSessionTracker` delegate to `SessionTrackerImpl` for global or local state. A thrown exception at the selected site would therefore require source-level lifecycle review. No such throw occurred in this campaign, so there is **no new bug candidate** to replay. The production coverage union gained **44 methods and 117 branch outcomes** over the healthy seed; 884 additional call-site feedback IDs are recorded separately. Runtime controller and synthetic fault-gate IDs are excluded from those code coverage counts.

The fixed budget stopped the run. Fault depth counts were 48 one-fault, 34 two-fault, and 14 three-fault sequences. All three-fault sequences lost the target, so no deeper target-preserving sequence could be mutated; the configured six-fault cap was not reached. The pending queue still contains 6,103 sequences. `evidence/trial-ledger.csv` records each sequence, its fault marker(s), exact match, target result, JUnit exit, coverage contribution, retry count, and the sum of all attempt times. `evidence/campaign-summary.json` records checkpoint counts. The final checklist status is `quality_complete` **for this workload and budget**; it does not claim exhaustive absence of a bug.
