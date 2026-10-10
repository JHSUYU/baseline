# SOLR-38 sealed healthy trace: unique writer audit

This is an **offline audit** of the immutable SOLR-38 v2 healthy cluster JUnit evidence. It runs no JVM and does not modify the Solr test, Mallory graph, fault controller, or checklist. The input archive is `data/mallory/evidence_archives/SOLR-38-election-value-healthy-node1-v2.tar.gz` (SHA-256 `954568a43a7b07f48d4185bde044b19d9a1e371ebf042174ad87f2a151a34763`). The audit pins the extracted campaign result, compressed trace, Solr source files, diagnostic adapter source and JAR, agent JAR identity, and passing JUnit/runtime attestation.

## Exact source path

* `ShardLeaderElectionContext.waitForReplicasToComeUp` has the typed ZooKeeper `getChildren` door at line 396. In the same `runLeaderProcess` invocation, line 264 calls `CloudDescriptor.setLeader(true)`.
* `CloudDescriptor.isLeader` is a private volatile boolean initialized false at line 43. The sole direct source assignment to this field is in `setLeader` at line 101; getter line 97 returns it. Other callers, including election reset and `ZkController`, must use the setter. The audit pins the entire `CloudDescriptor.java` file hash and rejects additional observed native writes on each target descriptor.
* The diagnostic adapter duplicates the actual setter argument and getter return from the JVM stack. It also reports the descriptor reference. The audit pins both adapter source files and verifies the compiled adapter JAR in the sealed archive.
* `DistributedZkUpdateProcessor.doDefensiveChecks` assigns `localIsLeader` only from `cloudDesc.isLeader()` at lines 982 and 1013. The branch at line 1021 consumes this local. Its source file is pinned. A diagnostic getter return in the same exact target invocation therefore identifies the value consumed at the branch; the target event itself has no object field.

For each target check, the audit requires one typed door, one setter write of `true`, the same descriptor object in the native setter event and getter event, a duplicated getter return of `true`, the same node, epoch and JVM thread, and nested region intervals around the election and target operations. It checks the *last* native writer before that read and rejects an intervening or competing native write for that descriptor across the complete trace. The native write/read sampled version equality is corroboration only; it is not treated as an exact read-from token.

The sealed result has **12 target checks and 12 source-backed unique-writer witnesses** on descriptor objects `o24` and `o37`; the native Mallory graph still has **0 strict door-to-target paths**. The healthy test passed and no fault was injected in this run. These facts make a bounded fault pilot a candidate for separate exploratory review. They do not authorize a full campaign or establish a bug. The controller would need to ingest and validate an explicit source-backed state edge, or a later instrumentation stage would need an exact read-from token, before this path can count as native strict closure.

## Reproduce the offline audit

Extract the pinned archive into a temporary directory, then run:

```sh
python3 Mallory/adapters/solr/cases/SOLR-38/election-unique-writer-audit-v1/audit.py \
  /tmp/solr38-v2-sealed/SOLR-38-election-value-healthy-node1-v2
python3 Mallory/adapters/solr/cases/SOLR-38/election-unique-writer-audit-v1/test_offline.py
```

`sealed-audit-result.json` records each event ID, object, node, thread, writer version, last writer, zero intervening writes, target outcome, and native strict-path result. The nine offline tests include negative controls for wrong object, extra writer, wrong thread, wrong exception, false getter return, mismatched target invocation, truncated trace, and changed source.
