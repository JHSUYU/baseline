> **Actor-bound campaign quality complete.** The V2 instrumentation with V3 queue selection ran 419 original JUnit fault attempts and independently verified 128 effective same-controller/PULL-core/leader postfault checks. The exact selected assertion threw zero times; no new bug is confirmed. See the [terminal audit](actor-v2/terminal/README.md). Earlier coarse-actor trials remain separate historical evidence under `legacy_coarse_actor` in `result.json`.

# SOLR-06: PULL replica leader assertion

The selected check is the assertion at `ZkController.register` line 1315 in Solr 8.11.4 source revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`:

```java
assert !(isLeader && replica.getType() == Type.PULL) : "Pull replica became leader!";
```

The original `TestPullReplica#testCreateDelete` uses two Jetty nodes with embedded ZooKeeper. Its `@Repeat(iterations=2)` creates NRT and PULL replicas for two shards, reloads the collection, and checks that a PULL replica never leads. Both original JUnit iterations passed with JVM assertions enabled.

The [healthy audit](independent/evidence/healthy-audit.json) records the original source and compiled test hashes. The independent instrumented run passed both iterations, reached the exact assertion 16 times (12 PULL, four NRT), and recorded no assertion throw. It observed `SolrZkClient` I/O against the collection's `state.json` and leader znodes before the check, including 25 `ZkController.getLeaderProps` reads of `/leaders/shard*/leader`.

The [weaver](independent/probe/weave.py) creates local copies of the original `ZkController` and `SolrZkClient` classes and compiles them ahead of the release JARs. It records the assertion predicate, collection, shard, core node, replica type, and compared leader/core URLs. It catches and rethrows only the `AssertionError` from this assertion. The original source checkout is clean. Neither the runtime classpath nor the probe reads GraphChecker or a static skeleton. JaCoCo supplies production coverage feedback.

Each fault selector uses the observed SolrZkClient operation, exact znode path, ordinal, and production caller. The probe emits adjacent matched and applied events and throws `KeeperException.ConnectionLossException` at that call. The [campaign](independent/probe/campaign.py) counts a sequence as strict only when every planned fault matches and applies in order. A post-fault target reach requires another PULL assertion for the same collection and, for a shard-specific znode, the same shard. A JUnit failure without the exact target `AssertionError` is recorded separately.

The campaign writes a resumable [checkpoint](independent/evidence/campaign/state.json) and per-trial time, JUnit result, fault plan, strict match, target reach, exception, production coverage, and new I/O feedback. The base budget is 80 trials with at most eight ordered faults; recent valid feedback can extend it to 128 trials and ten faults. Final bug marking requires raw-trace and source review of any exact assertion throw.

## Completed independent run

The 80 trials took 3,644.904 seconds in the campaign runner (3,684.277 seconds including the two measured healthy JUnit runs). The [trial ledger](independent/evidence/campaign/trial-ledger.jsonl) preserves each plan, elapsed time, JUnit exit, exact fault matching, target identity, and feedback. The [raw trace audit](independent/evidence/campaign/audit.json) independently verified 72 strict sequences and 61 with a later PULL check for the same collection and affected shard. The deepest strict target-retaining sequence applied seven faults. One eight-fault plan applied only seven and was excluded. Trials 73–80 added no new covered probe or stable I/O identity, so the conditional extension did not run.

The [production coverage summary](independent/evidence/campaign/coverage-summary.json) combines the healthy run with the 60 strict target-retaining trials that produced nonempty JaCoCo data. It found 47 new covered production methods and 227 new branch outcomes, including 219 branch outcomes in unmodified classes. Trial 30 reached the target after faults but timed out after 240 seconds and wrote no JaCoCo data; it is excluded from coverage totals. The check-specific `TARGET_EXCEPTION` event never occurred and the assertion guard was never true.

The [source audit](independent/evidence/campaign/source-audit.json) checks the original line 1315 assertion and classifies the 38 fault-run JUnit failure events as HTTP response failures, `ConnectionLoss`, cluster startup, or test-framework cleanup reports. None is the selected `Pull replica became leader!` assertion. The repaired `weave.py` was rerun after the campaign; its generated `ZkController` source and compiled class SHA-256 values matched the bytes used in the campaign exactly. Thus this bounded run found no selected target exception. The observation scope is the six hooked `SolrZkClient` operations in this original two-node test, with a global synchronized recorder that may affect timing.

The reused JUnit helper prints the cosmetic prefix `SOLR05_JUNIT_` in logs; its command and manifest identify `TestPullReplica#testCreateDelete`, and its event probe identifies `SOLR-06`.

The [raw evidence archive](independent/evidence/solr06-independent-raw-80.tar.zst) preserves both healthy runs and all 80 per-trial traces, JUnit logs, JaCoCo files, manifests, summaries, and the checkpoint. It excludes only regenerable JVM scratch directories. Its 500 entries compared byte-for-byte with the live evidence tree using `tar -d` after compression; SHA-256 is `3c3d4ec6cf3b3f6221d3f08399f0b1df39d778f1da3fc7a5af1bb4443352e81e`.

The old `/tmp/solr06-after-v4` CrashFuzz diagnostic tree is preserved separately in [legacy evidence](legacy-evidence/README.md). It did not supply instrumentation, coverage, selectors, or execution decisions for this run.
