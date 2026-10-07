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
