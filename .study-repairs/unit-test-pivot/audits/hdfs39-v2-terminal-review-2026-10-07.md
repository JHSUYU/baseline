# HDFS-39 actor V2 terminal review

The independent terminal audit of the fresh actor-bound Hadoop 3.4.3
`TestFileAppend#testMultipleAppends` campaign **passed with zero raw-evidence
errors**. The node1 atomic checkpoint ended at `budget_complete_80`, SHA-256
`bc93ac1b343e98fb9d8a5bd4b49e7f287531be1875dffb104f0548ab3975397c`,
with `current=null`. It has 173 distinct V2 attempts; 96 applied their full
ordered fault plans, and 80 also revisited `FSDirAppendOp.appendFile:131` on
`/testMultipleAppend/foo`, block `1073741825`, after the last fault. No trial
from the 205-attempt pre-actor-aware legacy campaign was imported.

For every V2 attempt, [the audit program](hdfs39-live-raw-audit.py) compared
the checkpoint row with the immutable exact plan and per-trial result, the
original JUnit manifest and log, trace and JaCoCo SHA-256, and independently
reconstructed ordered fault matches, actual NameNode peer port, DataNode
UUID/block-pool/role binding, target file/block reachability, production
coverage gain and actor-aware I/O feedback. It also rebuilt the coverage and
I/O unions from the two new passing healthy originals. The terminal audit
was repeated after extracting the complete local [raw archive](../hdfs39-rpc-actor-v2/evidence/hdfs39-v2-terminal-raw.tar.zst)
and produced identical JSON. The archive contains all 1,227 raw files
(922,058,939 bytes uncompressed; 67,672,602 bytes compressed), SHA-256
`d0f67f187af3421c9d89cbf99ed89656682606b455628e369e688f20da4f9321`.

| Measure | Actor V2 result |
| --- | ---: |
| Healthy original JUnits | 2 passed; 18.937 s and 20.228 s |
| Fault attempts / fully applied / effective | 173 / 96 / 80 |
| Requested / applied fault events | 323 / 205 |
| Effective plan depths | 45 one-fault, 28 two-fault, 7 three-fault |
| Healthy production JaCoCo IDs | 8,628 branch units; 8,012 methods; 28,179 probes |
| Effective production gain | 614 branch units; 285 methods; 1,481 probes |
| Final actor-aware I/O families | 11 |
| Measured original JUnit time | 3,832.736 s, including both healthy runs |
| Campaign wall time | 15,508.056 s, including lock and controller waits |

Effective trials 73–80 were trials 155, 160, 161, 162, 164, 171, 172 and
173. Each added zero production method/branch IDs and zero actor-aware I/O
families. The conditional 128-effective-trial extension therefore did not
apply; the 80-effective-trial stop is independently verified from the raw
feedback.

The only exact postfault target exception was the passing
`trial-0056-attempt-01` `COMMITTED`-block `RetriableException`. The
[source and exact-plan replay review](hdfs39-trial56-target-review.md)
classifies it as the expected `DFSClient.callAppend` retry; three clean
same-plan replays passed and did not repeat a postfault target throw. All
other V2 effective trials had zero exact postfault target exceptions. Of the
24 nonzero original fault JUnits, 21 terminated directly at their requested
injected I/O exception. Three attempts (12, 20 and 166) reached the 180 s
timeout with no exact postfault target exception and were ineffective. The
final effective trial 173's JUnit failed on its explicitly injected client
`RPC_RESPONSE_WAIT` `EOFException`; its postfault target guard was reached
but did not throw. These outcomes remain in the archive. **No new HDFS bug
was validated.**

The safe node1 shared-lock handoff after attempt 97, its two audited pilot
JUnits and the 10 GiB / at-most-four-Java gate are recorded in the
[handoff review](hdfs39-locked-handoff-2026-10-07.md). The complete
[terminal audit JSON](../hdfs39-rpc-actor-v2/evidence/terminal-raw-audit.json),
[summary](../hdfs39-rpc-actor-v2/evidence/terminal-summary.json), and
[archive receipt](../hdfs39-rpc-actor-v2/evidence/terminal-evidence-receipt.json)
bind this classification to the terminal raw files.
