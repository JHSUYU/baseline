# HDFS-14 registration RPC diagnostic seed

The first HDFS-14 healthy run passed both instances of
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite`, reached
four exact `BlockTokenSecretManager.checkAccess` password checks on named
DataNodes, and saw seven typed doors. Its trace provides **zero** event-time
paths from any door to any check, even when candidate state edges are included.
In each target DataNode, the `allKeys` writes happened before the configured
heartbeat door. That seed cannot justify a full fuzz campaign.

The same trace shows `BPServiceActor` registration RPC responses at events
116 and 321 immediately before `BPOfferService.registrationSucceeded` installs
the exported block keys at events 119–121 and 324–326. Hadoop 3.4.3
`BPServiceActor.register` invokes
`DatanodeProtocolClientSideTranslatorPB.registerDatanode` at line 829; a plain
`IOException` is caught and retried after a one-second delay at lines 840–845.
The exact typed IOException door at this call is the sole new injection site
in this diagnostic seed. The `register` method is also instrumented as a region
so its door and subsequent key installation can be traced through one
invocation. The earlier heartbeat door remains present for comparison.

This package runs **one fault-free** parameterized MiniDFSCluster JUnit. The
review gate requires 2/0/0 JUnit, a named exact target, and an observed
event-time path from the new registration door to that target. A candidate
sampled map-state edge alone is insufficient to claim an observed path.
No full 80/3600/max3 campaign is staged from this package until its healthy
trace demonstrates the path and a later scoped diagnostic fault retains the
target. An injected registration IOException may merely delay startup.

`python3 preflight.py --static` verifies the immutable release, source and
package pins without running Java. Dispatch alone may run `run_healthy.sh` on
node2 with `MALLORY_DISPATCH_ADMITTED=1`. The runner takes the shared HDFS
lane lock and writes to a separate resumable output directory. No Docker.
