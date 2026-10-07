# Cluster unit test exception fuzzing baseline

## Scope

The campaign contains 102 selected checks: 38 HDFS 3.4.3, 30 HBase 2.6.6,
21 Solr 8.11.4, and 13 ZooKeeper 3.8.7. It also includes two separate HDFS
known-issue controls, for 104 checklist entries in total. The selected source
locations and candidate tests are in
[selection102.json](.study-repairs/unit-test-pivot/selection102.json). A
selected check is a hypothesis; a failed test alone does not establish a new
coordination bug.

Each check uses an **existing cluster based unit test from the system's own
repository**. Its original operations and assertions supply the workload. A
small runner may select the test method and start or stop recording. If no
suitable existing cluster test reaches the check, record `no_cluster_test`
and continue to the next case. If a runnable original test cannot establish
the required target state, record `no_usable_cluster_test` with the attempted
test and the exact gap. Tests that fail before the check or expect its
exception require source review before they can support a bug claim.

The counted baseline uses I/O identity and code coverage feedback. It does
not construct a causal graph, load GraphChecker runtime classes, or use Docker
clusters. Earlier experiments using those components do not count as trials
in this checklist.

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
   requested exception matched and was applied, whether the same target
   identity executed after the last fault, the target's outcome, the JUnit
   result, elapsed time, and coverage. A missed injection is an invalid trial.
   A trial that ends before the target is recorded as `lost_target` and cannot
   establish a target bug.
4. Prioritize further trials using newly observed stable I/O identities,
   target outcomes, and production code coverage. Extend a promising trial
   with one later legal fault when the budget permits. Keep the selected
   sites, hit ordinals, actual injection evidence, and clean-fixture replay
   steps in a case-local trial ledger.
5. Treat an observed fatal target outcome as a candidate. Replay its matched
   fault sequence from clean fixtures and inspect the source path and the
   test's expected behavior before calling it a new bug. A timeout, unrelated
   exception, or JUnit failure by itself is insufficient.

New campaigns start with 80 trials and at most eight ordered I/O exceptions
per sequence. If one of the last eight effective trials adds production code
coverage or a stable I/O identity, the same checkpoint may extend to 128
trials and at most ten faults. Some case controllers count only fully applied
sequences that reach the same target after the final fault as effective
trials; others use an explicit attempt budget. Record the counting rule and
any attempt cap in each case. Stop earlier if the queue of distinct valid
sequences is exhausted, and record the observed I/O scope and stop reason.
Previously completed cases retain their actual measured budgets. Report
attempts, effective trials, target-retaining trials, and measured elapsed
time separately. Healthy test execution, source mapping, and instrumentation
setup are prerequisites, not completed fuzz checks.

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
