# HDFS-39 V2 trial 56: source and exact-plan replay review

**Classification:** reviewed expected transient target exception; no confirmed new bug. Preserve the original run in the target-exception ledger. Continue the HDFS-39 V2 budget; do not count this observation as a confirmed failure.

## Original observation

- Workload: unchanged Hadoop 3.4.3 `TestFileAppend#testMultipleAppends`, one NameNode and four DataNodes, with its original final file length and byte-for-byte content assertions.
- Target: `FSDirAppendOp.appendFile:131`, path `/testMultipleAppend/foo`, block `1073741825`.
- Node1 raw run: `evidence/trial-0056-attempt-01`; trace SHA-256 `a5e5274f01cd7d183b582cc8b5e5600231508daf1ac7ec56356d4312eecfe12b`.
- Immutable one-fault plan SHA-256 `854e0e095c0a84f19dd38f51ecc4f8c332791e602bf4c2cf99617a23efd052a2`: `RPC_SEND` of `DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted[blockReceivedAndDeleted:blocks=[1073741825]]`, physical `nn0<-dn1`, occurrence 1, `SocketTimeoutException`. The local copy is [plan.tsv](../hdfs39-rpc-actor-v2/evidence/candidate-trial56-review/plan.tsv).
- Actor binding and the exact block check passed. The first `COMMITTED` target guard/throw was at trace seq 74/75, **before** the fault at seq 83. A second `COMMITTED` guard/throw occurred at seq 225/226, after the fault. The controller's `candidate=false` label omitted this passing JUnit outcome because it required JUnit exit nonzero; the independent audit retains the actual post-fault target exception. The original JUnit exited 0, including the final data assertions.

## Source meaning and replay

`FSDirAppendOp.appendFile` throws `RetriableException(NotReplicatedYetException)` when the last block is `COMMITTED` but not yet `COMPLETE` (Hadoop source `hadoop-hdfs/.../FSDirAppendOp.java`, around lines 131–139). `DFSClient.callAppend` explicitly retries a remote `RetriableException` for up to five seconds, sleeping 500 ms between attempts (`hadoop-hdfs-client/.../DFSClient.java`, around lines 1422–1444). The original test performs repeated append/write/close operations and verifies the resulting length and every byte (`TestFileAppend.java`, around lines 393–437). This is a designed temporary response while block completion catches up; the check throwing by itself does not establish a coordination defect.

On node0, the same overlay test class SHA-256 `762da6dde4504b6a1689ccffa47c34538885fe11ae0bb4520e0faa73d9f29650` was used for one new healthy run and three exact-plan replays. Each original JUnit exited 0:

| Run | Time (s) | Fault applied | Post-fault guards | Post-fault `COMMITTED` throws |
| --- | ---: | --- | ---: | ---: |
| healthy comparator | 22.156 | none | n/a | n/a |
| exact replay 1 | 19.222 | seq 79, same `dn1` | 9 | 0 |
| exact replay 2 | 21.594 | seq 80, same `dn1` | 9 | 0 |
| exact replay 3 | 18.817 | seq 79, same `dn1` | 9 | 0 |

The healthy comparator had a `COMMITTED` guard/throw at seq 74/75. Every replay had one at seq 72/73, **before** its fault. All three replays had the requested fault exactly once with verified physical DataNode identity, and the same target path/block remained reachable after it. Thus the extra *post-fault* throw in trial 56 was not reproduced in three exact replays. The passing original run, healthy comparator, explicit client retry path, and full data assertions support classifying the observed throw as an expected temporary retry. They do not prove that every timing around this check is correct.

The raw trial 56 remains on node1. The healthy comparator and exact replays are also preserved in [hdfs39-trial56-replay-evidence.tar.gz](hdfs39-trial56-replay-evidence.tar.gz), SHA-256 `ccdf1bd04a0eb309b69b6a32fc9a4c19eabf70effea25f15e279aec6ff4c3253`. All 17 archived files were byte-compared with the node0 originals. Each run includes its manifest, trace, JaCoCo exec and original JUnit log. [hdfs39-live-raw-audit.py](hdfs39-live-raw-audit.py) accepts only the exact reviewed trial 56 plan/trace fingerprints as reviewed; any new post-fault target exception stays in `unreviewed_target_outcome_runs` for fresh review. At a live checkpoint snapshot of 72 trials, this independent raw audit recomputed 33 effective runs with zero evidence errors and no other post-fault target outcome.
