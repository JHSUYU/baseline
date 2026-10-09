# HBASE-24: procedure znode PB-magic check

The selected check is `ZKProcedureMemberRpcs.startNewSubprocedure`, source line
210 in unchanged HBase 2.6.6 commit
`d5f63f523c065f963992ea4e74db268d17816631`. The method reads a
procedure znode and rejects data without the protobuf magic prefix. It catches
its own `IllegalArgumentException` and sends an abort, so the test's JUnit
outcome alone cannot identify the exact guard outcome. This guard checks data
format; its classification as ad hoc coordination is uncertain from source
alone.

The original `TestZKProcedureControllers#testSimpleZKCohortMemberController`
does reach the guard in a MiniZKCluster. Its healthy run took 17.03 seconds,
passed, and evaluated `isPBMagicPrefix` once with a valid 7-byte payload.
A matched `CONNECTIONLOSS` at the abort-child watcher left the target reachable
and JUnit passing. The same fault at the initial acquired-child watcher
removed the only prepare callback; this diagnostic run timed out before the
guard. Those two diagnostics are excluded from the current campaign.

The current workload is the stronger unchanged original
`TestZKProcedure#testMultipleMembers`: it starts four actual procedure
members in one MiniZKCluster. Its healthy run took 17.95 seconds, passed,
and evaluated the selected PB-magic guard once on each member, all true.
Using four members allows one member's I/O exception to be followed by another
member reaching the check. The workload uses the original JUnit bytecode, with
no hand-written cluster operations or changed assertions.

The case-local ByteBuddy agent records the target method and the exact
`ProtobufUtil.isPBMagicPrefix(byte[])` result. It observes ZK child-list,
exists, and data-read operations from `ZKProcedureMemberRpcs`. A fault
selector contains the I/O family, member identity, znode path, production
call site, and hit ordinal. Runtime identity is registered from each
controller's `start(memberName, listener)` call and its own `ZKWatcher`.
The three checked `KeeperException` variants are `CONNECTIONLOSS`,
`OPERATIONTIMEOUT`, and `SYSTEMERROR`. JaCoCo records production method and
branch coverage in `ZKProcedureMemberRpcs`, `ZKProcedureUtil`, and `ZKUtil`.
There is no GraphChecker JAR, prewoven class, skeleton, static map, closure,
or graph feedback.

The graph-free campaign uses the healthy observed I/O as seeds, mutates one
ordered fault at a time, and admits feedback only when every planned selector
and exception kind matches and a PB-magic guard executes after the final
fault. The default budget is 80 such effective trials, at most 240 attempts,
and eight ordered faults per sequence. If the final 16 effective trials add
production method or branch coverage or a stable I/O family, the same
checkpoint can extend to 128 effective trials and ten faults. Every trial's
plan, match result, guard result, JUnit status, coverage, and elapsed time are
atomically recorded in `work/checkpoint.json` and `result.json`. The campaign
and supervisor run in tmux sessions `hbase24_fuzz` and `hbase24_supervisor`
and resume from an interrupted trial. All mutable data is case-local;
per-trial MiniZK data is removed only after its result is checkpointed.

## Completed result

The campaign finished its default budget: 92 distinct attempts, 85 strictly
applied plans, and 80 trials in which a PB-magic check executed after the
last fault. The plans requested 261 checked ZooKeeper exceptions and applied
252. The deepest tested plan contained five faults. Healthy calibration plus
all attempts took 2453.33 seconds. The 80 admitted trials added one covered
production method and eight covered branches; they added no stable I/O site.
The final 16 admitted trials added no method, branch, or I/O-site coverage,
so the conditional 128-trial extension did not apply.

Every observed PB-magic check returned true. No selected target exception
occurred, and there is no new-bug candidate at this check. Twelve faulted
JUnit runs passed and 80 failed, often through procedure abort or timeout
after an injected ZooKeeper exception. These JUnit failures are recorded
separately from the selected guard result and are not labeled as coordination
bugs by this target-exception oracle.

The source-level classification is a likely static-selection false positive:
this guard validates the encoding of one procedure znode's data and handles
bad encoding locally by sending a member abort. It does not compare the
multi-hop distributed state seen in the motivating ad hoc coordination case.
This classification does not change the recorded runtime result.

All 92 raw logs were re-parsed to confirm fault order, runtime identity,
target-after-fault, JUnit status, and per-trial elapsed time. The JaCoCo union
was recomputed and matched the checkpoint; the late-novelty gate was checked
again. The complete checkpoint, logs, JaCoCo execution files, agent binary,
and runner source are in `evidence/hbase24-graphfree-80.tar.gz` (SHA-256
`88786ac969a6d6ea638c577f5514ff8e44412d97f50ba3fea40bdaaa908b822c`).
