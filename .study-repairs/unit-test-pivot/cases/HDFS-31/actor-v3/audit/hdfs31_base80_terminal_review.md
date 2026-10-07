# HDFS-31 actor V3/V4 terminal review

## Check and unchanged workload

The selected Hadoop 3.4.3 check is
`DataNode.getBPOSForBlock(ExtendedBlock)` at
`hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java:1832–1835`.
It looks up the block-pool offer service and throws `IOException` if that
service is absent. The unchanged original embedded-cluster JUnit is
`org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero`.
Two no-fault JUnits passed in 18.515 and 15.767 seconds. Each reached the
selected same-block target and found the service present, with no selected
throw. The offline instrumentation overlay SHA is
`24435f63c124d259c328d441361f364b0dcd89e6259382f1110b2f2ab39d41f5`.

The fault point is `Client.getRpcResponse(Connection)` on the real BP actor's
NN0 endpoint. The runtime and independent auditor require the startup
episode, physical DataNode object, BP service, raw NN endpoint, registration
continuity, and pool-add event to agree with the later target. Fault plans
use relevant actor-bound I/O and production coverage feedback. The original
JUnit source and assertions were unchanged; there is no graph reconstruction,
GraphChecker runtime controller, or Docker workload.

## Budget and identity rule boundary

The V3 campaign reached a complete boundary at 21 attempts and 16 effective
under its stricter raw-UUID equality rule. Three pre-registration faults did
reach the same physical actor's target after a UUID was assigned; they remain
**uncredited in the old denominator**. The exact raw sequence and four
negative actor-identity controls are in
`actor-continuity-v4-review.md` and
`actor-continuity-v4-offline-audit.json`. V4 switched only at that saved
boundary. It kept the prior completed IDs, queue and 16 effective count,
then ran 73 new plans and credited 64 of them under the independently
validated continuity rule. Historical coarse-actor 80 attempts are separate
and contribute zero to this budget.

At 2026-10-07 15:45:13 UTC, the base budget stopped at 94 distinct
attempts, 87 strictly applied sequences, and **80 same-actor postfault target
reaches**. All 94 original JUnits exited zero. The independent raw audit
reconstructed 94/87/80 with zero issues and zero selected target exceptions.
The checkpoint has `in_flight=null` and SHA
`529f028ae784990f4650df4492c1d77fe3b792eac1bbaa0840a24b2131dcb2ee`.
The final tmux and this case's JUnit JVM exited. Every attempt's UTC,
duration, fault plan, identity rule, strictness, target outcome and raw
manifest are in `cases/HDFS-31/result.json` under `trial_results`.

The 94 fault JUnits took 1,740.463 seconds; the two healthy JUnits took
34.282 seconds, so the per-check original-JUnit total is **1,774.745
seconds**. Controller work, shared JVM lock and resource-gate waits are
excluded. The campaign tested depths one through four; the maximum allowed
depth was eight. The only stable actor-bound I/O family was the NN0 BP RPC
response. Global production coverage at stop was 9,205 branch identities,
36,661 lines, 8,425 methods and 29,214 probes, with effective-run gains
211/513/67/475. These global gains do not by themselves prove a new target
recovery behavior. Independent review of the last eight effective runs found
zero new branch IDs, target-path branch candidates or same-actor I/O families.
The configured 128-effective/max10 conditional extension therefore did not
activate. The base cap was 320 attempts and max eight faults per plan.

There was **no selected postfault IOException and no confirmed new bug**.
The observed target remained service-present in all credited trials. The
old coarse-actor result is preserved under `legacy_coarse_actor`; its old
counts and possible downstream JUnit failures are not mixed into V3/V4.

## Raw evidence and recovery

Node2 retains the original raw files, terminal checkpoint, independent
`base80_raw_audit.json` (SHA
`f44f4a86497a84241a57cef517898378138f293697d2a3e792052a58a9c60039`)
and `base80_novelty_audit.json` (SHA
`d3dd026f58f29597863de6b10dab6de61cd4e6f55e875df582765659db0a3b0a`).
The first 21 V3 plans were previously archived, restored on node1 and
verified 254/254 files; their tar SHA is
`601faffbc1616c15b2a5939bc4c9ffa1074816a3dde62e2580d6ea66dd98434d`.

The 73 V4 plans and terminal metadata comprise 734 files / 544,743,497 raw
bytes in `hdfs31-v4-0022-0094.tar.zst`, tar SHA
`81f8e29f6ba1b5d0127a6f5c5066c0a5e39957bdb309d0e7468d3d71d2c3ca9d`,
manifest SHA
`b9e83e45aa43b369b18499f66e5f811cdb64477b4279726f0d0776aacc60bb0f`.
The archive is durable on node2 under
`/users/ZhenyuLi/hdfs31-actor-v3-20261007/evidence/archives/` and on node0
under `/users/ZhenyuLi/hdfs31-v4-terminal-archive-20261007/`. Both compressed
copies have the same SHA. Node1 streamed the archive and checked every file
hash without expanding it; its 734/734 verification receipt is
`v4_terminal_node1_stream_receipt.json`. The temporary node1 compressed copy
was removed after the durable node0 mirror was verified, to keep node1 above
the shared disk gate. Node2 original raw files were not deleted. The
`archive_v4_terminal.py verify` command can stream-check either retained
compressed copy against the committed manifest.
