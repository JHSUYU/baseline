# HDFS-08: journal writer-epoch check

**Current 102-check status: independent coverage and I/O campaign complete.**
The new method and evidence are in
[`independent-coverage-io/README.md`](independent-coverage-io/README.md).
Its unchanged `testSingleWriter` reached the exact selected source guard on
the `jn2` finalizations of segments 1–3 and 4–4. After 17 independent
single-writer trials, the remaining combined budget moved to the original
`testChangeWritersLogsInSync` JUnit, which reached the `jn2` recovery
finalization of segment 1–3 under epoch 2. Both independent stages have
their own checkpoints and do not reuse the old recorder. The 64 trials described
below are historical evidence in `legacy-graph-result.json`. Their I/O
recorder was GraphChecker-prewoven; the first 48 trials also loaded a region
skeleton. They do not count toward the independent campaign.

The independent campaign completed 80 trials in 1,469.479 measured active
seconds: 77 strictly injected, 69 retaining the exact `jn2` segment guard
after the final fault, and zero exact target exceptions or confirmed new bugs.
Combined new HDFS production coverage was 17 method IDs and 35 branch units.
The final eight trials added no new method, branch unit, or stable I/O family;
therefore the conditional 128-trial extension did not apply. The case result,
both checkpoint stages, combined ledger, and 80-trial audit are in the linked
independent directory. The historical 64 prewoven trials are excluded from all
these counts.

The selected Hadoop 3.4.3 check is `Journal.checkRequest(RequestInfo)` in
`hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java`.
The guard starts at line 486 and throws `IOException` at line 487 when a
request epoch is below the JournalNode's promised epoch. In the original
second-writer test, the selected runtime invocation is the `jn2` call made
by `Journal.finalizeLogSegment` during
`QuorumJournalManager.recoverUnfinalizedSegments(phase=2)`. A stale writer
being fenced is expected behavior; an exact exception would require source
review and same-selector replay before any bug claim.

## Historical workload and budget (GraphChecker-prewoven recorder)

The unchanged `TestQuorumJournalManager#testSingleWriter` and
`#testChangeWritersLogsInSync` JUnit methods use their original embedded
three-JournalNode `MiniJournalCluster`. There is no Docker or handwritten
cluster workload. The case reached its 64-trial budget with a configured
six-fault sequence cap. The longest requested sequence had four faults;
the longest strictly injected sequence retaining the target had three.
No production method/branch outcome or I/O family appeared in trials 48–64,
so the conditional 128-trial extension was not triggered.

| Metric | Result |
| --- | ---: |
| Trials | 64 |
| Requested / matched / applied fault events | 116 / 104 / 104 |
| Strictly injected trials | 60 |
| Strict trials reaching the exact guard after the last fault | 48 |
| Exact target exceptions after fault | 0 |
| Confirmed new bugs | 0 |
| Measured campaign time, excluding the pause between sessions | 1223.689 s |

The four non-strict trials are 49–52. They reused a selector observed after
a fault under the earlier recorder mode; its retry occurrence did not match
under the new mode. They remain recorded as attempts and were never rerun.
Trials 53–64 seeded from healthy I/O or mutated I/O observed in the new mode.
Strict trials that lost the target after fault were discarded from mutation.

The healthy comparison in
[`discovery-validation-healthy/validation.json`](discovery-validation-healthy/validation.json)
confirmed the same selected guard, all 141 exact healthy I/O selector IDs,
and all 195 HDFS production method/branch IDs after removing the runtime
skeleton. Phase-relative production coverage gains were 15 for single-writer
RPC, 16 for single-writer epoch files, and six for multi-writer recovery;
these totals have different healthy seeds and must not be added.

## Instrumentation provenance

Fault selection and feedback use observed RPC/file I/O, production method
and branch outcomes, and the exact runtime target identity. They do not
read a concolic region plan, static scope map, or closure graph. The first
48 completed trials nevertheless used a GraphChecker-prewoven recorder in
`region-state` mode and loaded a region skeleton. Trials 49–64 used the
same prewoven probe artifact in `discovery` mode with no runtime skeleton
or graph aggregation. I/O occurrence addresses still contain region-formatted
text from that artifact. Therefore this case is **not fully independent of
GraphChecker instrumentation**, even though its fault decisions are graph
free. The two segments are explicitly marked in the checkpoint and trial
table.

[`coverage-io-trials.csv`](coverage-io-trials.csv) records every legacy trial's
duration, requested/matched/applied counts, target retention, coverage gain,
bug mark, selector IDs, and trace path. The resumable
[`coverage-io-checkpoint.json`](coverage-io-checkpoint.json) holds legacy
selectors and feedback; the current [`result.json`](result.json) feeds the
102-check table from the independent campaign. Each legacy completed trial
has its own manifest and result. The old 40-trial
`trial-summary.csv` is retained as historical evidence.

For adjacent journal checks, the immutable HDFS 3.4.3 distribution and
`deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar` can be used read only.
The historical graph-dependent runner has been removed. The current
case-local runner is `independent-coverage-io/system-test/run_original.py`,
and its resumable controller is
`independent-coverage-io/campaign/run_campaign.py`. Exact target identity
and oracle must be defined again for each different check; HDFS-08's
negative result does not transfer to another site.
