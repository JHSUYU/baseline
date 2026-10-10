# HDFS-14 registration RPC v2 healthy gap

The node2 calibration at
`/tmp/mallory-hdfs14-register-rpc-v2-node2-healthy` terminated naturally as
`calibration_complete` in 16.422 seconds. The two parameterized
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite` JUnit
instances passed (2 tests, 0 failures, 0 errors). The target class catalog
matched SHA-256
`350e35993314d4ce0dd4e32d150d7160e0923429f77154a2012eb47e0002860f`.
The selected six-argument `BlockTokenSecretManager.checkAccess` check at
line 411 occurred at sequences 191 and 210 on `hdfs-cluster-2/dn0`, and 384
and 398 on `hdfs-cluster-4/dn0`; the line 412 throw did not occur.

The typed `BPServiceActor.register` →
`DatanodeProtocolClientSideTranslatorPB.registerDatanode` IOException door
at line 829 occurred at sequences 19, 117, 230, and 324. **All four door
events have `node=unknown`**, including seq117 on the same JVM thread as the
later cluster-2/dn0 key writes and seq324 on the same thread as the cluster-4
ones. The trace emitted four `NODE_IDENTITY_GAP` events with reason
`unregistered_receiver`. The corresponding RPC responses at seq121 and
seq328 and `BlockTokenSecretManager.addKeys` writes at seq124–126 and
seq331–333 are named DataNode events, but their region occurrence was created
with an `unknown:0:...BPServiceActor#register...` identity. The initial
registration door cannot be selected with a runtime-matched DataNode identity.

The source explains the retry semantics. `BPServiceActor.register` calls
`registerDatanode` at line 829, catches a plain IOException at lines 840–842,
waits one second at lines 843–844, and calls
`BPOfferService.registrationSucceeded` at line 852 after successful
registration. That method installs the initial exported block keys at lines
428–431. The adapter's `actorEnter` and `serviceActorEnter` resolve the
`BPServiceActor.dn` receiver through `Probe.withRegisteredNode`; the trace
shows that receiver is unregistered when these early `register` regions
begin. Its existing `MiniDFSCluster.startDataNodes` lifecycle hook registers
the DataNode immediately before `runDatanodeDaemon`, after the call to
`DataNode.instantiateDataNode`. The latter can start the block-pool actor
before the lifecycle hook has bound the logical DataNode identity. The actor's
`dn` and `bpos` references are concrete, but the current hooks cannot derive
the stable `hdfs-cluster-N/dn0` identity from either at this earlier point.
The NameNode address and RPC port identify the remote endpoint; they do not
establish the DataNode's logical owner or restart epoch on their own.

Independent recomputation with `OccurrenceGraph(...,
reject_coarse_roots=True)` found zero event-time witnesses across all four
@829 doors × four selected checks, both with and without candidate edges.
The graph has 140 observed edges (94 RPC, 22 task, 24 region-parent) and 12
candidate state edges. The `allKeys` write at seq126 is paired with reads
at seq190/209, and the write at seq332 with reads at seq383/397, but each
state event reports `version_confidence=sampled`. Thus even correcting the
door's actor identity would yield, at most, a candidate key-state edge with
the current instrumentation. It would not by itself establish the required
observed event-time path or prove that an injected retry preserves the target.

The archived compressed trace SHA-256 is
`eb247aa2214451dab9ba5104a6d3368653fa089df7bb5e933eb7a44bb11cac22`;
the decompressed event-stream SHA-256 is
`382ec66b4f2e799abda8f24836585a48c71fe690597029253f017f8899ff9290`.
The campaign config SHA-256 is
`b8bef3072219b06e675f4105e80429fbcf17c86875eafce1bbf80f7d0066d7c9`.

**Disposition:** valid healthy JUnit and exact target; no observed injectable
closure door and no target-retaining fault trial. The 80-trial, 3600-second,
three-fault full campaign is not staged from this seed. A future diagnostic
would need an earlier source-backed DataNode identity hook plus exact
key-state provenance (or another observed edge) before full admission.
