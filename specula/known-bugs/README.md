# Specula on 14 known bugs at their buggy versions

Specula ran on each bug's buggy version (the parent of its fix commit), one ad hoc check per bug: the check the bug makes fail. Model claude-opus-5-5[1m], effort high, 2026-11-07/08. Time is active time; quota sleeps are excluded. Tokens and cost cover the whole run, all phases.

**Result: 11 detected, 1 partly detected, 2 not detected.**

**How detection was judged.** Before the runs, I wrote down from the JIRA ticket and the fix what a finding must show to count as each bug. A finding counts when it has the same root cause and fails the same check. All 14 runs ended REACHED_CONFIRMED.

| bug | case | detected | finding | method | time | tokens | cost | folder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HDFS-11741 Balancer block moves fail | hdfs-adhoc-k1 | yes | MC-1 | TLC | 1h55m | 56.9M | $35.95 | [`HDFS-11741-hdfs-adhoc-k1-MC-1`](HDFS-11741-hdfs-adhoc-k1-MC-1/BUG.md) |
| HDFS-17383 Block transfers fail | hdfs-adhoc-k2 | no | – | – | 3h14m | 76.8M | $43.18 | – |
| HDFS-12931 File checksum fails | hdfs-adhoc-k3 | yes | CR-5 | code review + test | 2h08m | 82.8M | $54.64 | [`HDFS-12931-hdfs-adhoc-k3-CR-5`](HDFS-12931-hdfs-adhoc-k3-CR-5/BUG.md) |
| HDFS-5766 Healthy DataNode marked dead | hdfs-adhoc-k4 | partly | CR-4 | code review + test | 2h19m | 101.3M | $70.29 | [`HDFS-5766-hdfs-adhoc-k4-CR-4`](HDFS-5766-hdfs-adhoc-k4-CR-4/BUG.md) |
| HDFS-10609 Pipeline recovery aborts client | hdfs-adhoc-k5 | yes | CR-3 | code review + test | 2h40m | 78.3M | $49.41 | [`HDFS-10609-hdfs-adhoc-k5-CR-3`](HDFS-10609-hdfs-adhoc-k5-CR-3/BUG.md) |
| HDFS-14075 NameNode crashes with NPE | hdfs-adhoc-k6 | yes | MC-1 | TLC | 1h05m | 36.3M | $25.76 | [`HDFS-14075-hdfs-adhoc-k6-MC-1`](HDFS-14075-hdfs-adhoc-k6-MC-1/BUG.md) |
| HDFS-14311 DataNode upgrade fails | hdfs-adhoc-k7 | yes | MC-1 | TLC | 1h17m | 41.9M | $29.96 | [`HDFS-14311-hdfs-adhoc-k7-MC-1`](HDFS-14311-hdfs-adhoc-k7-MC-1/BUG.md) |
| SOLR-9440 Client caches stale state | solr-adhoc-k1 | yes | CR-3 | code review + test | 4h26m | 127.0M | $62.45 | [`SOLR-9440-solr-adhoc-k1-CR-3`](SOLR-9440-solr-adhoc-k1-CR-3/BUG.md) |
| SOLR-6101 Shard splitting fails | solr-adhoc-k2 | yes | MC-1 | TLC | 1h27m | 37.4M | $22.80 | [`SOLR-6101-solr-adhoc-k2-MC-1`](SOLR-6101-solr-adhoc-k2-MC-1/BUG.md) |
| SOLR-6197 Collection migration fails | solr-adhoc-k3 | yes | MC-1 | TLC | 1h09m | 40.1M | $25.33 | [`SOLR-6197-solr-adhoc-k3-MC-1`](SOLR-6197-solr-adhoc-k3-MC-1/BUG.md) |
| HBASE-15039 Token authentication fails | hbase-adhoc-k1 | yes | MC-1 | TLC | 2h11m | 63.1M | $44.88 | [`HBASE-15039-hbase-adhoc-k1-MC-1`](HBASE-15039-hbase-adhoc-k1-MC-1/BUG.md) |
| HBASE-20642 Adding column family fails | hbase-adhoc-k2 | yes | MC-2 | TLC | 1h14m | 35.7M | $24.08 | [`HBASE-20642-hbase-adhoc-k2-MC-2`](HBASE-20642-hbase-adhoc-k2-MC-2/BUG.md) |
| ZOOKEEPER-710 Permanent session-moved errors | zk-adhoc-k1 | yes | MC-2 | TLC | 1h13m | 28.6M | $22.01 | [`ZOOKEEPER-710-zk-adhoc-k1-MC-2`](ZOOKEEPER-710-zk-adhoc-k1-MC-2/BUG.md) |
| ZOOKEEPER-2886 Multi-op session-moved errors | zk-adhoc-k2 | no | – | – | 1h24m | 43.1M | $30.34 | – |
| **total (14 runs)** | | | | | **27h42m** | **849.3M** | **$541.08** | |

## Notes on individual bugs

- **HDFS-5766, partly detected.** CR-4 is exactly the bug's defect: on a positional read, after `InvalidEncryptionKeyException` the client does not `continue`, so it puts a healthy DataNode into deadNodes. Specula's verdict is MASKED, because with the default configuration the read recovers through chooseDataNode's back-off.
- **HDFS-17383, not detected.** MC-1 is a different HA key bug: a restarted DataNode that has registered with only one NameNode. The real root cause is that a DataNode takes its currentKey from the standby NameNode. That cause was found in the hdfs-adhoc-k3, k4 and k5 runs (k3 MC-4, k4 CR-1/MC-4, k5 MC-5), but there it fails the encryption-key check, not this case's block-token check.
- **ZOOKEEPER-2886, not detected.** The finding is an owner divergence that recovers when the connection is torn down. It is not the multi-op path, which keeps the connection and fails forever.
- **Other runs also found some of these bugs.** HDFS-11741 was also found in k4 MC-5 and k5 MC-2. HDFS-12931 was also found in k4 CR-2. SOLR-6197 was also found in solr-adhoc-k2 CR-1.
- **HBASE-20642.** MC-1 of the same run (retry after an RPC timeout) is the same bug; its TLC files are not copied here.

## Each folder

- `BUG.md`: the known bug (mechanism from the JIRA and the fix), what counted as detecting it (written before the run), what Specula found, the operator's judgement, and the run's time, tokens and cost.
- `tlc/`: TLA+ modules, the config, the counterexample log and `RERUN.md` (jars in `../data/tlc/`, JDK 21). The 4 code-review findings have no TLC; their evidence is the reproduction.
- `repro/`, `confirmation/`: the reproduction on the buggy version, and Specula's verdict, investigation and issue.

All 8 TLC counterexamples were rerun from these published copies on 2026-11-09: each reports `Invariant TargetSafe is violated` (`rerun-results.tsv`). `bugs.json` has every row, including the not-detected ones, with the mechanism and the detection criterion.

## How the answer was kept away from Specula

- Each case tree is a single commit, `base`, made from `git archive` of the buggy parent. It has no history, no remote and no other refs.
- Trees and target files were searched for the JIRA key, the fix hash and phrases from the fix. The solr-adhoc-k1 tree had 7 comment lines naming SOLR-9440; only those comment lines were removed before the base commit.
- The zk-adhoc-k2 tree keeps an earlier ZOOKEEPER-710 fix comment. It is genuine buggy-version source and is unrelated to ZOOKEEPER-2886.
- Full histories and the operator's notes were kept only on node2's local disk, and no run ran on node2.
- **Post-run check.** No JIRA key or fix hash appears in Phase 1–3 output. For every detected finding, the run reproduced the bug before its novelty search reached the JIRA.
