# HDFS-12 full campaign staging

This package selects the existing indexed MiniDFSCluster test
`TestEncryptedTransfer#testLongLivedClient[0]`. Its healthy run passed one
JUnit test, reached the exact `BlockTokenSecretManager.retrievePassword`
check on `hdfs-cluster-2/dn0`, and did not throw the selected `InvalidToken`.
The case-local audit verifies the heartbeat command, `addKeys`, map read, and
selected check path. Frozen fa5f's generic graph audit remains negative because
it lacks that key read-from edge; the full campaign records this limitation.

The prior one-, two-, and three-heartbeat IOException diagnostics were
target-retaining but did not produce a missing key. The full budget is
80 fault trials, 3600 seconds, and at most three faults per trial. The
one-fault pilot is pinned as a recovery-site selection hint, with regular
exploration every fifth fault trial. An exact selected throw requires separate
source review and replay before a bug claim.

The package is staged on node2 and has passed static SHA preflight. It must
wait for HDFS-26's terminal archive, an independent dispatch host/lock gate,
and `MALLORY_DISPATCH_ADMITTED=1` before its runner starts. Its private output
is `/tmp/mallory-hdfs12-key-update-v3-full`; the source/build lock is
`/tmp/mallory-lanes/hdfs-identity-v8-node2.lock`.
