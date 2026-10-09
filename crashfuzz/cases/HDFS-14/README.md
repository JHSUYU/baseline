# HDFS-14: block token password comparison

The graph-independent campaign runs the original Hadoop 3.4.3 embedded
cluster JUnit `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
Its default `MiniDFSCluster` has one NameNode and one DataNode. Case-local ASM
hooks record the selected `BlockTokenSecretManager.checkAccess` comparison
`MessageDigest.isEqual(retrievePassword(id), token.getPassword())` at released
source line 411 and the corresponding `InvalidToken` throw at line 412.

Both independent healthy instrumented runs passed and reached the selected
comparison twice with matching passwords. Three actual socket-read call sites
in `SaslDataTransferServer.doSaslHandshake` supply I/O fault points; JaCoCo
supplies production coverage feedback. A calibration EOF at the first socket
read matched and applied exactly once. The original JUnit still passed, and
both comparison checks ran after the fault with matching passwords.

Fault plans identify an I/O marker, call site, logical DataNode source, hit
ordinal, and exception type. A sequence contributes coverage or I/O feedback
only when every requested exception matches and applies in order and the
selected comparison executes after the final exception. The fixture's only
DataNode is mapped to logical source `hdfs/datanode/0`; this case does not
claim a multi-DataNode run.

The tmux session `hdfs14-independent-campaign` uses the atomic checkpoint
`independent/campaign-state.json` and writes each trial's duration and outcome
to `independent-trial-ledger.csv`. Its initial budget is 80 trials and up to
eight ordered exceptions, with an extension to 128 trials and ten exceptions
only for recent valid production coverage or stable I/O novelty. An observed
selected throw is a candidate for replay and source review.

The prior two region-woven trials are preserved in
[legacy-graph-result.json](legacy-graph-result.json) and excluded from the
current campaign.

## Completed result and source review

The 80-trial budget extended to 128 because valid trial 79 added production
`LeaseRenewer` method/branch coverage. The campaign then completed 128 exact
ordered injections, with 51 trials reaching this same password comparison
after the final exception. Every one of those 51 original JUnit runs passed;
their post-fault checks each used one key ID and found equal passwords. No
selected `InvalidToken` was thrown. The deepest tested sequence had four
exceptions, and the final eight trials added no valid production method,
covered branch count, or stable I/O family. Total healthy plus fault-trial
runtime was 4,132.810 seconds. Each trial's duration and outcome are in
`independent-trial-ledger.csv`; the independent trace audit is
`independent/audit-summary.json` (zero discrepancies).
The checkpoint and all 128 compact trial plans, traces, and manifests are
also preserved in `independent/compact-evidence.tar.gz`, with SHA-256 in
`independent/compact-evidence-index.json`.
The complete raw `runs/` tree was separately archived on node1 and verified
byte for byte before removing the node0 scratch copy; see
[`full-raw-archive.md`](independent/full-raw-archive.md) for the receipt and
restore command.

Released Hadoop 3.4.3 source lines 411–414 call `checkAccess(id, ...)`, then
recompute the token password and compare it with the password carried by the
token. A mismatch would throw the selected `InvalidToken`. The exact hook
observed no mismatch in any strict post-fault trial, so this case has no new
bug candidate. These faults exercised the encrypted data-transfer SASL reads
on the original one-DataNode fixture; they do not claim to cover a separate
NameNode key-delivery failure.
