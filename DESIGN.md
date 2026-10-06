# Cluster unit test exception fuzzing baseline

## Scope

The campaign contains 102 selected checks: 38 HDFS 3.4.3, 30 HBase 2.6.6,
21 Solr 8.11.4, and 13 ZooKeeper 3.8.7. The selected source locations and
candidate tests are in
[selection102.json](.study-repairs/unit-test-pivot/selection102.json). A
selected check is a hypothesis; a failed test alone does not establish a new
coordination bug.

Each check uses an **existing cluster based unit test from the system's own
repository**. Its original operations and assertions supply the workload. A
small runner may select the test method and start or stop recording. If no
suitable existing cluster test reaches the check, record `no_cluster_test`
and continue to the next case. Tests that fail before the check or expect its
exception require source review before they can support a bug claim.

## One check's execution

1. Pin the system version, original test method, target source location,
   target guard, and exception outcome. Run the test from a clean fixture
   without an injected fault. Confirm that the exact target executes and
   record its observed nonfatal outcomes and baseline method, branch, and
   line coverage where available.
2. Instrument exception capable I/O calls exercised by that workload,
   including file, network, RPC, and storage operations relevant to the
   target. Record each site's stable identity, operation, node or process,
   invocation count, exception type, and whether it executed. Validate each
   injected exception type against the call site's declared behavior.
3. Select a concrete observed I/O site and hit ordinal, then rerun the
   **same original unit test** from a clean fixture. Record whether the
   requested exception matched and was applied, whether the target executed
   afterward, the target's outcome, the JUnit result, elapsed time, and
   coverage. A missed injection is an invalid trial. A trial that ends before
   the target is recorded as `lost_target` and cannot establish a target bug.
4. Prioritize further trials using newly observed target outcomes and method,
   branch, or line coverage. Extend a promising trial with one later legal
   fault when the budget permits. Keep the selected sites, hit ordinals,
   actual injection evidence, and clean-fixture replay steps in a case-local
   trial ledger.
5. Treat an observed fatal target outcome as a candidate. Replay its matched
   fault sequence from clean fixtures and inspect the source path and the
   test's expected behavior before calling it a new bug. A timeout, unrelated
   exception, or JUnit failure by itself is insufficient.

The default budget is 48 fault trials with at most four I/O exceptions in a
sequence. If new production coverage or a new I/O family still appears near
that limit, extend the same checkpoint to 96 trials and at most six faults.
Stop earlier only after recording why the observed relevant I/O families are
equivalent or exhausted. Report effective trials and measured elapsed time.
Healthy test execution, source mapping, and instrumentation setup are
prerequisites, not completed fuzz checks.

## Parallel execution and progress

Each agent owns one case at a time. Agents use separate source/test
workspaces, temporary directories, logs, and case-local fault plans. A case
lease prevents duplicate execution. Results are written atomically so an
interrupted campaign can resume unfinished cases while retaining completed
trial records.

[checklist102.md](.study-repairs/unit-test-pivot/checklist102.md) records the
selected location, original test, elapsed time, applied fault trials,
target-after-fault observations, coverage feedback, and bug review state for
every check. The per-case `result.json` and trial ledger hold the supporting
evidence.
