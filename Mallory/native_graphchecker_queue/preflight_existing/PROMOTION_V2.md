# Durable native 102-case queue v2

The promoted runtime is `/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2` on the shared project mount. `data/mallory/native_graphchecker_queue/promotion-v2.json` and `promotion-v2-manifest.json` pin the snapshot, inventory, 102-case physical ownership, isolation policy, eight native bindings, launch scripts, pilot, and adopted completion receipts by SHA-256. The repo-data `native-102-results.{json,tsv}` is an atomic snapshot from this runtime; refresh it from the durable exporter when a verified completion changes.

The eight bindings are ZOOKEEPER-01/02/07, HDFS-11/29/30, SOLR-01, and HBASE-02. A binding references its existing native config and trial root; promotion does not copy or modify running campaign state. ZOOKEEPER-07 and HDFS-11 were fully audited from immutable native trial receipts and adopted without another JUnit run. HDFS-11 finished its time budget with 15 strict target-retained trials and no target throw; its separate terminal review records incomplete SASL value provenance and no new closure edge families. Running cases have no queue completion receipt.

HDFS-29's guard is Jimple #u4 at source line 577 and its exact inventory throw is #u12 at line 578. Its binding pins `target-identity-audit.json`; the dispatcher also requires every bound config's exact throw site and exception to match the inventory. HDFS-30 uses guard #u14 and exact inventory throw #u23. Its binding pins the source and healthy-result attestation for the unchanged `TestLeaseRecovery#testBlockSynchronization` JUnit, which differs from the inventory's recorded HA selector.

The isolation profile uses ZK's disjoint assigned ports, HDFS-11/29/30 and SOLR-01 case-scoped source reviews of port-zero listeners, and HBASE-02's source-reviewed random ZooKeeper port with bind retry. Each JUnit has its own `{trial_workdir}` for temp and cluster data. The queue rejects observed bind collisions before publishing a completion. The direct native campaign `.campaign.lock` prevents a queue worker from starting a second run of an active case. There are two independent queue slots per physical host.

Run or resume one host wave inside a retained tmux session:

```bash
tmux new-session -d -s native102_node0_v2 /proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2/tmux-host-session.sh node0
```

Use the matching `node1` or `node2` command on those hosts. The session runs `run-host-once.sh`, then keeps an idle shell for manual successor runs. There is no polling loop. The launcher sets `PYTHONPATH` to the immutable shared Python snapshot and passes the pinned inventory, ownership, config, state, scratch, results, isolation, pilot, and `--slots 2` arguments. Controller PID/worker PID/exit receipts are in `state/.native-queue/controllers/HOST.json`, with timestamped logs beside them. `state/.native-queue/attempts/CASE-ID` records any queue-started native campaign.

A new case remains pending until a native config, original JUnit preparation, per-case port review, and isolated build inputs are present. Existing terminal cases are imported once by receipt and fingerprint; future invocations skip their JUnit. The queue's 102-row exporter includes live checkpoint observations, but only an audited `native_tested_complete` receipt is a completed fuzz result. Candidate target exceptions are separate from independently confirmed new bugs.

Verification without a distributed JUnit:

```bash
python3 -m unittest Mallory.native_graphchecker_queue.test_queue Mallory.native_graphchecker_queue.test_results Mallory.native_graphchecker_queue.preflight_existing.test_audit -v
```
