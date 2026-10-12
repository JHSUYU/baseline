# SOLR-09 directed three-fault replay

`run.py` runs the original `DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`
in a fresh embedded Solr cluster for each trial. It first requires a passing
healthy test with all three exact adapter doors. It then repeats one fixed,
role-relative plan:

1. `IOException` at the CoreAdmin `UNLOAD` request in `ShardRequestor.call`.
2. `ConnectionLossException` at the first matching state-watch `getChildren`
   after fault 0, on the same named node and epoch.
3. `ConnectionLossException` at the second matching state-watch `getData`
   after fault 1, on that same node and epoch.

The optional `--data-scope all` plan uses the same `fetchCollectionState`
callsite but includes direct collection-state reads outside a watch callback.
It requires a separate `--output` directory so the two plans cannot share
trial numbers or receipts. `--data-hit 1` can test the first matching read;
the default of 2 matches the earlier witness. Each variant needs its own
output directory, and the script checks for plan drift on resume.

`--post-data-hit 1` adds a fourth fault on the next same-node collection-state
read after fault 2. This mutation follows the new read observed between fault
2 and the target in the three-fault replay. It also requires its own output
directory and is a directed follow-up, not an automatically discovered plan.

The plan comes from the prior [CrashFuzz witness](../../../../../../crashfuzz/cases/SOLR-09/actor-v2/CANDIDATE-059.md).
This replay checks whether the current Mallory instrumentation and graph
feedback preserve the witness. It is not evidence that Mallory independently
discovered the plan. Each trial records exact fault receipts, target outcome,
JUnit result, duration, and a trace hash. `summary.json` is rewritten after
each completed trial, so rerunning the script resumes at the next trial.

Run after building the current instrumentation and Solr adapter jars, while
the node0 Solr and shared source lanes are free:

```sh
python3 Mallory/adapters/solr/cases/SOLR-09/targeted-replay-v1/run.py --trials 8
```

The script pins both jars in `data/mallory/solr09_targeted_replay_v1_node0/`
and holds both lane locks. A target exception is a candidate observation;
source review and a healthy comparison are required for a bug conclusion.
