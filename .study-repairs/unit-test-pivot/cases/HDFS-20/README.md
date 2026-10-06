# HDFS-20: active NameNode claim monotonicity

The selected released Hadoop 3.4.3 site is
`BPOfferService.updateActorStatesFromHeartbeat(BPServiceActor, NNHAStatusHeartbeat)`
at `BPOfferService.java:606`: `assert txid >= lastActiveClaimTxId;`.
The surrounding code compares the active claim in a NameNode heartbeat with
the largest claim previously accepted by the DataNode's block pool offer
service. A stale claim by a different NameNode is rejected earlier and is an
expected fencing path; a failure of the selected assertion is the exact target
oracle and requires source review and replay before a bug claim. Java assertions
are enabled with `-ea` in the original JUnit runner.

All workloads are unmodified JUnit methods from the released Hadoop source,
run in `MiniDFSCluster`. We use case-local source probes at the selected guard,
Hadoop IPC response and durable edit log I/O, and production-class JaCoCo
method/branch coverage. No graph, static slice, Docker cluster, or handwritten
workload is read by the campaign. A trial counts as target retaining only when
every ordered I/O selector matches and applies, and the selected guard runs
after its last fault in the same runtime actor context. An exception from
another actor or an aborted cluster startup is recorded separately.

The original `TestClientProtocolForPipelineRecovery#testPipelineRecoveryOnOOB`
provided the first 14 trials in 1 NameNode + 1 DataNode. The original
`TestStandbyIsHot#testDatanodeRestarts` provided six more in 2 NameNodes +
1 DataNode. The original `TestStandbyIsHot#testStandbyIsHot` supplies the
remaining trials in 2 NameNodes + 3 DataNodes. Its healthy run executes the
exact guard 30 times, 27 with a prior accepted claim, so it exercises the
monotonicity check beyond initial cluster startup.

The multi DataNode workload exposed an instrumentation identity error:
mapping a NameNode RPC port to one BPOS actor assigned every DataNode's RPC
to the last created BPOS. The one affected trial is retained under
`independent-ha-hot/legacy-endpoint-collision/` and excluded from valid
totals. The replacement probe binds `BPServiceActor.run` threads to a stable
`bposN:actorM` role and records the NameNode port separately. Its healthy
trace shows RPCs from all three BPOS actors. Valid trials from the earlier
phases were audited and kept; the replacement repeated-claim phase uses a
fresh `campaign-v2` checkpoint and distinct trial directories.

The canonical case result is `result.json`. Phase checkpoints, exact fault
plans, runtime traces, per-trial coverage, elapsed time, and audits are under
`independent-coverage-io/`, `independent-ha/`, and
`independent-ha-hot/campaign-v2/`. Only source-observed RPC responses and
durable file flushes enter fault plans. The selection identity is marker,
API, actor-bound endpoint, per-endpoint ordinal, and exception type; each plan
also records the chosen later guard's BPOS, actor, and prior claim frontier.
After early mutated selectors repeatedly disappeared on replay, the hot phase
kept its completed results and changed selection priority: unstable suffixes
and repeatedly tried parents cost more, while roughly one in four later trials
still explores an observed multi-fault continuation. Strict ordered injection
and the same-actor target check remain the validity boundary.
`coverage_provenance.py` writes `coverage-provenance.json` with the absolute
node1 path and SHA-256 of every retained raw JaCoCo execution file, the
commands that produced and parsed it, and the released class and source JAR
hashes. The committed packed coverage TSVs carry the feedback used by the
fuzzer; raw JaCoCo binaries stay on node1.

The case completed 80 fault trials in 3013.249 s across the three original
JUnit phases (14 + 6 + 60). There were 108 requested fault events and 86
matched/applied events; 62 trials applied their entire ordered plan. The
selected guard ran after the last fault in 59 of those strict trials. The
largest exercised plan had three faults. Faulted runs added 27 production
method IDs, 139 branch-unit IDs, and 250 probe IDs relative to their phase
healthy baselines. The exact target `AssertionError` occurred zero times,
and there is no verified new bug for this check. The final eight hot-phase
trials added no production method/branch coverage or stable I/O family, so
the case stopped at its 80-trial budget without the conditional extension.
The phase and aggregate audits passed after coverage was packed.
