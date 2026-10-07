# HDFS-12 actor V2 preflight: original long-lived JUnit

Status: isolated producer overlay compiled and passed offline verification;
**no HDFS-12 V2 JUnit or fault run has started**. Keep HDFS-11's paused
overlay/checkpoint intact, and wait for node1's explicit handoff before
starting a cluster.

## Original workload and target

Use the released Hadoop 3.4.3 `TestEncryptedTransfer#testLongLivedClient[0]`
JUnit child. `[0]` sets `resolverClazz == null`, so the encrypted transfer is
actually exercised. The test first builds an ordinary MiniDFSCluster, shuts it
down, and starts an encrypted cluster over the same local data directories
(`writeUnencryptedAndThenRestartEncryptedCluster`, source lines 136–160). V2's
startup episode must distinguish these DataNode instances even though their
directory paths can repeat.

In source lines 300–321, the test sets the NameNode block-token update
interval and token lifetime to 2 seconds, clears its keys, reads and checksums
a file, sleeps 15 seconds, and reads/checksums it again. The NameNode rotates
keys in `BlockTokenSecretManager.updateKeys` (lines 244–274) and exports them
at lines 201–207. A heartbeat can carry a `KeyUpdateCommand` when
`DatanodeDescriptor.needKeyUpdate()` is true (`BlockManager` lines 1660–1666,
called by `DatanodeManager` line 1925). The DataNode sends the heartbeat at
`BPServiceActor.sendHeartBeat` lines 563–575, enqueues response commands in
`offerService` line 737, and applies the active-NameNode command via the
command-processing thread and `BPOfferService.processCommandFromActive`
lines 779–784. Worker `BlockTokenSecretManager.addKeys` writes received keys
into `allKeys` at lines 224–235. The selected HDFS-12 check reads
`allKeys.get(identifier.getKeyId())` at line 509, guards `key == null` at
line 511, and throws the selected missing-key `InvalidToken` at line 512.
The expired-token throw at lines 503–505 is a different outcome.

The archived, coarse-actor healthy trace recorded four selected checks:
two before rotation with key ID 372364637 and two afterward with key ID
372364640. It also recorded seven heartbeat hooks and three received
key-update hooks. These event counts demonstrate that the workload can reach
the path; the old `hdfs/datanode/0` label and global ordinal cannot establish
same-incarnation fault-to-target identity. No archived trial is a V2 trial.

## Current V2 coverage gap

The isolated `hdfs-key-actor-v2` overlay binds the real `DataNode`, its
`BlockTokenSecretManager`, and its SASL receiver to a startup episode and
block-pool label. It records the selected target and the three
`SaslDataTransferServer.doSaslHandshake` socket-read sites. Its
`PatchHdfsKeyActor` contains **no** `BPServiceActor`, `BPOfferService`,
`KeyUpdateCommand`, heartbeat response, or `addKeys` hook. Thus a healthy V2
run can verify the exact target actor but cannot seed a producer-side key
update I/O fault. The archived `PatchHdfs12KeyRpc` places a hook before the
local `BlockPoolTokenSecretManager.addKeys` call and labels it RPC; that call
is command application after the RPC and its old probe still uses a fixed
DataNode label. Do not reuse that label as V2 evidence.

The case-local [actor-producer-v2](actor-producer-v2) overlay extends the
original HDFS-11 actor/SASL/target hooks without changing the original JUnit
or HDFS-11's checkpoint. Its `BPServiceActor.offerService` hook receives the
**actual decoded heartbeat response** immediately after `sendHeartBeat`
returns and before commands are enqueued. On a `KeyUpdateCommand`, it records
the real DataNode object/UUID and startup episode, raw and logical block pool,
raw NameNode endpoint plus `NN0`/`NN1` label, per-JVM unique manager and
command identity counters (with object hashes retained for diagnostics),
current key ID, all exported key IDs, and the response ordinal. The response
fault throws `IOException`/`SocketTimeoutException` or adds a bounded 1.5 s
delay at this boundary. This models DataNode-side loss or late handling of a
received RPC response; it does not claim the NameNode failed to send it.

Separate hooks immediately before and after the **actual** active/standby
`BPOfferService.processCommand*` call to `BlockPoolTokenSecretManager.addKeys`
record local application. Its exception/delay door is explicitly labeled
`LOCAL_APPLY`. The probe accepts the same command only if command object,
DataNode episode/object/UUID, block pool, NameNode endpoint, manager, current
raw key ID, and all key IDs match the received response. The target
`allKeys.get` guard records the same manager identity and looked-up key ID.
This gives a within-DataNode response→application observation; the exact
NameNode key-generation read-from edge across IPC remains outside this
graph-free baseline. The case only gains producer coverage if the healthy
target is reached after a rotated-key response and matched import on the same
manager. A missing producer marker leaves it pending; SASL-only seeds cannot
authorize a producer-key campaign.

Offline [receipt](actor-producer-v2/offline-smoke-receipt.json): released Hadoop
3.4.3 HDFS/tests JAR SHA-256 values, six woven classes loaded with
`-Xverify:all`, bytecode hook counts 1 heartbeat response / 2 key-import
calls, 11 exact-selector fail-closed checks (including other DN, block pool,
NameNode, raw key ID), and 18 Python gate/scheduler/producer-link tests. The
overlay SHA-256 is `7baac3afd45a14dfd3a025c6ba59d1827eada019e592f44d975087653e5798cb`.
There has not yet been an original JUnit smoke under this overlay, so hook
execution and runtime key-link stability remain to be measured.

## Bounded smoke and budget after node handoff

1. The HDFS-12-only offline build is complete. To repeat it without starting
   a cluster: `cd .../cases/HDFS-12/actor-producer-v2 && python3 offline_smoke.py`.
   The receipt includes released JAR SHA-256 values, overlay digest, hook
   counts, and the JaCoCo coverage collector source hash. Do not edit
   HDFS-11's `hdfs-key-actor-v2` classes or checkpoint.
2. Run two fresh, unchanged `testLongLivedClient[0]` healthy JUnits in
   separate scratch directories with port-0 MiniDFSCluster listeners,
   `-Xverify:all`, `-Xmx3g`, JaCoCo, and one JUnit child at a time. The
   exact isolated calibration commands, after node1 handoff, are:

   ```sh
   cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-12/actor-producer-v2
   python3 identity_gate.py calibrate --case HDFS-12 --output evidence/HDFS-12 --max-seeds 1 --timeout 600
   python3 identity_gate.py calibrate --case HDFS-12 --output evidence/HDFS-12 --max-seeds 2 --timeout 600
   ```

   The first command records `healthy-a` only and intentionally leaves the
   receipt awaiting seed two. The second reuses its manifest, then records
   `healthy-b`. The runner uses the unchanged parameterized `[0]` JUnit child,
   separate per-seed `test.build.data`/tmp/log paths, and port-0 cluster
   listeners. Record start/end UTC, exit code,
   peak RSS, per-seed scratch paths, raw DataNode/NN endpoints, exact target
   actor/pool, distinct early/late key IDs, and key-update response/import
   markers. Both seed digests and eligible full selectors must agree. No
   selected missing-key `InvalidToken` should occur in a healthy seed.
3. Use one observed key-update-bearing heartbeat response as the first
   one-fault smoke: inject a response-loss exception at its exact full
   actor-local occurrence. Use the seven-field fault plan, with raw key ID
   `*` because the NameNode seeds its ID randomly on each fresh JUnit; an
   explicit numeric raw key ID is accepted only when the observed ID matches.
   Require one exact match/application and a later
   selected check on the **same** DataNode episode and block pool. A lost
   target is an excluded trial, not a bug. Keep the original JUnit result and
   production JaCoCo probes/methods/branch-count feedback in the receipt.
   After the second seed passes, the following commands prepare and run exactly
   that plan once (only in the allocated node1 window). The generated run path
   uses the same sequence ID as the campaign, so a later campaign resume
   **reuses its manifest and never repeats this JUnit trial**:

   ```sh
   python3 prepare_smoke.py --output evidence/HDFS-12
   sh evidence/HDFS-12/run-smoke-response-loss.sh
   ```
4. Seed a fresh case-local queue from those two healthy runs. Start at 80
   **effective** target-retaining trials, up to eight ordered faults;
   optionally extend to 128/ten only if the last eight effective trials add
   production coverage or a new eligible I/O family. Cap attempted trials at
   600. Prioritize key-update-bearing RPC responses and newly exposed I/O,
   preserve a small exploration share, and checkpoint each plan/result so
   reconnect resumes unfinished work. Keep the prior 256 coarse-actor trials
   as historical evidence and do not import their IDs as V2 completions.
   After both seeds and the single response-loss smoke pass, start the sustained
   run in its own tmux session; the case directory is the only writable output:

   ```sh
   cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-12/actor-producer-v2
   tmux new-session -d -s hdfs12_key_actor_v2 -c /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-12/actor-producer-v2 'python3 campaign.py --case HDFS-12 --output evidence/HDFS-12 --max-attempts 600 --pause-on-candidate > evidence/HDFS-12/campaign.log 2>&1'
   ```

   Use `tmux attach -t hdfs12_key_actor_v2` to inspect progress. The campaign
   resumes an existing in-flight manifest and writes per-trial checkpoints;
   never import HDFS-11's prior 53 V2 attempts or rerun its planned IDs.
5. The oracle is a selected null-key `InvalidToken` after the matched fault
   and after the same-actor selected check, above the healthy count. Pause a
   candidate for exact replay and source review. A generic JUnit failure,
   expired-token exception, or missing target does not satisfy this oracle.

No node1 run is authorized by this document; root coordinates the SOLR-09,
HBASE-32, and HDFS handoff.
