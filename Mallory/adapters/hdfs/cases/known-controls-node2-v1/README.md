# HDFS-54 and HDFS-55 known controls: node2 stage v1

Status: source and compiled-artifact stage. No JVM, healthy calibration, or
Mallory fault trial has been run from this package. Both controls live in
`known_issue_controls`, outside the original 102 selection. Their historical
CrashFuzz outcomes are not Mallory observations.

The source is released Hadoop 3.4.3 at commit
`9d50c6884666e794e45102260a4017bb31802e1b`. PR
[#8698](https://github.com/apache/hadoop/pull/8698) is HDFS-17967, a later
follow-up for DataXceiver and StripedBlockWriter paths. HDFS-54 and HDFS-55
here are the HDFS-17897 and HDFS-17899 controls that it references.

## Original-JUnit site campaigns: exact selected checks and outcome criteria

- **HDFS-54:** `FileChecksumHelper$StripedFileNonStripedChecksumComputer`
  `checksumBlocks` line 629 is branch `@629:branch:4`; the selected
  `PathIOException` throw is bytecode line `@631:throw:1`. Its source
  declaration spans lines 629-631. The original parameterized
  `TestFileChecksum#testStripedAndReplicatedFileChecksum2*` is used, with
  a wildcard so Surefire can execute the variants. A failure at this throw
  is only a known-bug candidate if the trace shows stale-key rejection and
  the failure is not the expected outcome of making every located DN fail.
  This unchanged JUnit enables block tokens but does not enable encrypted
  data transfer in its `@Before` fixture. The staged original-JUnit
  campaign therefore cannot by itself reproduce HDFS-17897's stale data
  encryption key mechanism. The historical known-bug differential used a
  separate adapted encrypted XOR-2-1 cluster workload.
- **HDFS-55:** the inventory-selected `KeyManager.newDataEncryptionKey`
  cache guard is `@123:branch:2`. This check **does not throw**. The
  separate DN `BlockTokenSecretManager.retrieveDataEncryptionKey` first
  reads `allKeys.get(keyId)`, branches at `@552:branch:1`, and throws
  `InvalidEncryptionKeyException` at `@555:throw:1` when absent. The
  original `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` is
  used. Detection requires a key-ID-bound link from the same cached key
  decision to a DN rejection, followed by a failed Balancer move/JUnit and
  no successful cache clear/retry. Generic injected `IOException`, a
  KeyManager branch alone, or a failed JUnit alone cannot establish it.
  This original JUnit enables encryption, but does not shorten key rotation
  and has a 60-second timeout. The historical known-bug differential used a
  separately adapted Balancer phase with persistent DN rejection.

Mallory core requires one check/throw target. HDFS-55's config includes the
selected KeyManager branch and the distinct DN guard as checks, with the DN
exception as the core throw. The case-local verifier checks both observed
guards. Its trial review reports only a candidate because this package has
no key-ID binding probe. A separate raw-key audit or differential replay is
needed before marking the known bug detected. The core's `target_reached`
field by itself is insufficient for HDFS-55.

## Real I/O doors and admission

HDFS-54 catalogs NN `ClientProtocol.getBlockLocations` and DN
`DFSClient.connectToDN` / checksum-response reads as typed `IOException`
doors. HDFS-55 catalogs NN `NamenodeProtocol.getBlockKeys` in the Balancer
updater, DN `BPOfferService.processCommandFromActive` before
`BlockPoolTokenSecretManager.addKeys`, and Balancer
`SaslDataTransferClient.socketSend` in `PendingMove.dispatch`.
These are source and bytecode candidates. A fresh healthy trace must show an
actual door in the target's event-time causal closure; local timelines and
coarse roots are excluded. The controller's full config has 80 trials,
3,600 seconds, and at most three faults per trial. The healthy config is a
separate no-fault calibration; it uses the same pinned workload and limits.

Run `python3 preflight.py --case HDFS-54 --mode healthy --static` and repeat
for HDFS-55 and `full` on node0 or node2. This scans class files and all
pinned source paths without a JVM. On node2, dispatch launches `run_node2.sh CASE healthy`
with `MALLORY_DISPATCH_ADMITTED=1`; the runner holds
`/tmp/mallory-lanes/hdfs-identity-v8-node2.lock`. The healthy output is
`/tmp/mallory-hdfs54-known-v1-node2-healthy` or its HDFS-55 counterpart.
After the healthy run, run the frozen core's `Mallory.core.audit` to write
`offline-causal-audit.json`, then `verify_control.py --case CASE
--healthy-output OUTPUT --require-audit`. The `full` runner requires this
gate and uses a unique resumable `-full` output. Reserve 6 GB on node2 for
the campaign and evidence archive. Inspect the natural terminal result and
archive hashes before any report publication.

`node0-static-preflight-receipts.json` records the four passing no-JVM
source-mirror checks. It is a package admission artifact, not a healthy JUnit
or fault-trial result. The node2 source tree must pass its own static check.

## Separate adapted controls

`adapted-controls-v1.json` records the exact workloads, source diffs,
fault models, probes, and JUnit oracles. `run_adapted.py --case CASE --static`
checks their pinned inputs without Java. Dispatch may later run
`MALLORY_DISPATCH_ADMITTED=1 python3 run_adapted.py --case CASE --run` on node2;
it holds the same node2 lock and writes only under
`/tmp/mallory-known-controls-adapted-v1`. These are **separate** from the
80-trial original-JUnit site campaigns and from the original-102 count.

### Adapted HDFS-54 encrypted checksum differential

The HDFS-54 adapted source keeps the released encrypted key-expiry workflow,
uses XOR-2-1 on three DNs, and changes the historical positive-control
assertion to a JUnit failure after the observed `PathIOException`. The
fixed clear-and-retry comparison must pass and restore the healthy checksum.

### Synthetic HDFS-55 response diagnostic

The HDFS-55 `adapted55/` overlay directly changes a **present** lookup result
to null after `allKeys.get(keyId)`. It is a diagnostic of the Balancer's
response to an `INVALID_KEY` wire result, not a reproduction of the
key-distribution failure in HDFS-17899. Its original/fixed comparison can
only receive `synthetic_missing_key_diagnostic_passed`, never a bug-detection
verdict. No run has occurred.

### Faithful HDFS-55 upstream I/O candidate

`faithful55/` records the separate upstream I/O candidate. The fault is a
typed `IOException` at the receiving DataNode's
`BPOfferService.processCommandFromActive` key-update application, before
`BlockPoolTokenSecretManager.addKeys`. The command processor catches that
exception, so the received update is lost. Short key rotation plus a
Balancer move before the next successful update could cause the untouched
`allKeys.get(keyId)` to return null. This candidate is source-backed but
timing-dependent and has **no executable admission** yet. A faithful verdict
requires a runtime key-ID/manager/endpoint link from NN rotation and missed
DN update to the naturally null guard, native `InvalidEncryptionKeyException`,
failed original JUnit with no cache clear, then passing fixed replay after
clear/retry. `faithful55/contract.json` states the required evidence.
