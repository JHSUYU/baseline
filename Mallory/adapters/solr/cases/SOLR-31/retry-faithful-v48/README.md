# SOLR-31 v48: retry-faithful, source-only staging

**State:** unbuilt and unrun. This case-local add-on does not alter the pinned v46/v47 Solr adapter, core, JUnit test, or the 102-case result. No JUnit or fault trial is authorized by this staging alone.

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
| `exhaust` | attempts 1 through the healthy-observed `retryCount` (2–12) | Every configured fault applies in one group, no low-level success before the final attempt, the real retry loop propagates ConnectionLoss to `StateWatcher`'s catch, and its cache/target operands are recorded. |

This is a **bounded diagnostic**, initially one healthy and at most one trial per plan. A physical actor change, absent watcher ordinal, extra group, different session, partial application, or missing post-success/catch evidence is `unmatched` or `inconclusive`; it is never relabeled to a different actor. The runner should give each trial a fresh output directory and an isolated node2 Solr lane flock, with source/JAR/config/plan SHA pins. Its planned ceiling is two fault trials, each at most 480 seconds; the exhaustion trial uses at most 12 exact low-level exceptions. Dispatch must admit the JVM slot after HDFS26 releases node2. No full 80-trial campaign is staged.

## Fail-closed oracle for later implementation

1. Bind trial result, plan, original class/JAR, events, JUnit log/receipt, hook logs, and source hashes. Require one successful `MALLORY_SOLR31_RETRY_WEAVE` marker with the pinned original class SHA and one class-loader identity, plus typed exact `DOOR_OBSERVED`/`FAULT_MATCHED`/`FAULT_APPLIED` IDs for each planned attempt. Check `hit=1..N` in one named watcher occurrence and one reader/client/keeper/session; verify the actual retry budget equals the plan's `N`.
2. For `transient`, require exactly one injected attempt followed by a second **successful real getData** in the same operation; distinguish any later JUnit failure from retry behavior. For `exhaust`, require N injected attempts, no success in that operation, then source's caught ConnectionLoss warning and the watcher cache `before/after` snapshots. A session change is a separate outcome, not a same-session proof.
3. Join a later `CollectionsHandler.forceLeaderElection` target operand to the **same physical node, epoch, collection, and server reader identity**. Compare its version/leader state with the independent client reader's no-leader assertion. Record selected `@1477` throw and JUnit separately. The watcher→handler relation crosses threads and is a state timeline, not an observed Mallory graph edge.
4. A new-bug claim needs both the faithful fault outcome and a version/issue novelty review; a failed JUnit or selected throw alone is insufficient.

Before any trial, build/test the add-on on an isolated source tree, pin the shaded JAR SHA, prove the transformer weaves exactly one call and the healthy trace sees low-level attempt/success markers, then freeze a calibration receipt and diagnostic config. `build_plan.py` currently has four passing offline Python tests; Java compilation/weave tests and runtime validation remain pending.
