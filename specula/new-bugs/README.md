# New bugs found by Specula's ad hoc runs (tier A and B, 25)

Specula ran once on each of 84 ad hoc coordination checks (HDFS 36, ZooKeeper 16, HBase 19, Solr 13), on each system's current code. These are the bugs that are **real, severe, new, and make the ad hoc check fail**: 7 tier A, 18 tier B (HDFS 11, ZooKeeper 7, HBase 7, Solr 0).

- **Tier A:** default configuration, a realistic trigger, severe impact.
- **Tier B:** real and severe, but a narrower trigger (non-default config, a rare procedure or fault combination, a narrow timing window) or lower severity or confidence.

How each was verified: Specula reproduced it in the real system on the unmodified base; an independent reviewer then checked it against the source; then the operator re-read the decisive code. Root causes with file:line citations are in `../data/<system>/VERIFIED-BUGS.md`, and the per-check results (all 84 checks, with time, tokens and cost) are in `../data/<system>/REPORT.md`.

## Each folder

- `BUG.md`: the explanation (verified defect, consequence, trigger, and Specula's own cause/trigger/consequence), the evidence, and the cost.
- `tlc/`: the TLA+ modules, the config that produced the counterexample, the counterexample log, and `RERUN.md` with the TLC command (jars in `../data/tlc/`, JDK 21). Code-review findings (no TLC) have no `tlc/`.
- `repro/`: the tests and scripts run in the real system, and their (small) logs.
- `confirmation/`: Specula's verdict, investigation and issue for the finding.

All 22 TLC counterexamples were rerun from these published copies on 2026-11-09: each reports the expected violation (`rerun-results.tsv`).

## Cost

- **Run:** the whole Specula run of the check that found the bug, all phases. Time is active time (quota sleeps excluded). Several bugs share a run.
- **Confirm:** the part of the run spent confirming that finding (Phase 4).

Totals: 17 runs, 74h25m, 3481.0M tokens, $2,137.35; confirmation of the 25 findings 251.6M tokens, $196.47.

| tier | system | bug | folder | TLC | run time | run tokens | run cost | confirm tokens | confirm cost | same defect as |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| A | hbase | truncate_region force-detaches a concurrent move's TRSP; region stuck CLOSING, unserved | [`hbase-adhoc-11-MC-3`](hbase-adhoc-11-MC-3/BUG.md) | yes | 6h41m | 159.1M | $132.53 | 2.3M | $5.26 | 10/CR-1 |
| A | hdfs | JN purge marks a restarted JN's live segment .stale; an acknowledged edit is lost after failover | [`hdfs-adhoc-07-MC-1`](hdfs-adhoc-07-MC-1/BUG.md) | yes | 5h48m | 303.2M | $159.65 | 27.6M | $13.15 |  |
| A | hdfs | epoch selection reads only a quorum's promises; a JN fences the new writer for its whole term | [`hdfs-adhoc-08-MC-1`](hdfs-adhoc-08-MC-1/BUG.md) | yes | 5h53m | 253.0M | $148.60 | 23.7M | $11.60 |  |
| A | hdfs | FileChecksumHelper retry does not restore `remaining`; getFileChecksum silently returns a wrong checksum | [`hdfs-adhoc-11-MC-4`](hdfs-adhoc-11-MC-4/BUG.md) | yes | 6h18m | 470.5M | $259.50 | 17.7M | $10.17 |  |
| A | hdfs | disk formatted during an unfinalized upgrade gets the new cTime and no previous/; rollback cannot complete | [`hdfs-adhoc-24-MC-2`](hdfs-adhoc-24-MC-2/BUG.md) | yes | 6h09m | 552.9M | $297.19 | 19.9M | $9.22 | 26/MC-3 |
| A | hdfs | LAZY_PERSIST inherited by existing files; append refused, scrubber deletes DISK files | [`hdfs-adhoc-38-MC-1`](hdfs-adhoc-38-MC-1/BUG.md) | yes | 3h04m | 140.2M | $82.19 | 7.0M | $6.77 | 38/MC-2 |
| A | zookeeper | silent, durable delete of a client's PERSISTENT znode; default config | [`zk-adhoc-b3-MC-1`](zk-adhoc-b3-MC-1/BUG.md) | yes | 2h49m | 100.6M | $74.96 | 2.4M | $3.07 | b3/CR-2 |
| B | hbase | new master forgets a quota DISABLE; raising the limit does nothing | [`hbase-adhoc-04-MC-3`](hbase-adhoc-04-MC-3/BUG.md) | yes | 2h38m | 101.1M | $67.38 | 3.2M | $3.63 |  |
| B | hbase | recovered namespace delete races quota init; the new master aborts | [`hbase-adhoc-08-MC-1`](hbase-adhoc-08-MC-1/BUG.md) | yes | 3h10m | 137.0M | $88.01 | 3.3M | $3.60 |  |
| B | hbase | rsgroup: meta assignment needs the namespace cache, which needs meta; master aborts | [`hbase-adhoc-08-MC-3`](hbase-adhoc-08-MC-3/BUG.md) | yes | 3h10m | 137.0M | $88.01 | 4.4M | $4.35 |  |
| B | hbase | split admits a CLOSED parent; rollback sets OPEN with no location; assign refused | [`hbase-adhoc-11-MC-2`](hbase-adhoc-11-MC-2/BUG.md) | yes | 6h41m | 159.1M | $132.53 | 3.7M | $3.68 |  |
| B | hbase | master rebuild counts region replicas, creates reserve primaries; valid creates refused after every restart | [`hbase-adhoc-21-MC-4`](hbase-adhoc-21-MC-4/BUG.md) | yes | 2h33m | 41.4M | $44.58 | 2.0M | $2.42 | 22/CR-1 |
| B | hbase | crashed RS both online and dead after failover; stays online for good, cluster shutdown never completes | [`hbase-adhoc-31-MC-3`](hbase-adhoc-31-MC-3/BUG.md) | yes | 4h21m | 99.3M | $79.00 | 7.3M | $6.25 |  |
| B | hdfs | Journal.doRollback does not refresh cached epochs; a JN left up through rollback fences the next writer | [`hdfs-adhoc-08-MC-2`](hdfs-adhoc-08-MC-2/BUG.md) | yes | 5h53m | 253.0M | $148.60 | 21.3M | $11.49 |  |
| B | hdfs | heartbeat returns early in safe mode before the key update; encrypted reads fail after ~10 h | [`hdfs-adhoc-11-MC-1`](hdfs-adhoc-11-MC-1/BUG.md) | yes | 6h18m | 470.5M | $259.50 | 19.7M | $9.55 |  |
| B | hdfs | derived-QOP re-signs the forwarded token with the DN's key and keeps the keyId | [`hdfs-adhoc-14-MC-1`](hdfs-adhoc-14-MC-1/BUG.md) | yes | 4h11m | 314.4M | $152.01 | 4.9M | $23.42 |  |
| B | hdfs | failed block-pool dir still finalized; a volume that missed -rollback loses previous/ | [`hdfs-adhoc-24-CR-6`](hdfs-adhoc-24-CR-6/BUG.md) | code review | 6h09m | 552.9M | $297.19 | 32.1M | $24.01 | 24/CR-2, 26/MC-2 |
| B | hdfs | stale rolling-upgrade marker makes doFinalize delete a regular upgrade's previous/ | [`hdfs-adhoc-24-MC-3`](hdfs-adhoc-24-MC-3/BUG.md) | yes | 6h09m | 552.9M | $297.19 | 14.9M | $8.94 |  |
| B | hdfs | DN doUpgrade deletes an existing previous/; a DN down during one rollback is silently re-upgraded | [`hdfs-adhoc-26-MC-1`](hdfs-adhoc-26-MC-1/BUG.md) | yes | 4h10m | 429.8M | $236.47 | 15.1M | $8.65 |  |
| B | zookeeper | read-only server serves never-committed txns (run incomplete) | [`zk-adhoc-04-MC-2`](zk-adhoc-04-MC-2/BUG.md) | yes | 5h38m | 128.8M | $96.51 | 4.1M | $7.48 |  |
| B | zookeeper | one failed epoch write leaves SNAP sync mode; an observer is wedged for good | [`zk-adhoc-11-CR-1`](zk-adhoc-11-CR-1/BUG.md) | code review | 4h56m | 110.2M | $96.99 | 2.3M | $2.73 |  |
| B | zookeeper | stop during sync skips the epoch write; the peer can never restart | [`zk-adhoc-11-MC-3`](zk-adhoc-11-MC-3/BUG.md) | yes | 4h56m | 110.2M | $96.99 | 3.0M | $3.61 | b5/MC-2 |
| B | zookeeper | offer vanishes between list and read; participant goes FAILED and blocks the election | [`zk-adhoc-b2-MC-1`](zk-adhoc-b2-MC-1/BUG.md) | yes | 2h45m | 84.2M | $61.38 | 1.5M | $2.46 | b2/MC-3 |
| B | zookeeper | after a live restore the manager scans the old tree forever and deletes restored nodes | [`zk-adhoc-b3-CR-3`](zk-adhoc-b3-CR-3/BUG.md) | code review | 2h49m | 100.6M | $74.96 | 2.3M | $2.72 |  |
| B | zookeeper | ObserverMaster eviction empties the queue and skips the gap check; observer silently misses a commit | [`zk-adhoc-b6-MC-3`](zk-adhoc-b6-MC-3/BUG.md) | yes | 3h21m | 55.3M | $60.40 | 5.9M | $8.24 |  |
