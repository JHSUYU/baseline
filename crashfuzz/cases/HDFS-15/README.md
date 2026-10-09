# HDFS-15: `BlockInfo.commitBlock` state guard

## Case identity

- System: Hadoop HDFS 3.4.3.
- Original source: `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo.java:447`.
- Function and guard: `BlockInfo.commitBlock(Block)`, `Preconditions.checkState(!isComplete());`.
- Exact oracle: the `IllegalStateException` thrown by this guard after the last applied fault. The preceding block-ID `IOException` and ordinary JUnit failures are different outcomes.
- Original embedded-cluster workload: `org.apache.hadoop.hdfs.security.token.block.TestBlockToken#testBlockTokenInLastLocatedBlockLegacy`, with one NameNode and one DataNode via `MiniDFSCluster`. It writes 1,000 bytes into two 512-byte blocks, observes block locations, and closes the stream. The original JUnit passed in 13.005 seconds.
- The bootstrap description called this a block-token check, but the selected source line is a block completion state guard. This case uses the exact source guard as its target.

## Runtime method

`system-test/OriginalHdfs15Test.java` runs the unchanged upstream JUnit method and fixture. `source/` contains read-only copies of the relevant original Hadoop sources and test resource; `source-provenance.json` records matching Hadoop 3.4.3 release-JAR members and hashes. `system-test/build_probe.py` builds case-local source overrides for the exact guard, Hadoop RPC response, and edit-log flush; it does not modify the original JUnit or system JARs. The healthy instrumented run passed in 18.123 seconds and reached the exact guard twice with normal outcomes. Its trace contains 41 observed RPC and file I/O events.

`system-test/Probe.java` records each guard outcome and I/O event in order. An injection selector is `(marker, API, ordinal, exception type)` and a fault is counted as strict only if every requested selector matches and applies in order. Each selector is also bound to the next observed exact target guard's `blockId` and `reportedBlockId`; its source occurrence ordinal is saved for replay. The campaign discards any sequence that loses that same block-instance guard after the final applied fault. `system-test/CoverageDump.java` derives HDFS production method, covered branch-unit, and exact class-probe IDs from JaCoCo. Branch units are JaCoCo covered branch counts at a source line; they do not identify which branch outcome was taken. Selection uses only those coverage IDs and I/O points observed in the healthy or faulted JUnit run. No graph, closure, static scope, Docker cluster, GraphChecker skeleton, or prewoven GraphChecker artifact is read.

The current budget is 80 trials with at most eight ordered faults per sequence. If the last eight trials at that limit still discover production method/branch coverage or a stable I/O family, the same checkpoint extends to 128 trials and ten faults. This was increased from the initial 64/six setting after 48 trials; `campaign/checkpoint-before-80-trial-budget.json` preserves the prior checkpoint. `campaign/run_campaign.py` stores the selected sequence in `campaign/checkpoint.json` before running it. Each trial has a plan, trace, manifest, coverage, exact selector result, elapsed time, and ledger row; a resumed run skips completed trials and does not rerun a current trial with a remote manifest.

## Evidence and resume

- Healthy: `healthy/original-manifest.json`, `healthy/instrumented/healthy-summary.json`, `runtime_trace.jsonl`, and `coverage.tsv`.
- Trial evidence: `campaign/trial-XX/`, `campaign/trial-ledger.csv`, `campaign/checkpoint.json`, and top-level `result.json`.
- The first five coverage outputs were repaired from their existing JaCoCo `.exec` files because the initial probe-only dump also counted test-JAR classes. `campaign/coverage-filter-repair-2026-10-06.tar.gz` preserves the old summaries, TSVs, trial results, and before/after counts. No JUnit or fault trial was repeated for this correction.
- The first ten saved traces were re-audited with per-block target identity. `campaign/target-context-migration-2026-10-06.tar.gz` preserves the prior checkpoint and trial results. Mutations now consider I/O before the last later target guard and bind each candidate to its next guard's block identity; no completed trial was repeated.
- The long-running driver uses node0 tmux session `hdfs15-coverage-io-80`; each JUnit runs on node2 in the isolated HDFS-15 directory. To resume if tmux ended: `python3 -u crashfuzz/cases/HDFS-15/campaign/run_campaign.py` from `/users/ZhenyuLi/baseline`.

The run status and bug mark are in `result.json`. A target exception is a candidate until the same exact selector reproduces it and the released Hadoop source explains a correctness failure.

## Completed result

The 80-trial budget finished with 80 distinct ordered fault sequences and no exact target exception. The final eight trials added no production method or branch coverage and no stable I/O family, so the 128-trial extension did not apply. The remaining 57 queued sequences remain in the checkpoint and can be explored under a later authorized budget without repeating any completed trial.

| Measure | Result |
| --- | ---: |
| Requested / matched / applied fault events | 178 / 171 / 171 |
| Strictly injected trials | 73 |
| Strict trials retaining the same block's guard after the last fault | 53 |
| Trials with target lost / incomplete injection | 20 / 7 |
| Multi-fault trials; maximum realized depth | 62; 3 faults |
| New production method / branch-unit / probe IDs | 24 / 89 / 177 |
| Exact target exceptions; confirmed new bugs | 0; 0 |
| Healthy plus fault-campaign time | 1,808.737 seconds |

Each trial's exact requested/applied selector sequence, target context, JUnit outcome, coverage, I/O novelty, and duration are in its `trial-result.json` and the ledger. A JUnit failure caused by an injected I/O exception was never treated as an occurrence of `BlockInfo.commitBlock`'s guard exception.
