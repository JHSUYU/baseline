# HDFS-09: QJM original cluster test

Selected check: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:504` in `Journal.checkRequest(RequestInfo)`: `reqInfo.getCommittedTxId() >= committedTxnId.get()`.

The workload is the unchanged Hadoop 3.4.3 `TestQuorumJournalManager#testSingleWriter` JUnit method. Its fixture starts three JournalNodes. The current graph-free campaign is `../../qjm-rpc-actor-v2/campaign_v2.py`, with the offline ASM I/O and target probes under `independent/src` and `../../qjm-rpc-actor-v2/`. It selects observed RPC/file fault points by runtime identity, collects JaCoCo coverage, and checks the target after applied faults.

The final result is in [`../../../data/cases/HDFS-09/result.json`](../../../data/cases/HDFS-09/result.json): 180 trials, 180 fully applied, 128 reached the check after a fault, 2383.082 recorded seconds, and bug mark `none`. The terminal audit is `../../qjm-rpc-actor-v2/evidence/HDFS-09/audit-terminal-128.json`. An observed exception at the guard is interpreted using the source semantics and replay evidence.

Run `./reproduce.sh` to inspect the selected test and invocation. `./reproduce.sh --run` advances the current QJM campaign by one plan after its offline build and calibration are prepared. The published terminal archive and audit remain under `../../qjm-rpc-actor-v2/evidence/HDFS-09/`.
