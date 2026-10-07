# HDFS-54 unchanged-JUnit supplement

This is a separate, graph-free experiment. It does not replace the existing
adapted HDFS-17897 known-bug control in `../result.json`.

## Source and workload identity

- Hadoop tag: `rel/release-3.4.3` (`9d50c688` locally).
- Unchanged JUnit: `org.apache.hadoop.hdfs.TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]` from the released `hadoop-hdfs-3.4.3-tests.jar` (SHA-256 `08cb98dc77193afb196cb8b1f74108080c59bbcb3ae6430aca51bbfd004e9acb`).
- The original `@Before` builds a `MiniDFSCluster` with `dataBlocks + parityBlocks + 2` = 11 DataNodes, enables an erasure coding policy, and creates `/striped/stripedFileChecksum1`. The unchanged test obtains its checksum with `getFileChecksum`.
- Target: `FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks()` at source line 629. The bytecode overlay reports the boolean outcome of `checksumBlockGroup` at that exact conditional. A target record is valid only for the original file and after the final applied fault.

Only released production class bytecode is overlaid. The overlay records four
native application-level checksum RPC points (`connectToDN`, send
`BLOCK_GROUP_CHECKSUM`, read response, check response status), a generic
`IOException` catch at line 669, and the line-629 target. Each fault plan uses
`file, blockGroup, DataNode role, I/O site, occurrence, exception type`.
Runtime trace also records the actual DataNode UUID and block ID, but the plan
uses stable roles so it can match a fresh MiniDFSCluster. Four injected
exceptions are available: `IOException`, `EOFException`,
`SocketTimeoutException`, and `InvalidEncryptionKeyException`.

The first node2 healthy pilot passed the exact unchanged JUnit once in 17.72
seconds. It observed all four checksum RPC points, one line-629 target check
with `completed=true`, and 28,723 production JaCoCo probes. Its raw evidence
is at `/users/ZhenyuLi/hdfs54-original-campaign/runs/healthy-01` on node2.
The first strict fault pilot passed the same original JUnit in 17.57 seconds:
the one planned `IOException` at `CONNECT_L686`, DN role 0, was matched and
applied once. The trace then shows the line-669 `IOException` catch, checksum
RPC on DN role 1, and the same file's line-629 target check with
`completed=true` after the fault. It covered 28,727 production probes, four
more than the healthy seed. The raw directory is
`/users/ZhenyuLi/hdfs54-original-campaign/runs/trial-0001-01f09073125e7810-r0`.
The checkpoint reports 1 effective trial and 31 queued mutations. Full
budget execution remains pending the shared node2 JVM slot.

## Campaign

`campaign.py` seeds one fault at each observed I/O point and then adds one
ordered fault at an observed point after the prior fault. It keeps only plans
whose fault order actually matched and whose target was reached after the
last fault as effective. The queue scores new I/O roles/sites, production
JaCoCo probe/method/branch-count gain, execution time, fault count, and wait
time. Every run gets a fresh JUnit MiniDFSCluster. `campaign-state.json` is
written atomically, `trial-ledger.csv` records time and outcome, and individual
trial directories retain trace, log, JaCoCo execution data, coverage tokens,
plan, and manifest. The campaign can resume without repeating completed
plans. Initial budget: 80 effective trials and at most 8 faults per plan;
conditional extension: 128 effective and at most 10 faults. An attempt cap
keeps repeated nondeterministic misses bounded.

Example, after reserving the node's JVM slot:

```bash
cd /users/ZhenyuLi/hdfs54-original-campaign
python3 campaign.py --runs /users/ZhenyuLi/hdfs54-original-campaign/runs \
  --effective-budget 80 --max-faults 8 --attempt-cap 320
```

## Interpretation limit

The original JUnit enables block access tokens but does not set up an expired
data encryption key. A synthetic `InvalidEncryptionKeyException` at a checksum
RPC explores the line-669/629 response path; it does not demonstrate an actual
stale DataNode `allKeys` state. That state and the known HDFS-17897 differential
are evidenced by the separate adapted control. A target `completed=false`
after fault is a candidate observation until its source and replay are
reviewed; it is not automatically a new bug.
