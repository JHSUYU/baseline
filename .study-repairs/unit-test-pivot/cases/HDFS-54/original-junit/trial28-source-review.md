# HDFS-54 original-JUnit trial 28: nine-DN all-I/O-fault observation

**Classification: expected all-DN fault-model failure; clean replay pending.**
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
differential evidence. Until a clean identical-plan replay finishes, this
trial stays an observation with source-based expected classification.

## Replay plan

After the live HDFS-54 campaign releases its node2 JVM slot, rerun this
exact nine-entry TSV plan under a fresh original `MiniDFSCluster`, with a
separate output directory and unchanged test JAR. Verify 9/9 ordered matches,
the same nine distinct DN roles for one block group, exact postfault
line-629 false, and the same `PathIOException`. Preserve the raw replay
manifest, trace, JUnit log, JaCoCo and elapsed time. A mismatch changes the
classification to nondeterministic pending further review; it cannot be
silently counted as reproduction.
