# HDFS-11 isolated post-call heartbeat campaigns (2026-10-12)

These are diagnostic campaigns for the selected Hadoop 3.4.3 check in
`BlockTokenSecretManager.retrieveDataEncryptionKey`: `allKeys.get(keyId)` at
line 551 and its `InvalidEncryptionKeyException` throw at line 553. Both use
the original `TestEncryptedTransfer#testLongLivedClientPipelineRecovery[0]`
MiniDFSCluster workload. They are separate from the 102-check result table.

The healthy run records **one** exact target `EXPLICIT_THROW` at bytecode site
`BlockTokenSecretManager.retrieveDataEncryptionKey#bytecode:throw:555:0`.
This test deliberately expires the old client key and recovers from its
rejection. A fault trial is a new target-exception candidate only if its
target throw count exceeds this healthy baseline, with the target reached
after the fault. JUnit exit alone is not the exception oracle.

| Isolated campaign | Budget and terminal result | Strict / target-retaining trials | Exact target `EXPLICIT_THROW` count across trials | New target throws vs healthy | Measured JUnit time | Worker total time |
| --- | --- | --- | --- | ---: | ---: | ---: |
| v1 post-call | 80 completed; base budget 80, conditional hard cap 120; `budget_or_queue_complete` | 76 / 46 | 71 trials × 1; 9 trials × 0 | 0 | 2,382.567 s | 2,931.583 s |
| v2 temporal | 40/40; `budget_or_queue_complete` | 40 / 33 | 33 trials × 1; 7 trials × 0 | 0 | 1,121.711 s | 1,375.967 s |

Neither campaign changed the target outcome or produced an oracle candidate.
The zero-throw trials lost the relevant post-fault target path; they do not demonstrate
that the intended stale-key rejection was repaired. The v1 hard cap was not
used because its 46 target-retaining trials exceeded the configured minimum
of 30 at the 80-trial base boundary. Its persisted queue still contained
untested sequences.

The observed `BPServiceActor.sendHeartBeat → sendHeartbeat` call occurs up to
ordinal 6 in the healthy trace. The comparison below concerns **applied**
faults, not merely observed I/O:

| Milestone | v1 | v2 |
| --- | --- | --- |
| First heartbeat ordinal 2 | Trial 60, before call; 1,624.678 s cumulative measured JUnit time | Trial 12, before call; 337.814 s |
| Heartbeat ordinal 2 after return | Not applied | Trial 19; 551.530 s |
| Heartbeat ordinal 4 before call | Not applied | Trial 20; 581.437 s |
| Heartbeat ordinal 4 after return | Not applied | Trial 21; 638.472 s |

V2 trial 20 applied two heartbeat faults (ordinal 2 after return, then ordinal
4 before call), retained the target, recorded one expected target throw, and
exited JUnit successfully. Trial 21 applied the ordinal-4 after-return fault
but lost the target, exited JUnit with failure, and recorded zero target
throws. The temporal rule therefore reached later control-plane I/O much
earlier within this workload, without detecting an additional selected
exception or reproducing the distinct [HDFS-17967 / PR #8698](https://github.com/apache/hadoop/pull/8698)
DN-to-DN stale-key failure.

Raw local diagnostics (not part of the original 102-check table):

- v1: `.study-repairs/diagnostics/hdfs11-postcall-key-campaign/results/HDFS-11/campaign-postcall-key-v1/HDFS-11/` (`result.json`, `state.json`, `trials/`, and `healthy-postcall-key-v1/` one level above); worker log at `.study-repairs/diagnostics/hdfs11-postcall-key-campaign/worker.log`.
- v2: `.study-repairs/diagnostics/hdfs11-temporal-key-campaign/results/HDFS-11/campaign-temporal-key-v2/HDFS-11/` (`result.json`, `state.json`, `trials/`, and `healthy-temporal-key-v2/` one level above); worker log at `.study-repairs/diagnostics/hdfs11-temporal-key-campaign/worker.log`.
- Exact heartbeat milestone trial results: v1 `trials/0060-eab32403432354e2c78c/result.json`; v2 `trials/0012-d9d3c943e741ede7c5db/result.json`, `trials/0019-fbc451d5f5eede3ce123/result.json`, `trials/0020-a24f8ff1a47b13980336/result.json`, and `trials/0021-f83277259bd2f5e1e027/result.json`. Each result points to its compressed runtime trace.

Terminal `result.json` SHA-256: v1
`3c51dc81540f9f59ad4bd94fc72bfcf88bc5f68626eacb40770b3c6af4a786bf`;
v2 `ab6c8e79f7c225d60f81513620db102505d4e3a5ed2d99fccd399aecb61b926f`.
