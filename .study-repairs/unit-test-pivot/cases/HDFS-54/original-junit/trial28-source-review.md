# HDFS-54 original-JUnit trial 28: nine-DN all-I/O-fault observation

**Classification: reproduced expected all-DN fault-model failure.**
The selected check fired, but this trial does not establish the stale
encryption-key mechanism in known HDFS-17897 and is not a new bug claim.

## Exact workload and runtime receipt

- Released, unchanged Hadoop 3.4.3 JUnit:
  `TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]` in its original
  11-DataNode `MiniDFSCluster`. Test JAR SHA-256:
  `08cb98dc77193afb196cb8b1f74108080c59bbcb3ae6430aca51bbfd004e9acb`.
- node2 trial 28, plan `e080d9f78ce80f65`, raw directory:
  `/users/ZhenyuLi/hdfs54-original-campaign/runs/trial-0028-e080d9f78ce80f65-r0`.
  Measured JUnit run: 14.868 s, one test run, one failure, exit 1.
- Planned `IOException` at checksum RPC `CONNECT_L686` for roles 0, 1, 3,
  4, 5, 6, 7 and 8; at `RECV_L699` for role 2. All nine faults matched and
  applied in plan order. `runtime_trace.jsonl` shows nine distinct DN UUIDs,
  one file `/striped/stripedFileChecksum1`, block group 0, block ID
  `-9223372036854775792`. Each injection is followed by the production
  line-669 `IOException` catch. After role 8's catch at trace sequence 38,
  the exact target `FileChecksumHelper$StripedFileNonStripedChecksumComputer`
  `#checksumBlocks` line 629 records `completed=false` at sequence 39.
- The original JUnit log's failure names the same block ID and lists nine
  locations with indices 0 through 8. It reports `Fail to get block checksum`
  and `Original JUnit runs=1 failures=1 ignored=0`.

| Raw file | SHA-256 |
|---|---|
| `manifest.json` | `0ca18424e98c09ad7157d9c709c62b6beb426da052d38de6adcf73b2fe26e31b` |
| `runtime_trace.jsonl` | `f299b4431f5c4c56fc1f2965c374237d2d1a36a361d9d18d492bec2ae9cc9a1a` |
| `jacoco.exec` | `a68e68159b8fbae0cfc40f9d4078b97a6ba83d22af0d36b4c39bcefa7dad8826` |
| `junit.log` | `874acbb6da18d40110653d1c508702ef54843cbd64428ed5bebe3e0f77b65ad8` |

## Source explanation

In released `FileChecksumHelper.java` lines 651–672,
`checksumBlockGroup` reads all locations for a `LocatedStripedBlock` and
loops while `!done` over each DataNode. A successful `tryDatanode` sets
`done=true`; the generic `IOException` handler at line 669 leaves it false
and tries the next DataNode. The trace has one deliberately injected
`IOException` on **every one of the nine locations** and no successful
checksum RPC after the ninth fault. `checksumBlockGroup` therefore returns
false, and line 629 throws `PathIOException`. The original JUnit failure is
the expected response to making every eligible checksum source fail.

The HDFS-17897 mechanism is different: a client keeps a stale cached data
encryption key, DataNodes throw real `InvalidEncryptionKeyException`, and the
striped path fails to clear that cache and retry. This trial has only planned
generic `IOException` injections and no observed stale DataNode `allKeys`
lookup. The separate adapted control has the actual key-expiry and fixed
differential evidence. The clean replay below confirms this source-based
classification.

## Clean original-JUnit replay

The live fuzz controller was held **after** finishing trial 38's original
JUnit, JaCoCo and manifest; its JVM had exited. A separate output directory
`node2:/users/ZhenyuLi/hdfs54-replays/trial28-clean-01` then ran the
identical nine-entry `e080d9f78ce80f65.tsv` plan under a fresh, unchanged
11-DN `MiniDFSCluster`. The plan file SHA-256 is
`33756640f8dd1baf3cf0fc3f405229e9546e09f8c73b848a72dd4dfc19308484`.
No fault was injected by the fuzz controller during this replay.

The replay applied all nine faults in order, again on distinct fresh DN UUIDs
for roles 0 through 8, the same file, block group and block ID. After nine
line-669 catches, line 629 was false at trace sequence 39. The original
JUnit reported the same `Fail to get block checksum` failure (one run, one
failure, exit 1) in **15.160 s**. The raw replay manifest retains production
JaCoCo coverage: 29,440 probes, 8,266 methods and 9,307 branch-count tokens.

| Replay raw file | SHA-256 |
|---|---|
| `manifest.json` | `4fd3e6efe7248b69f3fe93037fec92b0563590fdd4c4dd0b5576dc331c082556` |
| `runtime_trace.jsonl` | `7470dd440d339b0fb8fae526b753a1a77d461197f69e1e00fdbc213237719aaa` |
| `jacoco.exec` | `6c14e6549baaa2871bf3334f0e266ed852e851d7f5a37d369a5fc583ff4b8a6d` |
| `junit.log` | `987e0f3448f5f0557fae6aac07793c1f4a3a623356426fd0b17ff864f1aa61b4` |

After replay, the pause marker was removed. The live campaign summarized its
own already completed trial 38 once and continued from trial 39. The replay
therefore does not enter the fuzz budget's attempt/effective counters.
