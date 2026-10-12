# HDFS-14 Mallory node2 full stage

Status: staged offline, pending dispatch. The case uses the existing
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite` parameterized
MiniDFSCluster JUnit. The Maven method selector ends in `*` so both parameter
instances run; the older exact selector produced zero JUnit tests. The exact
selected six-argument `BlockTokenSecretManager.checkAccess` password comparison
is at Hadoop 3.4.3 lines 411–412. `DataXceiver.readBlock` invokes this overload
on its named DataNode worker.

The site file pins the `BPServiceActor.sendHeartBeat` `IOException` door.
The immutable adapter also exposes `hdfs:sasl-first-response-read` after the
client sends the first SASL message. Both are eligible I/O exceptions for the
runtime to measure; neither is a demonstrated cause of unequal token password
bytes. A missing key raises HDFS-12 before the selected comparison. The
healthy run must show a passing two-instance JUnit, the exact check, a named
DataNode, and an eligible door before promotion. Graph path evidence and any
causal gap are outcomes in the result.

The full budget is 80 fault trials, 3600 seconds, and at most three faults per
trial. A natural `budget_exhausted` or `queue_exhausted` terminal is complete;
the observed trial count and strict target count must be reported separately.

`python3 preflight_hdfs14_node2_full.py --static` checks package SHA pins and
the equivalent node0 source without Java. Only dispatch may run
`run_hdfs14_node2_full.sh` on node2 with `MALLORY_DISPATCH_ADMITTED=1`. The
runner takes the shared HDFS v8 lane lock, checks the node2 source and artifact
hashes, and writes to a unique resumable output directory. No Docker is used.
