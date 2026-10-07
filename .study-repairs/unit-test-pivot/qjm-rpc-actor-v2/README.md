# QJM RPC actor V2: offline repair for HDFS-07/09/10

This independent overlay repairs the old `Client.getRpcResponse` selector in
HDFS-07/09/10. The old probes normalized the RPC thread name by replacing the
dynamic port with `:port` and all digits with `N`. That conflated different
JournalNodes. It cannot establish that an injected response fault and a later
target check concern the same JournalNode.

## Identity chain

1. After `JournalNodeRpcServer.start`, the hook reads the actual listener port
   and `dfs.journalnode.edits.dir` from that server's `JournalNode`, then records
   `NODE_PORT_REGISTER(port, journalnode-N, storageRoot)`.
2. At `Client.getRpcResponse(Call, Connection, ...)`, the hook reads the actual
   `Connection.remoteId.getAddress().getPort()` via the Java 8 synthetic
   accessor. The probe records `RPC_PEER_RESOLVED(port, journalnode-N)` and uses
   that actor as its `sourceKey`. Unknown or ambiguous ports emit
   `RPC_ACTOR_UNBOUND` and **cannot inject**.
3. HDFS-07 already emits `journalNode` from `Journal.storage.getRoot()` at its
   `acceptRecovery` target. HDFS-09 and HDFS-10 now bind the same storage root
   at entry to `checkRequest` and `checkWriteRequest`, and emit `journalNode`
   on `TARGET_CHECK`. `strict_receipt.py` requires the requested fault, a
   registered peer, and the selected same-actor target after the final fault.

The hook is based on the existing HDFS-08 listener-port registration and
connection-port read, with stricter fail-closed handling for unknown actors.
The case-local target and file-I/O hooks are copied into each new overlay;
historical file-only evidence remains separate from the previous coarse RPC
trials. No graph runtime or Docker is used.

## Offline build and evidence

`python3 build_offline.py` creates self-contained case overlays under
`build/HDFS-{07,09,10}/overlay`. It asserts exact bytecode site counts, compiles
against released Hadoop 3.4.3, runs the registry and strict-receipt smoke
checks, and verifies all changed classes with ASM `CheckClassAdapter` on the
full Hadoop classpath. It does **not** launch a cluster or JUnit. The build
uses the original case target/file overlay as input without editing it.

Validation completed on 2026-10-07: all three overlays compiled, registry
smoke passed, and `CheckClassAdapter` reported no errors. Run
`python3 strict_receipt.py --self-test` for the trace-gate smoke.

## Next runtime gates for each case

Each case requires its own unchanged original embedded-cluster JUnit with a
fresh fixture and a new checkpoint. HDFS-07 uses
`TestQuorumJournalManager#testRecoverAfterIncompleteRecovery`; HDFS-09 and
HDFS-10 each use `TestQuorumJournalManager#testSingleWriter`, but their target
hooks and oracles differ. Run two healthy calibrations per case, checking that
all three JournalNodes register distinct listener ports, that QJM RPC events
resolve to these actor keys, and that the target events carry the corresponding
storage-root actor. Preserve the raw registration, peer, fault, target, JUnit,
and JaCoCo evidence. Then use `strict_receipt.py` per plan and selected actor.
Only a fully applied sequence with the selected target after its final fault
counts as an effective actor-aware trial. A target exception still requires
source review and clean replay before bug classification.

This work is an offline implementation and bytecode validation. No new
actor-aware HDFS-07/09/10 JUnit or fuzz trial has run, so none of their
`actor_identity_recheck_pending` results is complete yet.
