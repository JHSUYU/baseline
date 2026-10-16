# HDFS key-mismatch Mallory evidence

The [seven-path status table](../hdfs_key_pr_seven_path_status_20261015.md) gives the definitions, JUnit workloads, per-path conclusions, and elapsed times. These JSON files are compact copies of final receipts and audits. `SHA256SUMS` pins their bytes. The raw traces, complete trial results, checkpoints, and archive restore receipts remain at the original locations named inside the JSON and status table; they are too large for this Git directory.

| File | Role |
| --- | --- |
| `sps-r0045-direct.json` | Direct `BlockDispatcher.moveBlock` target exceptions after the observed RPC fault. |
| `sps-r0045-replay-control.json` | Exact-plan replay with direct SPS throws and zero-fault control without throws. |
| `balancer-r0115-diagnosis.json` | First faulted receiver exception attributed to proxy `DataXceiver.replaceBlock`, not direct Balancer send. |
| `balancer-r0141-r0156-wave.json` | No-repeat Balancer wave, including the direct-path negative r0154. |
| `balancer-r0154-direct-sender.json` | Exact HDFS SASL UUID/attempt attribution for r0154. |
| `balancer-r0157-r0164-wave.json` | Corrected V21 ledger; no exact target throw. |
| `balancer-r0159-r0167-sender-gap.json` | Sender attribution limits for two selected checks. |
| `balancer-r0165-r0172-final.json` | Final V22 stop receipt and eight-trial archive hashes. |
| `append-r0104-sender.json` | Intermittent `DataXceiver.writeBlock` target-throw candidate and exact sender join. |
| `append-r0104-differential.json` | Five zero-fault controls and ten faulted replays; no repeated throw. |
| `append-r0105-r0120-wave.json` | Subsequent append continuation. |
| `append-r0117-excluded-sender.json` | CLIENT-origin throw, excluded from the two intended append sender paths. |
| `append-r0121-r0130-final.json` | Final append stop receipt, per-trial timings, fault sites, and checkpoint lineage. |

The final outcome is two observed PR paths under the target-exception criterion, one intermittent third-path candidate, and no confirmed new upstream bug. The final V22 and append continuations found no additional exact target throws. The retained-parent quota added to the integrated Mallory code was not exercised before the user-requested stop; the append receipt records the executed frozen bundle separately from the integrated Git source.
