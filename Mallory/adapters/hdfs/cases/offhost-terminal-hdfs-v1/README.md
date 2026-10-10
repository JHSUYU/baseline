# Node2 HDFS terminal evidence collector

This case-scoped collector stages HDFS-19, HDFS-20, HDFS-29 and HDFS-30 version-2 full campaigns. `cases.json` pins each existing full config SHA, exact private `/tmp` output, and separate node0/node2 dispatch state roots. It never starts Hadoop or changes a campaign. The scripts require a natural terminal `budget_exhausted` or `queue_exhausted` checkpoint/result pair.

On node2, `collect_node2.py` takes an exclusive lock on the completed campaign, hashes every raw file, checks the 5 GiB reserve plus copy/archive allowance, makes a compressed SHA manifest, runs the frozen fa5f offline audit, and atomically publishes the complete raw case. It writes `terminal-publication.json` only after verifying archive, raw, audit and canonical hashes. It can recover if interrupted between canonical rename and receipt creation.

On node0, `sync_node0.py` fetches the remote terminal receipt and verifies the archive SHA and size before transferring **only** config, result, audit, archive manifest and receipts. It checks the 5 GiB floor plus 128 MiB headroom, verifies every imported hash, then atomically publishes a compact `data/mallory/cases/<ID>` record. All trial traces and the archive remain on node2. A pre-existing different canonical case is refused.

Read-only checks passed on both hosts: `python3 -B preflight.py` validates all four case pins and `python3 -B -m unittest discover -s . -p test_collectors.py` covers terminal consistency, manifest tampering and receipt mismatch. No collector or HDFS JVM was launched while staging this package.

After dispatch starts one worker tmux, arm these watchers with the pinned manifest SHA from `release-receipt.json` (substitute the worker's actual tmux name):

```
python3 collect_node2.py --case HDFS-19 --manifest-sha 8d984734ac650f1f0d5aa641d38d76d1eefd6d20e48374bb36c92895d2120984 --worker-session <worker-tmux>
python3 sync_node0.py --case HDFS-19 --manifest-sha 8d984734ac650f1f0d5aa641d38d76d1eefd6d20e48374bb36c92895d2120984
```

Run each command in its own durable tmux. The same scripts accept HDFS-20/29/30 after their respective independent campaign admission. A failed quality audit still yields an immutable terminal result, with `report_gate_passed=false`; report generation determines final quality separately. Dispatch should not arm a watcher for a campaign whose config SHA has changed without a versioned collector manifest update.
