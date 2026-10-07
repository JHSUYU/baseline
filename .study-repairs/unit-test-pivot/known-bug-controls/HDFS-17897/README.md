# HDFS-17897 calibration: stale encryption key during striped checksum

This is a **known bug control**, not a new finding or one of the original 102
selected candidate checks. Its check is now tracked separately as HDFS-54 in
the expanded checklist. It uses Hadoop 3.4.3 release JARs and a case-local MiniDFSCluster
JUnit derived from the unchanged `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey`
test. The one workload change is an XOR-2-1 erasure-coded file, to execute the
striped checksum branch. No GraphChecker runtime or Docker cluster is used.

## Source mechanism

`FileChecksumHelper.StripedFileNonStripedChecksumComputer#checksumBlockGroup`
in 3.4.3 catches `InvalidBlockTokenException` and generic `IOException`, but
does not specially catch `InvalidEncryptionKeyException`. The replicated
`checksumBlock` method clears the cached `DataEncryptionKey` and retries the
same block once. A stale key in the striped path therefore poisons every
DataNode attempt for that block group and later retries by the same client.

The control obtains a healthy checksum in a real 1 NameNode / 3 DataNode
encrypted-transfer cluster; retains the client's cached DEK; rotates the NN
block keys and waits until the cached key ID is absent from every DN; then
requests the striped checksum twice. This follows the original JUnit's
key-expiration procedure and checks the downstream operation, not merely the
presence of an injected exception. The fixed comparison recompiles only
`FileChecksumHelper.java` from the exact 3.4.3 source with PR #8364's
`InvalidEncryptionKeyException` clear-and-retry branch added. A diagnostic
line in the second fixed run proves that branch executed. The workload and
cluster setup are identical. The fault is NN key rotation and expiry at DNs;
the `InvalidEncryptionKeyException` is emitted by the real DN SASL handshake.

Sources: [HDFS-17897](https://issues.apache.org/jira/browse/HDFS-17897),
[fix PR #8364](https://github.com/apache/hadoop/pull/8364/files),
[related PR #8698](https://github.com/apache/hadoop/pull/8698).

## Run

```sh
python3 run_control.py --mode original --output evidence/original-01
python3 run_control.py --mode fixed --output evidence/fixed-01
```

`manifest.json` records each elapsed time and release source SHA-256; the
JUnit log gives the exact key ID, post-expiry exception, repeated retry, and
checksum result. Both test modes assert their expected outcome, so a JUnit
pass in the original mode means the known bug reproduced.

## Outcome

| Mode | Run time | Observed result |
| --- | ---: | --- |
| Original 3.4.3, run 1 | 28.372 s | `PathIOException`, same-client retry also fails |
| Original 3.4.3, run 2 | 24.551 s | Same failure and repeated failure |
| Clear-and-retry fix, run 1 | 23.841 s | Checksum equals healthy result |
| Clear-and-retry fix, run 2 | 27.016 s | Patch class loaded; retry branch executed; checksum equals healthy result |

Both original runs logged the DataNode's real
`InvalidEncryptionKeyException`, followed by striped block-group exhaustion.
The fixed run logged `CONTROL patched_clear_and_retry_bg=-1` before success.
See `result.json` and `known-bug-evidence.tar.gz` for hashes and full logs.
The failure oracle is the striped `getFileChecksum` operation after the cached
key has expired on all DNs; an isolated SASL exception alone is not counted
as this bug.

## Baseline implication

The relevant I/O boundary is the client-to-DN SASL handshake inside
`checksumBlockGroup`, while the coordinating state is the NN-issued key ID,
the client's cached DEK, and the DNs' retained block keys. A useful
graph-free fault input must retain the stale-key condition across the
candidate DNs until the client explicitly clears its cache. A one-off
exception at one DN may allow the loop to succeed at another DN and hide the
missing recovery branch. The I/O family and role selector should include
NN key issue/rotation, client-to-DN SASL setup, and each candidate DN's
handshake for the same block group. The feedback must record the block group,
file, cached key ID, DN key membership, branch outcome, and downstream
checksum result. Code coverage is useful for selecting new paths but is not
itself a bug oracle. This calibration also shows why a candidate check list
should include sibling retry paths and missing-catch cases around the same
I/O operation, rather than only explicit `if` or `assert` locations.
