# HDFS-12 bounded subcampaign, checklist pending (2026-10-06)

Owner: `site_hdfs12`. Resume shell: `tmux attach -t hdfs12-case`.
Checkpoint: `.study-repairs/unit-test-pivot/cases/HDFS-12/result.json`.
The final multi-round campaign has ended; rerun the idempotent summary with
`python3 .study-repairs/unit-test-pivot/hdfs12/summarize_trials.py`.

## Exact target and original test

In Hadoop **release-3.4.3**, `BlockTokenSecretManager.retrievePassword`
reads `allKeys.get(identifier.getKeyId())` at line 509, checks
`key == null` at line 511, and throws `InvalidToken` at line 512.
GraphChecker bytecode target: guard `#u25`, throw `#u37`. The
selection-list line 514 is the error-message continuation, not the throw.
Source was reviewed at Git tag `rel/release-3.4.3`, not the local trunk.

Both workloads are unmodified released Hadoop 3.4.3 JUnit children of
`org.apache.hadoop.hdfs.TestEncryptedTransfer`:

- `testEncryptedReadDefaultAlgorithmCipherSuite[0]`: encrypted read and
  SASL server read fault family.
- `testLongLivedClient[0]`: MiniDFSCluster encrypted restart, 2-second
  key update interval and lifetime, `clearAllKeysForTesting()`, read,
  15-second wait, then read/checksum again. This reaches key rotation.

The test uses its default one NameNode and one DataNode. No Docker or
handwritten workload was used.

## Healthy graph

The final 27-class GraphChecker SEED/LineageScan/weave scope, DataNode source
adapter, and fault catalog live under `producer-heartbeat-door/`. Two
independent healthy `testLongLivedClient[0]` runs each exited 0 and
reached four distinct target request occurrences on
`hdfs/datanode/0#epoch0`; the guard was true four times. Target closure:
11 full occurrence addresses, 85 observed fault events, zero BLOCKING gaps.
Heartbeat, RPC request/response, BPOfferService key imports, and SASL read
members are admitted. Producer membership is
`CANDIDATE/SHARED_LOCATION_DEMAND_V1`, with
`edgeEvidence=UNAVAILABLE`: this is **not** an exact read-from edge.

The post-`sendHeartBeat` marker at hit ordinals 3, 5, and 6 precedes a
same-DataNode `BlockTokenSecretManager.addKeys` import by 226 trace events
in both healthy replays. The `Client.getRpcResponse` response markers and
`Client$Connection.sendRpcRequest` request marker at hit ordinal 6 are
inside that same heartbeat call, with the same source and closure address.
The selector manifest in `producer-heartbeat-door/trial-plans/manifest.json`
records both healthy replay matches.

Hadoop source at `rel/release-3.4.3` shows
`BlockManager.addKeyUpdateCommand` creates a `KeyUpdateCommand` and
clears `needKeyUpdate` before acknowledgment (lines 1660–1666).
`BPServiceActor.offerService` handles heartbeat responses and commands;
`BlockTokenSecretManager.addKeys` inserts received key IDs into
`allKeys` (lines 224–238). This motivated the fault window, but no bug
claim follows without the target exception.

## Bounded fault budget and outcome

The checklist row was regenerated from trace artifacts:

| Family | Trials | Observation |
| --- | ---: | --- |
| SASL SERVER_READ EOF/timeout | 8 | 6 target retaining, 2 target lost |
| Key-update heartbeat response loss | 10 | 8 target retaining; a six-fault retry loses DataNode/target |
| Direct Hadoop IPC response IO/EOF/timeout | 3 | all 3 exact applied, target retaining |
| Direct Hadoop IPC request connect timeout | 1 | exact applied, target retaining |

Total: **22 trials, 44 fault events applied, 21 fully applied trials,
18 target-retaining trials, zero target `InvalidToken` exceptions**.
The incomplete six-fault attempt applied three of six; its retry applied
all six and lost the target. A missing target is excluded by the oracle.
Target-retaining runs added 12 branch pairs in the SASL scope and 16 in
the key-update scope, with zero new method-entry signatures.

Measured final-campaign process durations total **867.342 seconds**
(static work, healthy tests, trials, aggregation), excluding earlier
feasibility probes and source review. Every trial duration and result is
in `cases/HDFS-12/result.json`. Mark: **no confirmed new bug**.

Checklist status is **pending**. NameNode command payload identity and exact
`allKeys.put`→`allKeys.get` runtime read-from have not been proved;
the closure explicitly labels their relation CANDIDATE. This result is
a bounded negative subcampaign for the original one-DataNode test, not a
claim that every HDFS key-update execution is correct.
