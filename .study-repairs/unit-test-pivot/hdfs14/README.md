# HDFS-14: block-token password check

## Original test and exact target

The released Hadoop 3.4.3 JUnit child is
`org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
The `[0]` parameter has no trusted-channel resolver. The original test starts
`MiniDFSCluster` with its default one NameNode and one DataNode, writes a file,
reads it and its checksum, shuts the cluster down, then restarts it from the
same directories with encrypted transfer and block access tokens enabled. It
then reads and checksums the file again. See the unchanged source at
`TestEncryptedTransfer.java:80-213`. No custom workload actions or assertions
were added.

The selected check is `BlockTokenSecretManager.checkAccess(Token,...,
StorageType[],String[])` at source line 411-412. Its `MessageDigest.isEqual`
guard rejects a block token whose password cannot be recomputed. That
recomputation calls `retrievePassword`, which reads `allKeys.get(keyId)` at
line 509; a missing key has its own `InvalidToken` throw at line 512. The
GraphChecker target for HDFS-14 resolves to guard `#u33`, region
`REGION.7f08d6f5-b1ef-323d-8084-ce44a2259712`.

## Scoped runtime identity repair

The shared HDFS SASL adapter initially closed its DataNode request scope as
soon as `SaslDataTransferServer.receive` returned. Hadoop calls
`DataXceiver.processOp` and the token check **after** that return, so the two
target executions inherited the embedded JUnit client's root and shared one
occurrence address. This copy of the adapter keeps the inbound SASL scope
until `DataXceiver.run` exits. `PatchSaslReceive` adds a `finally` callback
to the released `DataXceiver.run` bytecode; the original test and Hadoop wire
payload remain untouched. The normal-path `receive` callback defers the scope
exit, while an exceptional `receive` exit closes it immediately. The patched
class and helper live only in `adapter/overlay`.

With this change, the healthy trace has two distinct target occurrence
addresses on `hdfs/datanode/0`, anchored to the two observed `HDFS_SASL`
request exchanges. The trace has two matching send/receive pairs, two healthy
`#u33` outcomes, and no HDFS-14 fatal occurrence. The planner includes both
client `FAULT:HDFS_SASL:REQUEST` markers in the backward closure headed by
the first target occurrence (`CONTROL_PRODUCER_V1`, `CANDIDATE`). The second
target has a distinct address and a concrete matching send/receive endpoint,
but the planner does not assign each marker separately to its corresponding
target occurrence. This is **not** an exact `allKeys` key-version read-from
edge. The latter still needs a separate key-distribution state adapter, so
these two trials do not cover all important HDFS-14 timing windows.

## Strict trials and oracle

Both selectors name the healthy run's exact marker, site, occurrence address,
source, and hit ordinal. The injected DoorWeave exception is an `IOException`
at the SASL request boundary. The oracle is only whether HDFS-14's exact guard
takes its fatal arm after an applied fault; JUnit success or failure alone is
not the bug verdict.

| Trial | Matched / applied | Original JUnit | Target after fault | HDFS-14 fatal |
|---|---:|---:|---:|---:|
| First SASL request | 1 / 1 | passed | yes, two healthy hits | no |
| Second SASL request | 1 / 1 | failed | no | no; discard |

In the first trial, the original `DFSClient` retries after the injected
`IOException`, and the token check still succeeds. In the second, the injected
exception prevents the remaining target activation; this trial is discarded
under the user's target-retention rule. The reaggregated summaries for both
trials contain no fatal HDFS-14 occurrence. No new bug is claimed.

Production method and branch-outcome coverage did not increase. The first
fault adds one outcome on DoorWeave's synthetic fault branch; it is excluded
from the production coverage gain.

## Reproduction and evidence

From `/users/ZhenyuLi/baseline` with the released Hadoop distribution and
GraphChecker core jar named in the Python scripts:

```sh
python3 .study-repairs/unit-test-pivot/hdfs14/static_probe.py
python3 .study-repairs/unit-test-pivot/hdfs14/run_smoke.py --weave-only
python3 .study-repairs/unit-test-pivot/hdfs14/adapter/build.py
python3 .study-repairs/unit-test-pivot/hdfs14/run_original.py \
  --output .study-repairs/unit-test-pivot/hdfs14/healthy_scoped
python3 .study-repairs/unit-test-pivot/hdfs14/run_original.py \
  --output .study-repairs/unit-test-pivot/hdfs14/trial_sasl_first \
  --fault-trial .study-repairs/unit-test-pivot/hdfs14/trial-sasl-first.json
python3 .study-repairs/unit-test-pivot/hdfs14/run_original.py \
  --output .study-repairs/unit-test-pivot/hdfs14/trial_sasl_second \
  --fault-trial .study-repairs/unit-test-pivot/hdfs14/trial-sasl-second.json
```

See `healthy_scoped/trace/concolic_region_plan.jsonl` for distinct target
addresses and marker closure, each run's `manifest.json` for measured times,
`trace/runtime_trace.jsonl` for strict fault events and guard outcomes, and
`trace/summary.json` for the target oracle. The checklist entry at
`../cases/HDFS-14/result.json` summarizes these artifacts. Successful pipeline
stages totaled 98.265 seconds; shell and analysis time are excluded.
