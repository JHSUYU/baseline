# HDFS-17967 target-check experiment

## Workload and search

The unmodified Hadoop 3.4.3 distribution ran as one NameNode and three
DataNodes with encrypted data transfer and block tokens enabled. Each trial
created an 8 MiB file with replication factor three, read it back, and
compared SHA-256 hashes. The target was the compiled `key == null` guard
immediately after `allKeys.get(keyId)` in
`BlockTokenSecretManager.retrieveDataEncryptionKey`; the exact
`InvalidEncryptionKeyException` throw was monitored separately.

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Seed: encrypted HDFS put/get → trace exact guard and communication  │
└───────────────────────────────┬──────────────────────────────────────┘
                                ↓
                Target backward causal closure
                │ client ↔ NameNode: Hadoop IPC request/response
                │ client → DataNode: encrypted data-transfer request
                │ DataNode → DataNode: replication pipeline request
                │ DataNode addKeys → target read: STATE_CANDIDATE
                ↓
      Mutate crash/reboot at observed, replayable fault points
                │ DataNode SASL receive communication boundary
                │ target-method entry inside that receive path
                ↓
      Fresh cluster → inject → trace → extend coverage → repeat
```

The NameNode was protected by the campaign's maximum-down constraint. A
single DataNode could be crashed and restarted. The fault schedule was chosen
from observed points and ranked using closure membership and new coverage.

## Observed result

| Measure | Result |
| --- | ---: |
| Total trials, including healthy seed | 12 |
| Fault trials | 11 |
| Fault trials with matched injection | 10 |
| Matched crash/reboot actions | 13 |
| Matched actions at SASL receive boundary | 5 |
| Fault trials reaching the exact guard | 11 |
| Total exact guard evaluations, including seed | 43 |
| `key == null` outcomes | 0 |
| Exact target exception throws | 0 |
| Workload failures | 0 |

The healthy seed reached the guard four times. Every fault trial also reached
the guard. All observed evaluations took the key-present branch. One planned
fault did not match its replay point; it is counted as a trial but not as an
injected fault. All ten trials with matched injection passed the data checker.
The search stopped at its configured 12-run budget with 35 queued candidate
sequences and no finding.

For a concrete communication-boundary example, `run-00004` crashed `dn2` at
`SaslDataTransferServer.receive#ENTRY`. The injection matched exactly. The
target guard was evaluated three times, all key-present, and the put/get
workload plus checksum checker succeeded. `run-00010` through `run-00012`
also exercised matched crash/reboot sequences.

## Interpretation and limits

This workload and these schedules did **not** trigger the missing-key branch
or `InvalidEncryptionKeyException`. The result is bounded by the 11 fault
trials and the selected crash/reboot points. The Hadoop IPC edges currently
observed in the target closure are client/NameNode requests and responses;
they do not by themselves prove an exact NameNode-to-DataNode key-update
dependency. The `addKeys` map edge is explicitly a `STATE_CANDIDATE`, because
the trace does not record a per-key read-from version. The workload launches
separate HDFS client JVMs for put and get, so it does not retain a client-side
encryption key across those commands. These limits matter when interpreting
the negative observation.

`out_fuzz/report.json` has per-run matched actions, branch outcomes, and
closure message-edge counts. `out_fuzz/runs/*/traces/` contains the raw
events; `out_fuzz/runs/*/result.json` contains each planned sequence and the
controller's exact injection matches.
