# SOLR-31 v48: retry-faithful, source-only staging

**State:** built and offline weave-checked. Two no-fault calibrations on node2 passed the original JUnit, reached the exact target without throwing, and observed low-level attempts on the target server reader. Two initial and two later bounded diagnostics did not satisfy same-reader postfault target matching. This case-local add-on does not alter the pinned v46/v47 Solr adapter, core, JUnit test, or the 102-case result.

## Exact boundary

Use the existing `ForceLeaderTest#testReplicasInLowerTerms` workload. The pristine Solr 8.11.4 distribution `solr-solrj-8.11.4.jar` has SHA-256 `b274e65f3607224b3337e9fc797137d8093c7981bcb54b695644dfd5d2242517`. Its original `SolrZkClient.class` has SHA-256 `51b3131fed142509b80da408d0d3f8d036045237b51a48c2a4dd9cf574a72dc0`. `javap -p -c` shows exactly one `SolrZooKeeper.getData(String,Watcher,Stat)` call in instance method `lambda$getData$6(String,Watcher,Stat):byte[]`; source `SolrZkClient.java:346-351` places that lambda inside `ZkCmdExecutor.retryOperation`. The add-on transformer inserts a hook immediately before **that low-level invocation** and an observation after a successful return. Unlike v46/v47's `ZkStateReader.fetchCollectionState` call-site hook, an injected `ConnectionLossException` here is caught by the real `ZkCmdExecutor.retryOperation` loop (`ZkCmdExecutor.java:68-95`). It does not modify ZooKeeper, Solr, or the JUnit workload.

Load the normal adapter first, then the add-on:

```properties
adapter.transformers=edu.uva.liftlab.mallory.solr.SolrTransformer,edu.uva.liftlab.mallory.solr31.RetryAttemptTransformer
adapter.jars=/absolute/pinned/mallory-solr-adapter-v46.jar,/absolute/pinned/mallory-solr31-retry-attempt.jar
```

Keep `SolrZkClient` out of the generic agent's `agent_include` so this add-on receives the original class bytes and can require their pinned SHA. The existing `ZkStateReader` and `CollectionsHandler` target instrumentation stays as in v46. The add-on's `MALLORY_SOLR31_RETRY_WEAVE` marker records the original class SHA and loader; no Java trial is admitted if it is absent or mismatched.

The add-on qualifies only `/collections/forceleader_lower_terms_collection/state.json` inside a registered `ZkStateReader.StateWatcher.refreshAndWatch` region. It checks the original watcher, its owning reader, the same `SolrZkClient`, a named physical node/epoch, and a readable keeper session/retry count. Every low-level attempt logs its physical node, epoch, numeric thread, watcher occurrence, collection/path, reader/client/keeper identities, ZooKeeper session ID, read ordinal, attempt number, retry budget, and post-success `Stat` version. A changed keeper/session or retry budget stops further fault injection in that read; the verifier must reject mixed-session evidence.

With no `MALLORY_SOLR31_RETRY_*` selector variables, a fresh **healthy** trial observes all qualified low-level doors without injecting. After a healthy receipt establishes one physical node, epoch, reader, session, watcher-read ordinal, and the actual retry count, a diagnostic sets all three variables `MALLORY_SOLR31_RETRY_ACTOR`, `MALLORY_SOLR31_RETRY_EPOCH`, and `MALLORY_SOLR31_RETRY_READ_ORDINAL`. A partial selector fails closed. `build_plan.py` then writes a standard exact FaultPlan with `point.hit` values within that watcher occurrence:

| Plan | Injected low-level attempts | Required control observation |
| --- | --- | --- |
| `transient` | attempt 1 only | Same node/epoch/reader/client/keeper/session/stat and occurrence; attempt 2 succeeds, `Stat`/cache advances, and the JUnit/target result is recorded separately. |
| `exhaust` | attempts 1 through the healthy-observed `retryCount` (2–16) | Every configured fault applies in one group, no low-level success before the final attempt, the real retry loop propagates ConnectionLoss to `StateWatcher`'s catch, and its cache/target operands are recorded. |

This is a **bounded diagnostic**, initially one healthy and at most one trial per plan. A physical actor change, absent watcher ordinal, extra group, different session, partial application, or missing post-success/catch evidence is `unmatched` or `inconclusive`; it is never relabeled to a different actor. The runner should give each trial a fresh output directory and an isolated node2 Solr lane flock, with source/JAR/config/plan SHA pins. Its planned ceiling is two fault trials, each at most 480 seconds; the exhaustion trial uses at most 16 exact low-level exceptions. No full 80-trial campaign is staged.

## Fail-closed oracle for later implementation

1. Bind trial result, plan, original class/JAR, events, JUnit log/receipt, hook logs, and source hashes. Require one successful `MALLORY_SOLR31_RETRY_WEAVE` marker with the pinned original class SHA and one class-loader identity, plus typed exact `DOOR_OBSERVED`/`FAULT_MATCHED`/`FAULT_APPLIED` IDs for each planned attempt. Check `hit=1..N` in one named watcher occurrence and one reader/client/keeper/session; verify the actual retry budget equals the plan's `N`.
2. For `transient`, require exactly one injected attempt followed by a second **successful real getData** in the same operation; distinguish any later JUnit failure from retry behavior. For `exhaust`, require N injected attempts, no success in that operation, then source's caught ConnectionLoss warning and the watcher cache `before/after` snapshots. A session change is a separate outcome, not a same-session proof.
3. Join a later `CollectionsHandler.forceLeaderElection` target operand to the **same physical node, epoch, collection, and server reader identity**. Compare its version/leader state with the independent client reader's no-leader assertion. Record selected `@1477` throw and JUnit separately. The watcher→handler relation crosses threads and is a state timeline, not an observed Mallory graph edge.
4. A new-bug claim needs both the faithful fault outcome and a version/issue novelty review; a failed JUnit or selected throw alone is insufficient.

The shaded add-on JAR SHA-256 is `6da147e58b84ad600366b0cf54247fda317bb42090854abe1bc40d08a8f42059`. `RetryAttemptTransformerSmoke` checked one before/after hook pair in the pinned `SolrZkClient.class` and rejection of modified class bytes. `build_plan.py` has four passing offline Python tests. The node2 healthy run is `data/mallory/solr31_retry_v48_healthy_node2/SOLR-31`, with its selected binding in `healthy-receipt.json`: physical `shard-1`, epoch 0, same reader as the target, watcher read ordinal 2, actual retry count 14. That healthy read observed `state.json` version 5; the target later observed version 8 and no leader. The copied healthy evidence on node0 matches all four SHA-256 values in the receipt.

The transient trial at `data/mallory/solr31_retry_v48_transient_node2` applied one exact `ConnectionLossException` to the selected low-level attempt. Solr's real retry loop made a second attempt on the same reader/session and succeeded. The original JUnit then failed while waiting for a replica to become `down`; it never reached the selected FORCELEADER check. The exhaustion trial at `data/mallory/solr31_retry_v48_exhaust_node2` applied eight of the planned fourteen exceptions before the JUnit failed waiting for the collection to become active. It likewise never reached the selected check. Both are **unmatched diagnostics**, not bug detections. The evidence contains plans, typed events, JUnit logs, and diagnostic results. A later candidate would need a watcher read closer to the leader-removal transition while retaining the target on the same server reader.

The bounded late-window finder stopped at its first admitted seed. Its unchanged
JUnit passed, and the same `shard-2` reader observed watcher read ordinal 5 at
`state.json` version 8 before reaching the target at version 8 with no leader.
The receipt is in `data/mallory/solr31_retry_v48_late_healthy_node2/seed-01/SOLR-31`.
The subsequent transient diagnostic applied its sole exact exception, observed
the real second-attempt success on that reader/session, and passed the JUnit;
the selected target instead ran on the `control` reader, so this is **not** a
same-reader postfault target result. It took 50.306 s. The later exhaustion
diagnostic took 51.039 s, passed the JUnit, and reached the target on another
reader, but its selected ordinal-5 watcher read never occurred and none of its
14 planned faults applied. Both diagnostic results are preserved under
`data/mallory/solr31_retry_v48_late_{transient,exhaust}_node2`. These trials
show a fresh-cluster actor/timing alignment gap, not a target throw or bug.
