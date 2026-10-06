# GraphChecker guided exception fuzzing for ad hoc checks

## Scope

The campaign contains 102 selected checks: 38 HDFS 3.4.3, 30 HBase 2.6.6,
21 Solr 8.11.4, and 13 ZooKeeper 3.8.7. The selected source locations and
proposed original tests are in
[selection102.json](.study-repairs/unit-test-pivot/selection102.json). A
selected check is a hypothesis, not a confirmed coordination bug.

Each check uses an **existing cluster based unit test from the system's own
repository**. The test's original operations and assertions remain the
workload. A small generic JUnit runner or recording adapter may open a trace
window around that test. If no suitable existing cluster test reaches the
exact check, record `no_cluster_test` and move to the next check. Tests that
fail before the target or intentionally expect the target exception need
separate source review before they can support a bug claim.

## One check's execution

1. Pin the system version, test method, exact target branch/throw, and
   GraphChecker static scope. Start the original embedded cluster test from
   a clean fixture with no injected fault. Verify the target check's region
   and nonfatal branch in the trace.
2. Use GraphChecker's static analysis and bytecode weaving to record method,
   branch, asynchronous, RPC/message, and state provenance events. Build the
   runtime causal graph and compute the backward closure rooted at the exact
   target occurrence. Runtime node identity and cross-boundary links must be
   explicit; an unregistered node or missing transport edge is a graph gap.
3. Collect fault markers in that closure, plus method and branch coverage.
   A trial selector names the I/O site, region occurrence address, marker,
   and hit ordinal. Inject an exception only when that selector matches.
4. Rerun the **same original unit test** from a clean fixture. Record whether
   every requested exception was actually applied, whether the target region
   still exists afterward, and whether its exact fatal check was reached.
   Rebuild the graph and coverage from this trial. Append one later legal
   fault to promising sequences and prioritize new target closure behavior
   and branch outcomes, with bounded exploration of globally new coverage.
5. A fatal target outcome is a candidate observation. Replay the same matched
   sequence from clean fixtures and inspect the specific source path before
   marking a new bug. A test failure, timeout, or unrelated exception alone
   does not satisfy the target oracle.

A trial that removes the target region is recorded as `lost_target` and is not
used as evidence for that check. The trial queue stops when its per-check
budget expires or there is no valid sequence left. The budget is set for the
runtime of the original test and the size of its target closure; the recorded
elapsed time and effective trials, not a requested budget, are reported.

## Isolation and progress

One agent owns one check at a time. At most ten agents run concurrently,
including the coordinator. Each case has its own GraphChecker worktree,
source/test workspace, temporary directory, trace, fault selectors, and
`cases/<CASE-ID>/result.json`. A case lease prevents two agents from running
it at once. Results are written atomically; after interruption the campaign
resumes unfinished work and skips terminal cases.

[checklist102.md](.study-repairs/unit-test-pivot/checklist102.md) records the
system, file, function, check code, chosen original test, elapsed time,
strictly applied fault trials, target-after-fault count, coverage feedback,
and bug review state for every selected check. Source mapping and a healthy
unit test alone do not count as a high quality completed fuzz check.
