# HBase 3.0.0, twenty-check pilot

This adapter tests HBase `rel/3.0.0` (commit
`da418afa6973bf4222231c1d233410d8c18ac7ec`) on two Masters, three
RegionServers, one Hadoop 3.4.3 NameNode/DataNode pair, and ZooKeeper. Every
node is a separate Docker container, so a selected JVM can be stopped without
stopping the others. The HBase and Hadoop release archives were checked
against their Apache SHA-512 files; exact digests are in `VERSION.json`.
HBase 3.0.0 requires JDK 17, so this adapter uses `eclipse-temurin:17-jdk`.

The earlier Soot scan of HBase 2.6.6 reported 225 `YES` checks. Running the
same classifier on HBase 3.0.0's five production JARs reports 203 `YES` checks
among 6,164 scanned sites. Exact class, method signature, site kind, exception
type, and within-method order map 168 explicit throw/assert sites across the
versions. The broad fault-free workload enters 37 of the mapped throw sites'
enclosing methods on server JVMs before the workload ends. A deterministic
selection keeps 20 unique sites, favoring component code and limiting how many
sites come from one class. Selection does not change the classifier verdicts.
The selected site IDs, method descriptors, writer evidence, and observation
nodes are frozen in `selected20.json`; the selection script also writes its
working output under `out_selection/`.

The workload creates a table, writes and reads a row, scans, flushes, takes
and clones a snapshot, drops the copy, disables the original, truncates it,
and checks its existence. A completed fault-free cluster run has been verified
on 3.0.0. For each selected check, `run_batch.py` creates a separate oracle:
entry into the candidate's method anchors the healthy causal graph, while an
actual throw at the candidate's source line reports a fatal target. The entry
anchor is deliberately coarser than the exact branch guard; method entry alone
does not prove that the candidate's guard was evaluated. Candidate and witness
writer method entries provide replayable fault points. Each target's seed must
complete the workload and checker before its fault trials are accepted.

To reproduce, unpack the official HBase 3.0.0 binary under
`~/.baseline-deps/hbase-3.0.0`, unpack Hadoop 3.4.3 under
`~/.baseline-deps/hadoop-3.4.3`, and build the Java agent in
`baseline/crashfuzz/agent` with `mvn -DskipTests package`. From
`baseline/crashfuzz`, run:

```sh
python3 examples/hbase_300/select_candidates.py
python3 examples/hbase_300/discover.py
python3 examples/hbase_300/select_candidates.py \
  --trace-dir examples/hbase_300/out_discovery/runs/discovery-00001/traces
python3 examples/hbase_300/run_batch.py --runs-per-target 2
```

The Soot scan input is `out_scan/hbase-3.0.0.decisions.jsonl`. The batch runner
resumes completed targets and writes per-target traces/results under
`out_batch/candidate-NNN`, with a rolling `out_batch/progress.json`. A run is
reported as *injected* only when the controller matched the planned fault
point. Raw fatal throws are saved with their replay outcomes; the batch report
counts reproduced witnesses separately. Both unreached targets and untriggered
fault sequences remain explicit in the results.

For a completed target whose fault point did not recur exactly, rerun with
`run_batch.py --retry-unmatched --runs-per-target 3`. The retry stops after its
first matched fault trial. The controller first matches the full causal
context and otherwise can match the same node, site, phase, and local ordinal
at its corresponding per-site occurrence count. Each injection records
`match_mode` as `exact` or `site_occurrence`, and earlier attempts are archived
under `candidate-NNN-previous-K` and retained in `progress.json`. The fallback
preserves the intended program site but may choose a different logical RPC
request when concurrent request order changes.
If a retry is interrupted, rerunning the same command archives its partial
directory and keeps the last completed attempt available for reporting. The
runner checks Docker daemon access before it archives any result.

An explicit throw observed in the fault-free seed is an unsuitable oracle for
this workload, even if the workload itself succeeds: the surrounding code may
catch and recover from that exception. The report labels such a site
`baseline_fatal`; replayed throws from these sites are counted only as raw
exceptions. New campaigns reject a seed that already throws at the target.

The RPC adapter correlates HBase Netty requests using socket endpoint and
call ID, and the generic graph tracks cross-thread task handoffs. Procedure
state replayed from HDFS after a Master restart is not yet linked as an exact
durable-state edge. The graph and fuzzing feedback remain may-influence
approximations where exact read-from information is unavailable.
