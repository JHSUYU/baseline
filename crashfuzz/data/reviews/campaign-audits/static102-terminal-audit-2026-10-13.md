# Original 102 terminal audit

The final table is [`data/crashfuzz/static102-rerun.tsv`](../../static102-rerun.tsv). It records the unchanged JUnit cluster workload, Soot selection, generic fault campaigns, per-check cumulative elapsed time, and source-reviewed target exception observations. The table was regenerated from durable case summaries, migration records, offload receipts, and `static102-target-exception-reviews.json`; no completed trial was rerun to make this audit.

## Terminal distribution

| Status | Checks | Interpretation |
| --- | ---: | --- |
| `budget_or_queue_complete` | 75 | Campaign ended after budget or queue exhaustion. This does not by itself prove the check was exercised under every fault. |
| `no_valid_target_trial` | 22 | At least one strict fault applied, but no trial reached the target after a fault according to the old target-reach hook. Coverage gap. |
| `no_cluster_test` | 4 | No suitable unchanged JUnit cluster test: HBASE-23, HDFS-13, ZOOKEEPER-08, ZOOKEEPER-09. |
| `candidate_review` | 1 | HBASE-27: three target exceptions reviewed as expected shutdown after injected master startup failure. |

All 102 rows have unique IDs, exact source file/function/line/site, terminal `finished=True`, and a nonnegative total elapsed time. The 98 executable cases completed 6540 fault trials, of which 4614 had strict injections and 1829 were recorded as post-fault target reaches by the old hook. No executable terminal case had zero strict injections. The per-case elapsed times sum to 476861.961 seconds of aggregate work across concurrently used nodes; this is not campaign wall-clock time. For migration rows, `total_elapsed_seconds = prior_campaign_elapsed_seconds + current_campaign_elapsed_seconds`; no row violates this or falls below its active runtime.

## Coverage gaps

Among the 22 `no_valid_target_trial` rows, 14 have `healthy_target_reached=True`: HBASE-02, HBASE-18, HBASE-19, HBASE-20, HBASE-28, HDFS-20, HDFS-29, HDFS-30, HDFS-32, HDFS-39, HDFS-40, HDFS-52, SOLR-38, ZOOKEEPER-10. Their unchanged JUnit reaches the check in the healthy seed, but the tested fault sequences lose the target afterward; further generic fault scheduling can help, while the current result should remain a coverage gap. HBASE-18's old result omitted the reach flag, but its retained healthy trace has an exact `CHECK_REACHED` for selected site `#u73` at seq 712. The collector now recovers a missing true flag from an exact seed trace event.

Eight have `healthy_target_reached=False`: HBASE-33, HDFS-18, SOLR-01, SOLR-15, SOLR-16, SOLR-34, ZOOKEEPER-04, ZOOKEEPER-07. This unchanged JUnit workload does not reach the selected check even without a fault. Another original cluster JUnit would be needed if one exists; simply raising this workload's fault budget will not establish healthy reachability. None of these 22 is treated as a checked negative finding.

## Exception and evidence audit

HBASE-16 trial 22/64 and HBASE-21 trial 36 have strict fault applications followed by exact target `EXPLICIT_THROW` events, although the old differential oracle labelled the trials `lost_target`. HBASE-27 trials 3/4/9 use the configured method/type oracle plus exact exception message and source path; the old selector emitted no `EXPLICIT_THROW`. These three cases have `target_exception_triggered=True` in a separate table column, with trial numbers, healthy expectation, first-trigger elapsed time, and evidence kind. See the [target exception audit](static102-exact-throw-oracle-audit-2026-10-13.md). None is claimed as a newly discovered bug. No other exact post-fault target throw was found among the old-oracle false negatives in the scanned node0/node1/node2 raw trial traces. In particular, HDFS-32's method-level `IOException` count did not have an exact selected `EXPLICIT_THROW` event.

The old differential candidate count is three, all in HBASE-27; `review_verdict=rejected_expected_shutdown_after_injection` cites source and trial logs. Thus there is no unreviewed candidate in the final table. Keeping `target_exception_triggered` separate avoids misreading a rejected *bug* candidate as an untriggered *check*.

Result-path validation found 38 campaign result files still local, 28 resolved on node1, and 32 on node2; all 98 executable result files exist at these paths. HBASE-21's local `campaign_result` was archived after the run; the table now fills `archive_host=node1` and the exact archived `result.json` path from the checked `archive.json` receipt. Other HDFS offload `archive_path` values name evidence directories while their local `campaign_result` files remain available. The four `no_cluster_test` rows have no result file as expected.
