# HDFS-14/31/32 node2 healthy admission audit

Scope: the staged healthy-only packages on Hadoop 3.4.3 source digest
`825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.
The HDFS-14 package manifest is SHA-256
`d909c36b95fce8174b40a31562238f039ea20803750c42a9bf3adec05279dba8`;
the HDFS-31/32 manifest is
`1c9918ec91cb706071baf990b5a3b1c4acf4b433c000a5e925ab28dd692f4c8e`.
The source and compiled artifacts, configurations, catalogs, releases, and
source lines were checked by each package's pinned preflight. No JVM ran in
this audit.

## Normal node2 preflights

On node2, each normal (without `--static`) `python3 -B preflight.py` command
returned `preflight_pass`, `jvm_started: false`, and `healthy_admitted: false`.
The commands also checked that their fresh `/tmp` outputs do not exist and
that free disk exceeds the configured reserve.

| Case | Command suffix | Pinned config SHA-256 | Selected JUnit count |
| --- | --- | --- | --- |
| HDFS-14 | `hdfs14-node2-healthy-stage-v1/preflight.py` | `f521a5e3fefa44be6920c2864b5d5e89c65513fd00cd9e8adcfd43dc3d008c30` | 2 parameter instances |
| HDFS-31 | `hdfs31-32-node2-healthy-stage-v1/preflight.py --case HDFS-31` | `04544f739cda7fe97974bbeccf2df578b42870c3649b5d153aa3305da5a2bd71` | 1 |
| HDFS-32 | `hdfs31-32-node2-healthy-stage-v1/preflight.py --case HDFS-32` | `de2e10671adbb42ab24e94f8571625f83ff0722694751804f5bc662e9ecc26cf` | 1 |

## Target and door review

| Case | Exact selected check and physical actor to establish | Typed I/O candidate | Remaining causal and identity gap |
| --- | --- | --- | --- |
| HDFS-31 | `DataNode.getBPOSForBlock(ExtendedBlock)` null branch at `DataNode.java:1833`, followed by the selected `IOException` at 1835. `TestDiskError.java:241-283` calls `dn0.transferBlock(existingBlock, ...)`, which calls this guard directly at `DataNode.java:2834`. | `BPServiceActor.sendHeartBeat` RPC at 563 may throw `IOException` on a DataNode actor and is caught/retried in `offerService` at 786-788. The test's `RandomAccessFile.writeByte`/`writeInt` at 259-260 are also typed `IOException` calls. | The heartbeat must be matched to the same physical `dn0`, block pool, and epoch before the transfer. The test's metadata writes run on the test thread and an uncaught failure there skips `transferBlock`. No reviewed heartbeat fault removes `dn0`'s block-pool map entry or changes the `ExtendedBlock` pool ID; `BlockPoolManager.remove` at 89-95 is the relevant removal. The test's `DataNode.equals(UUID string)` destination loop at 268 needs runtime actor confirmation. |
| HDFS-32 | `DataNode.deleteBlockPool(String,boolean)` running-pool branch at `DataNode.java:3819`, selected `IOException` at 3822. `TestDeleteBlockPool.java:142-187` sends two `DFSAdmin` requests for `bpid2` to the original federated `dn1` (`cluster.getDataNodes().get(0)`): `force=false`, then `force=true`. | Same DataNode heartbeat RPC at 563; `DFSAdmin.deleteBlockPool` client RPC at `DFSAdmin.java:2702` is typed `IOException`. | Healthy observation must bind each guard occurrence to `dn1`, `bpid2`, the request force flag, and epoch. The first client RPC may return failure without reaching the DataNode guard; the second must succeed. `refreshNamenodes` stops and joins the removed nameservice before the requests (`BlockPoolManager.java:194-251`), and no reviewed heartbeat or client RPC fault is shown to retain its block-pool map entry. The expected no-force storage failure is distinct from the selected running-pool exception. |
| HDFS-14 | Six-argument `BlockTokenSecretManager.checkAccess(Token,...,StorageType[],String[])` password comparison at 411 and selected `InvalidToken` throw at 412. `DataXceiver.readBlock` calls that overload through `DataXceiver.checkAccess` at 592 and 1452 on a DataNode worker. `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite*` has two parameter instances. | Same heartbeat RPC at 563; the adapter's `hdfs:sasl-first-response-read` is an `IOException` door after the client writes its first SASL protobuf (`HdfsHooks.java:906-912`). | The healthy trace must identify the concrete DataNode, epoch, read operation, six-argument overload, and a pretarget door on a causally linked occurrence. The SASL read is on the client while the selected guard is later on the DataNode worker; a client read failure can end the connection before `readBlock`. A heartbeat error is on a separate actor. No reviewed I/O exception is shown to leave both `retrievePassword(id)` and `token.getPassword()` available but unequal. A missing key throws earlier at `BlockTokenSecretManager.java:501-516`. |

All three catalogs have empty `nodeBindings`, and the healthy gates set
`minimum_healthy_observed_path_doors` to zero. A passing static preflight or
even a passing JUnit therefore does not by itself prove a named physical
actor, pretarget injectable door, or fault-to-target path. The older HDFS-31/32
calibrations stopped at an obsolete-agent startup `LinkageError`; they do not
prove target reach. The HDFS-14 exact method selector previously collected
zero tests, so the staged parameter wildcard and expected JUnit 2/0/0 are
material.

## Dispatch decision

After HDFS-29 and HDFS-30 release the shared node2 HDFS source/build lane,
queue **HDFS-31, then HDFS-32, then HDFS-14**, one healthy run at a time.
HDFS-31 has the shortest direct test-to-check call, HDFS-32 needs two RPC
phase identities, and HDFS-14 runs two encrypted-transfer parameter instances.
This order is for named healthy observation only; all fault and full-campaign
admission remains closed.

For each result, require the configured Surefire count with zero failures,
errors, and skips; loaded target class and catalog SHA attestation; the exact
nonthrowing branch on a named DataNode and epoch; and at least one observed,
injectable typed pretarget door linked to that same physical request or a
source-backed state path. HDFS-32 additionally needs `bpid2` and `force`
phase disambiguation. If the door is merely contemporaneous on another
actor, classify it as an observation, not as a target-retaining fault site.
Before any fault pilot, provide a concrete mechanism by which that door's
`IOException` can change the selected predicate while the same check still
runs. None of these three packages currently supplies that mechanism.
