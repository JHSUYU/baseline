# HDFS-14 isolated healthy seed

`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite` is a
two-instance parameterized MiniDFSCluster test. The original exact Surefire
method selector ran zero JUnit tests. The pinned `*` selector in this package
selects both instances. The test starts a plaintext cluster, writes a file,
restarts it with encrypted transfer and block tokens, then reads the file and
checks its checksum. The selected six-argument
`BlockTokenSecretManager.checkAccess` compares a recomputed block-token
password with the token's password at Hadoop 3.4.3 lines 411–412.

The site file includes the typed `BPServiceActor.sendHeartBeat` IOException
door at line 563. Its enclosing offer loop catches IOException at lines
786–790 and continues. A heartbeat response can carry a key-update command
consumed by `BPOfferService` at lines 774–786. This is a plausible pretarget
I/O disturbance, but whether it occurs before and remains causally connected
to this target must be measured in the healthy trace. The adapter also exposes
the typed `hdfs:sasl-first-response-read` door. Faulting that door may abort
the same transfer; it must not be counted as target-retaining without runtime
evidence. A missing token key throws an earlier `InvalidToken`, not the HDFS-14
password comparison.

Only a single fault-free seed is run. Admission requires two passing JUnit
instances, exact check observation on a named DataNode, a valid site catalog,
and an eligible pretarget door. This package does not mark HDFS-14 complete.

Run `python3 preflight.py --static` on node0. Dispatch alone may run
`run_healthy.sh` on node2 with `MALLORY_DISPATCH_ADMITTED=1`; the runner uses
the shared HDFS lane lock and a unique resumable output directory. No Docker.
