# HDFS-14: block-token password check

The unchanged Hadoop 3.4.3
`TestEncryptedTransfer.testEncryptedReadDefaultAlgorithmCipherSuite[0]`
JUnit child runs an embedded one-NameNode, one-DataNode
`MiniDFSCluster`. It reads and checksums a file, restarts the cluster
with encrypted transfer and block tokens, then reads and checksums again.
The selected `BlockTokenSecretManager.checkAccess` check rejects a token
whose password does not match. The healthy test reached its guard twice,
both nonfatal.

Two SASL request exception trials each matched and applied one fault.
The first retained the target after the client retried; the second ended
before the remaining target activation. Neither took the target's fatal
outcome. Production method and branch-outcome coverage did not increase;
the first trial changed only a synthetic injection branch. The recorded
phase time was 98.265 seconds.

The exact plans, test outcomes, and source location are in
[result.json](../cases/HDFS-14/result.json) and [the compact two-trial evidence](../cases/HDFS-14/evidence/legacy-sasl-trials.json). Two historical
trials leave the current 48-trial budget and additional relevant I/O
families open. No new bug was confirmed.
