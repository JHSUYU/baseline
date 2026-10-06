# HDFS-11: encryption-key lookup under original cluster test

The selected check is
`BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])` in
Hadoop 3.4.3. The `allKeys.get(keyId)` call is at source line 551, the
null guard at 552, and its `InvalidEncryptionKeyException` throw at 553.
The selection-list line 555 continues the exception message.

The workload is the unchanged
`TestEncryptedTransfer.testEncryptedReadDefaultAlgorithmCipherSuite[0]`
JUnit child with its embedded one-NameNode, one-DataNode
`MiniDFSCluster`. The healthy test reached the guard twice, both
nonfatal. The historical campaign ran 19 applied trials across SASL
server-read and key-update control-plane I/O. Sixteen retained the target;
none produced the selected exception. The final nine-trial sequence ledger
and exact selectors are preserved in
[cases/HDFS-11/evidence/legacy-key-path-trials.json](cases/HDFS-11/evidence/legacy-key-path-trials.json).
Ten earlier SASL trial plans and outcomes are preserved in
[cases/HDFS-11/evidence/legacy-server-read-trials.json](cases/HDFS-11/evidence/legacy-server-read-trials.json).

The final key-path campaign gained ten scoped branch outcome pairs and
zero new method entries against its healthy run. The campaign's recorded
phase time was 543.904 seconds. Its original 19 trials leave the current
48-trial budget and further I/O diversity open. No new bug was confirmed.
See [result.json](cases/HDFS-11/result.json) for trial outcomes and timing.
