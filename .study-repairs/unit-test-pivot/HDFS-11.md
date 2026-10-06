# HDFS-11 — missing DataNode encryption block key

## Result and exact site

**Status: `pending_graph_precision`, with no observed HDFS-11 target exception.**
The unchanged owner test reached the exact guard in a healthy run. Across
19 strict trials, every requested fault matched and applied; 16 trials
reached the target again after injection, while three lost it. Ten trials
covered the DataNode SASL server read and nine covered the registration/key
producer path, IPC request/response, and client SASL send. The healthy trace
correlates the actual `allKeys.put` with both `allKeys.get` calls by map,
integer key, and returned `BlockKey` identity, but GraphChecker still marks
that relationship `CANDIDATE` with `edgeEvidence=UNAVAILABLE`. This is the
reason for the pending precision status, not an observed failure.
The check is `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])` in
Hadoop 3.4.3. `allKeys.get(keyId)` is at source line 551, `key == null` is
line 552, and `InvalidEncryptionKeyException` starts at line 553. The old
selection line 555 is the continuation of its message. Released bytecode
maps `ifnonnull` offset 25 to line 552, exception allocation offset 28 to
line 553, and message continuation offset 57 to line 555. GraphChecker
resolves `TARGET_SITE #u20`, guard `#u8`, fatal outcome `false`. The final
27-class graph gives it region
`REGION.53092d3e-263d-3a18-b7a5-ae5b437d96de`; the earlier 22-class
SASL-only graph used `REGION.c0d9d80b-cf85-36a4-87a7-f409be7dd190`.

The workload is the **unmodified original** JUnit4 child
`org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
It builds its own one NameNode, one DataNode `MiniDFSCluster`, writes and
reads a file, restarts with encrypted transfer, then reads and computes the
checksum. Parameter `[0]` enables the encrypted SASL path; `[1]` uses a
trusted-channel resolver and does not exercise this check. The generic
[parameterized runner patch](graphchecker-junit-parameterized.patch) selects
`[0]` while retaining JUnit setup, teardown, rules, and assertions.

## Static graph, runtime identity, and actual I/O doors

The first static SEED used 22 extracted Hadoop application classes, 485 Hadoop
classpath jars, and released 3.4.3 binary. Its healthy recording reaches
the exact guard twice, both with `outcome=true`. Initial DataNode
registration imports NameNode-exported keys into `allKeys`; the trace
observes `Map.put` and the later `Map.get` on the same receiver object and
the same returned `BlockKey` object. The graph marks key import `addKeys` as
`CANDIDATE` under `SHARED_LOCATION_DEMAND_V1`, with
**`edgeEvidence=UNAVAILABLE`**. This is value correspondence, not a proven
cross-process read-from edge.

The released Hadoop JAR has no GraphChecker request/source annotations at
the DataNode SASL entry. The isolated
[SASL identity adapter](hdfs11-sasl-identity/HdfsSaslRequestIdentity.java)
registers a stable logical DataNode source and opens one request root per
accepted SASL connection. Its [ASM adapter](hdfs11-sasl-identity/PatchSaslReceive.java)
records client `doSaslHandshake` SEND and matching server parsed-name RECEIVE.
It pairs actual TCP endpoints and verifies the received SASL name against
the sent name in memory; it changes no test operation or wire bytes. This
in-process side channel applies to the embedded `MiniDFSCluster`, not a
transport implementation for separate JVMs. Two healthy runs recorded two
matched SEND/RECEIVE pairs. The target full occurrence addresses and all
four server-read fault selectors were byte-for-byte identical across the
two scratch-cluster runs.

The stock client-side `HDFS_SASL:REQUEST` door is outside the first 22-class
target closure. The isolated [server-door builder](hdfs11-server-door/build.py)
adds EOF and socket-timeout faults at the real server SASL message read,
immediately before `DataTransferSaslUtil.readSaslMessageWithHandshakeSecret`.
It supplies a classpath catalog-resource overlay, then runs GraphChecker
SEED and region-state weave; it leaves the fixed core JAR and Hadoop JARs
unchanged. The door adds four healthy `FAULT_POINT_OBSERVED` events: two
exception kinds at each distinct target occurrence. The first target's
closure has no BLOCKING gap and includes key import as candidate plus its
server-read points. The second target is observed, but GraphChecker attaches
shared-location membership to the first target occurrence; no exact
key-import edge for the second is claimed.

```text
NameNode generateKeys/exportKeys
       │ registration / key-update control plane
       ▼
DataNode addKeys ── Map.put(allKeys, BlockKey)   [CANDIDATE location]
       │
       │ same receiver/value observed; edgeEvidence=UNAVAILABLE
       ▼
Client SASL SEND ── TCP ──> DataNode SASL RECEIVE
                               │ server-read EOF/timeout door
                               ▼
                    parse keyId → allKeys.get(keyId)
                               │
                               ▼
                    HDFS-11 `key == null` guard
```

## Fault campaign and coverage feedback

The [healthy manifest](hdfs11-server-door/healthy/manifest.json),
[runtime trace](hdfs11-server-door/healthy/trace/runtime_trace.jsonl),
[target plan](hdfs11-server-door/healthy/trace/concolic_region_plan.jsonl),
and [static/weave manifest](hdfs11-server-door/manifest.json) are the seed.
SEED took 38.939 s and weave 20.027 s. Two independent healthy original
JUnit runs took 10.995 s and 10.295 s; their aggregations took 1.419 s and
1.118 s. All exited zero. Each healthy run has two normal target guards;
the final one has 146 observed markers (142 original plus four server-read).

For each trial, the controller selected the full recorded marker, site,
occurrence, ordinal, and source, and reported `FAULT_MATCHED` and
`FAULT_APPLIED` for every step. `targetAfterFault=true` means a target guard
occurred after the last fault; the oracle additionally requires the HDFS-11
fatal branch or exception.

| Sequence | JVM time | Matched/applied | Target after last fault | Original JUnit | HDFS-11 fatal |
| --- | ---: | ---: | --- | --- | --- |
| First SASL read: EOF | 11.250 s | 1/1 | Yes; two normal guards | Pass | No |
| First SASL read: timeout | 12.306 s | 1/1 | Yes; two normal guards | Pass | No |
| Second SASL read: EOF | 11.356 s | 1/1 | No; target lost | Injected checksum I/O failure | No |
| Second SASL read: timeout | 11.695 s | 1/1 | No; target lost | Injected checksum I/O failure | No |
| First EOF → retry EOF | 20.894 s | 2/2 | Yes; two normal guards | Pass | No |
| First EOF → retry timeout | 19.783 s | 2/2 | Yes; two normal guards | Pass | No |
| First timeout → retry EOF | 17.292 s | 2/2 | Yes; two normal guards | Pass | No |
| First timeout → retry timeout | 21.197 s | 2/2 | Yes; two normal guards | Pass | No |
| First EOF → retry EOF → retry EOF | 28.802 s | 3/3 | Yes; two normal guards | Pass | No |
| First timeout → retry timeout → retry timeout | 32.021 s | 3/3 | Yes; two normal guards | Pass | No |

The first fault exposes a new full SASL request occurrence, justifying
ordered second-fault mutations. Both target-retaining one-fault traces and
all four two-fault traces aggregate with the exact target region, no
BLOCKING gap, and `edgeEvidence=UNAVAILABLE`. Across all trials, the
instrumented scope gains five branch `(site,outcome)` pairs and zero
`METHOD_ENTER` methods versus healthy. One new pair is
`BlockTokenSecretManager.updateKeys(long)#u5=true` in longer runs; this is
timing sensitive and does not establish a causal route from SASL read
failure to a missing key. The two three-fault runs add **zero** methods,
branch outcomes, target-closure regions, or fault-site classes beyond the
one- and two-fault union. Both remain on the normal HDFS-11 arm.

The server-read feedback subqueue is exhausted under this original
workload and the recorded server-read door class: further retry iterations
only repeat the same region and I/O site without new target-region or code
feedback. We stopped at three ordered faults after testing both EOF and
timeout variants. This bounded result does not rule out other workloads,
fault kinds, or key-rotation schedules. Ten fault trials ran; eight kept
the target after the last fault, two lost it, and none triggered
`InvalidEncryptionKeyException`. The measured sum of final SEED, weave,
two healthy JVMs and aggregations, ten trial JVMs, and eight faulted
aggregations is **279.280 s**. Trials ran partly in parallel, so this is
summed active run time rather than wall clock. Earlier feasibility probes
and manual source review are excluded.

## Registration/key path: final nine strict trials

The isolated [key-path builder](hdfs11-key-path/wire_plus/build_wire.py)
expanded the final SEED to 27 Hadoop classes and used GraphChecker’s IPC
request/response bridge, DataNode actor source/root hook, NameNode source
identity, and the two selected protobuf `WIRE_FLOW` mappings for block-key
ID and expiry. The source is the unchanged Hadoop 3.4.3 JAR; these are
recording/door overlays. SEED and region-state weave exited zero in 46.948 s
and 23.283 s. The final [healthy original JUnit run](hdfs11-key-path/wire_plus/healthy-final/manifest.json)
exited zero in 11.059 s; aggregate took 2.572 s. It recorded two normal
HDFS-11 guards, 14 target-closure occurrence addresses, 51 fault-marker
observations, eight marker/site classes, and no `BLOCKING` gap. The 10
`ADMISSION_GAP`, three shared-occurrence, and two lost-lineage diagnostics
remain explicit. The original JUnit operations and assertions were not
modified.

The final healthy [runtime trace](hdfs11-key-path/wire_plus/healthy-final/trace/runtime_trace.jsonl)
and [extracted map history](hdfs11-key-path/wire_plus/key-state-evidence.json)
show this exact, **within-run** correspondence in the second MiniDFSCluster:

| Operation | Event sequence | Manager | `allKeys` map | Integer `keyId` | `BlockKey` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `addKeys` `Map.put`, site `#u23` | 7251–7254 | 643 | 648 | 562312551 | 634 written |
| First target `Map.get`, site `#u6` | 10038–10040 | 643 | 648 | 562312551 | 634 returned |
| Second target `Map.get`, site `#u6` | 10536–10538 | 643 | 648 | 562312551 | 634 returned |

The trace has no intervening `remove` or `clear` call on map 648. The
`Integer` wrapper objects differ, so object identity alone would miss the
matching key; the integer value is recovered from the adjacent `valueOf`
call. These IDs are run-local and are **not** stable fault selectors. The
actual target guard remains normal. Static/runtime planning admits the
DataNode `BPServiceActor`/`BPOfferService` import region by
`SHARED_LOCATION_DEMAND_V1` and the NameNode protobuf producer by
`WIRE_PRODUCER_V1`, both as `CANDIDATE`; there is no certified cross-process
wire read-from or local map-state edge.

The closure’s 51 markers partition into five IPC request/response
marker/site classes (45 observations), one client SASL request class (two),
and two server SASL read classes (four). The first six classes are represented
by the new trials; the server read classes were represented by the ten
earlier trials. The IPC trials select the second cluster’s DataNode actor
root and actual registration response/send sites. Exact full occurrence,
source, site, and hit ordinal matched for every step. For each ordered
mutation, its new marker was also present in the preceding faulted trace’s
target closure. `targetAfterFault` refers to a guard after the *last* fault.

| New sequence | JVM time | Matched/applied | Target after last fault | Original JUnit | HDFS-11 fatal |
| --- | ---: | ---: | --- | --- | --- |
| Registration response EOF | 12.507 s | 1/1 | Yes | Pass | No |
| Registration response timeout | 12.454 s | 1/1 | Yes | Pass | No |
| Registration request connect timeout | 12.449 s | 1/1 | Yes | Pass | No |
| Registration response I/O error | 12.909 s | 1/1 | Yes | Pass | No |
| Registration request I/O error | 16.077 s | 1/1 | Yes | Pass | No |
| First client SASL send I/O error | 15.006 s | 1/1 | Yes | Pass | No |
| Second client SASL send I/O error | 13.749 s | 1/1 | No; target lost | Fail after injected I/O error | No |
| Response EOF → retry timeout | 22.207 s | 2/2 | Yes | Pass | No |
| Response EOF → retry timeout → heartbeat response EOF | 32.046 s | 3/3 | Yes | Pass | No |

All nine final trial traces aggregate with the exact `REGION.53092d3e...`
target and zero `BLOCKING` gaps. The two-fault trial exposes 10 new
instrumented branch `(site,outcome)` pairs versus the final healthy seed,
including `BlockTokenSecretManager.updateKeys(long)#u5=true`, heartbeat
handling, and IPC retry outcomes. It adds zero methods. The three-fault
trial adds zero further method or branch outcomes; the target guard remains
normal. This is coverage feedback, not proof that a fault changed key
membership. The [atomic checkpoint](hdfs11-key-path/wire_plus/campaign-checkpoint.json)
records nine completed trials and supports resume without rerunning them;
the run used tmux session `hdfs11_key_final`. Measured active process time
for final SEED, weave, healthy run/aggregate, nine trial JVMs, and nine
trial aggregates is **264.624 s**. Combined with the earlier SASL campaign,
HDFS-11 used **543.904 s** of measured active process time, 19 trials, 30
applied fault events, 16 target-retaining trials, three lost-target trials,
and zero target fatal outcomes. The final nine-trial tmux phase took 132.911 s
wall time with two independent JVM trials in parallel.

### Exact state edge needed before revisiting HDFS-11

The smallest reusable repair is to reuse GraphChecker’s versioned
`StateDoors` (`GraphChecker-unit-hbase`, commit `a79170360`) instead of
assuming a causal edge from two region locations. Instrument the successful
`Map.put` in `BlockTokenSecretManager.addKeys` (Hadoop 3.4.3 source line 235;
Soot `#u23`) and the returned `Map.get` in
`retrieveDataEncryptionKey` (line 551; Soot `#u6`); the same adapter can
record `retrievePassword` for related HDFS checks. The adapter must keep a
side-table entry for each live `(cluster incarnation, DataNode epoch,
blockPoolId, manager/map instance, integer keyId)`. On successful put,
assign a unique state version and emit `STATE_WRITE`; keep the actual
`BlockKey` identity in the side table for checking. On get, read the returned
value **and the same
entry’s version** while still under the manager’s monitor and emit
`STATE_READ`. Repeated writes to the same key must get distinct versions;
absence without a certified writer/removal remains an explicit gap. Include
`removeExpiredKeys` iterator removal (line 216), `clearAllKeysForTesting`
(line 572), and any other remove/clear path so a stale put is never joined
across deletion. A get should link only to the unique last surviving write
of the same entry and value. The version must be created at mutation time;
a later separate lookup or `BlockKey` object identity alone cannot certify
the read. Runtime map/object IDs help validate one run, while a deterministic
cluster/manager generation gives replayable identity and separates the two
MiniDFSClusters that currently both appear as `hdfs/datanode/0#epoch0`.

`StateDoors` already emits versioned `STATE_WRITE`/`STATE_READ` rows and its
aggregator joins a unique earlier writer on `(sourceKey, stateKey, version)`;
it reports missing or ambiguous writers as gaps. That mechanism can be
reused once the HDFS adapter certifies the atomic version. The existing
block-key ID/expiry `WIRE_FLOW` mapping and IPC call ID are a separate
NameNode→DataNode candidate path; they still require exact request/response
and command identity to prove an end-to-end producer edge. No further
equivalent fault trials are scheduled until the map-state edge is available.

## Source-level interpretation

The NameNode makes and exports current/next block keys. Initial DataNode
registration calls `addKeys`, and later `DNA_ACCESSKEYUPDATE` commands call
it again. The HDFS-11 guard is fatal only when DataNode `allKeys` lacks the
exact client `keyId`. A SASL read EOF or timeout does not remove an imported
key, and the tested client paths retry the first failed connection. For an
actually missing key, the server sends an unknown-key SASL response;
`DFSInputStream` and `FileChecksumHelper` clear the cached encryption key
and retry once. An observed target exception would first be a candidate
requiring replay and source-level failure analysis. Here it never occurred.

Reproduce the earlier SASL-only healthy seed with:

```sh
python3 .study-repairs/unit-test-pivot/hdfs11-server-door/build.py
python3 .study-repairs/unit-test-pivot/hdfs11-sasl-identity/build.py \
  --woven .study-repairs/unit-test-pivot/hdfs11-server-door/instrumented \
  --overlay .study-repairs/unit-test-pivot/hdfs11-server-door/overlay
python3 .study-repairs/unit-test-pivot/hdfs11-param-smoke.py \
  --server-door --sasl-identity
```

For the final 27-class graph and unchanged original JUnit `[0]` child, run:

```sh
python3 .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/prepare_weave.py
python3 .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/build_sasl.py
python3 .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/build_wire.py
python3 .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/run_wire.py \
  --output .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/healthy-reproduction
python3 .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/evidence.py \
  --trace .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/healthy-reproduction/trace/runtime_trace.jsonl \
  --output .study-repairs/unit-test-pivot/hdfs11-key-path/wire_plus/healthy-reproduction/key-state-evidence.json
```

The recorded nine fault trials and exact plans are in
[trials-final](hdfs11-key-path/wire_plus/trials-final) and
[trial-plans](hdfs11-key-path/wire_plus/trial-plans). The resumable
[campaign.py](hdfs11-key-path/wire_plus/campaign.py) skips completed
checkpoint entries. For the earlier campaign, each exact JSON selector is in
[trial-plans](hdfs11-server-door/trial-plans);
for example, add `--fault-trial .study-repairs/unit-test-pivot/hdfs11-server-door/trial-plans/first-eof.json`
to the final command. Trial logs, manifests and traces are in
[trials](hdfs11-server-door/trials). The checklist record is
[result.json](cases/HDFS-11/result.json).
