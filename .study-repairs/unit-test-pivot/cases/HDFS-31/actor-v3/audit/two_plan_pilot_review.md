# HDFS-31 actor V3 two-plan pilot, 2026-10-07 UTC

The unchanged Hadoop 3.4.3 `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` JUnit ran twice after two healthy calibrations. The selected production guard is `DataNode.getBPOSForBlock(ExtendedBlock)` at `DataNode.java:1832`, with its possible exception at line 1835. The old coarse 80 attempts remain historical and contribute zero to this V3 campaign.

| Plan | Fault | Raw ordering and selected actor | JUnit | Effective |
| --- | --- | --- | --- | --- |
| `1337d6ac6c2455df645c` | same-actor NN0 `Client.getRpcResponse` ordinal 6, `IOException` | Strict fault at seq 37, but same-block transfer and selected target were seq 33 and 34. The target was already executed. | pass, 17.368 s | no |
| `4af3aedefb481302fc28` | same-actor NN0 `Client.getRpcResponse` ordinal 6, `EOFException` | Strict fault at seq 24, then same-block transfer and selected target at seq 34 and 35, joined by raw DataNode UUID, BP, block ID, service object and actor. | pass, 17.268 s | yes |

The independent [raw pilot audit](two_plan_pilot_raw_audit.json) passes with 2 completed, 2 strict, 1 same-actor postfault effective, 0 selected target exceptions and 0 issues. The durable checkpoint before queue migration had SHA-256 `fd3fa785f0c0cd48551080980c012733fd3bb1dd922c9c937dc1e7cd01d80d0e`, `in_flight=null`. The pilot raw runs, controller logs and checkpoint comprise 25 files / 22,298,948 bytes in [the node2 manifest](pilot_mirror_manifest_node2.json), SHA-256 `ea1d98aa21459686d9f9ce257d8a32038478e0ed352ad155353bda03e5cb2dd0`. They were mirrored to node1 at `hdfs31-actor-v3-20261007/evidence/pilot-snapshot-2`; independent SHA verification passed for all 25 files.

Only scores of the 16 pending one-fault plans were changed at this complete boundary to favor earlier, stable NN0 response ordinals. Plan IDs, queue order, completed plans, effective count and original fault plans were unchanged. Offline synthetic migration showed top ordinal 1 and preserved IDs/counts. The new checkpoint SHA-256 is `c8ab29826f827ec13f4c946cc07f3b7c07bfd88b18bf4e992dc6adcb86b7703b`; the immutable remote receipt is `evidence/pilot-queue-reprioritization.json`.

The resumed controller uses the same original JUnit, two-seed overlay digest, shared launch lock, Java-before ≤4 and free disk ≥10 GiB. It pauses at 80 effective for a source and target-related coverage review before any conditional 128/10 extension.
