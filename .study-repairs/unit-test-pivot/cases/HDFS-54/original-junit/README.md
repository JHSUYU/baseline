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
The first checkpoint reported 1 effective trial and 31 queued mutations.
After its node1 handoff, a second strict trial finished in 21.065 seconds:
two ordered `CONNECT_L686` `IOException` faults matched and applied on
distinct DataNode roles 0 and 1 for the same block group. The production
catch at line 669 followed each injection. Role 2 served the request, and
the same file's line-629 target evaluated `completed=true` after the second
fault. The unchanged JUnit passed. It covered 28,883 probes, with 156 probe
tokens new to the prior global coverage set. The healthy and two fault runs
together cover 28,885 distinct production probes, 162 more than the healthy
seed. The node1 checkpoint now reports **2/80 effective**, 2 attempts, 46
queued plans, and no in-flight plan. See
[`node1-trial2-receipt.json`](node1-trial2-receipt.json). Full budget execution
remains pending a safe node slot. The node2 copy remains paused at 1/80.

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

After the node2 owner explicitly releases its JVM slot, reconcile the node1
2/80 checkpoint and trial-2 evidence onto node2, verify both trial IDs and
the 46-plan queue, and then clear the node2 pause marker. Only then use
`bash /users/ZhenyuLi/hdfs54-original-campaign/resume_node2.sh`. The
launcher refuses an active Solr 36/37 session or another JVM and starts
`hdfs54_original_80` in tmux at lower CPU priority. The campaign must read
the reconciled 2/80 checkpoint and avoid repeating either completed plan.
The direct command, for inspection, is:

```bash
cd /users/ZhenyuLi/hdfs54-original-campaign
python3 campaign.py --runs /users/ZhenyuLi/hdfs54-original-campaign/runs \
  --effective-budget 80 --max-faults 8 --attempt-cap 320
```

### Optional node1 one-trial handoff

An offline copy of the same 20 MB campaign is staged at
`/users/ZhenyuLi/hdfs54-original-campaign` on node1. Both copies had
`campaign-state.json` SHA-256
`8728827521d8d650325f9801add8d15ba32dd38e3b458860f0ce1029ed256cf8`
when copied: effective 1, attempts 1, queue 31, `in_flight=null`. The
unchanged Hadoop test JAR also has the same SHA-256 on both hosts. Scratch,
ports, and run directories are local to each host; node1 had 32 GiB disk
and 55 GiB available RAM at staging time.

The node1 path was reserved for **one next queued trial** after SOLR-13
released its node1 slot and HDFS storage actor-V2 paused calibration. Running
`reserve_node1_pilot.py` from node0 verified both checkpoint copies and
absence of either HDFS-54 tmux, created a node2
`runs/.node1-pilot-active` marker to block `resume_node2.sh`, then writes the
node1 `runs/.node1-pilot-lease.json`. Any partial reservation fails closed;
inspect both marker files before retrying.
`resume_node1_pilot.sh` refused to run without that lease, validated the
unchanged 1/80 checkpoint and resource headroom, checked that SOLR-13 and
actor-V2 tmux sessions had exited, and started tmux
`hdfs54_original_node1_pilot` with `campaign.py --once 1`. It consumed the
next queued plan as trial 2; completed trial 1 was not rerun. The pilot ran
04:11:58–04:12:43 UTC. Its own measured JUnit duration was 21.065 seconds.
HBase-17's overlapping original JUnit r055 passed in 55.65 seconds with
postfault target, within its prior 49–57 second band. Node1 HDFS-54 tmux/JVM
exited, and the node1 slot returned to actor-V2 calibration. Node2's original
checkpoint remains unchanged behind `runs/.node1-pilot-active`. Reconcile
trial 2 and its updated checkpoint before clearing that marker. Never resume
both copies at once.

## Interpretation limit

The original JUnit enables block access tokens but does not set up an expired
data encryption key. A synthetic `InvalidEncryptionKeyException` at a checksum
RPC explores the line-669/629 response path; it does not demonstrate an actual
stale DataNode `allKeys` state. That state and the known HDFS-17897 differential
are evidenced by the separate adapted control. A target `completed=false`
after fault is a candidate observation until its source and replay are
reviewed; it is not automatically a new bug.
