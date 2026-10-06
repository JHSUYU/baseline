# HDFS-11 — missing DataNode encryption block key

## Result and exact site

**Quality complete for the bounded original-test campaign; no new bug found.**
The check is `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])` in
Hadoop 3.4.3. `allKeys.get(keyId)` is at source line 551, `key == null` is
line 552, and `InvalidEncryptionKeyException` starts at line 553. The old
selection line 555 is the continuation of its message. Released bytecode
maps `ifnonnull` offset 25 to line 552, exception allocation offset 28 to
line 553, and message continuation offset 57 to line 555. GraphChecker
resolves `TARGET_SITE #u20`, guard `#u8`, fatal outcome `false`, in region
`REGION.c0d9d80b-cf85-36a4-87a7-f409be7dd190`.

The workload is the **unmodified original** JUnit4 child
`org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
It builds its own one NameNode, one DataNode `MiniDFSCluster`, writes and
reads a file, restarts with encrypted transfer, then reads and computes the
checksum. Parameter `[0]` enables the encrypted SASL path; `[1]` uses a
trusted-channel resolver and does not exercise this check. The generic
[parameterized runner patch](graphchecker-junit-parameterized.patch) selects
`[0]` while retaining JUnit setup, teardown, rules, and assertions.

## Static graph, runtime identity, and actual I/O doors

The static SEED used 22 extracted Hadoop application classes, 485 Hadoop
classpath jars, and released 3.4.3 binary. The healthy recording reaches
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

The stock client-side `HDFS_SASL:REQUEST` door is outside this target
closure. The isolated [server-door builder](hdfs11-server-door/build.py)
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

The target-specific feedback queue is exhausted under this original
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

Reproduce the healthy seed with:

```sh
python3 .study-repairs/unit-test-pivot/hdfs11-server-door/build.py
python3 .study-repairs/unit-test-pivot/hdfs11-sasl-identity/build.py \
  --woven .study-repairs/unit-test-pivot/hdfs11-server-door/instrumented \
  --overlay .study-repairs/unit-test-pivot/hdfs11-server-door/overlay
python3 .study-repairs/unit-test-pivot/hdfs11-param-smoke.py \
  --server-door --sasl-identity
```

Each exact JSON selector is in [trial-plans](hdfs11-server-door/trial-plans);
for example, add `--fault-trial .study-repairs/unit-test-pivot/hdfs11-server-door/trial-plans/first-eof.json`
to the final command. Trial logs, manifests and traces are in
[trials](hdfs11-server-door/trials). The terminal checklist record is
[result.json](cases/HDFS-11/result.json).
