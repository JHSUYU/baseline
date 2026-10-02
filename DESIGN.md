# Target-guided fault injection for ad hoc coordination checks

This repository contains an independent baseline in [`crashfuzz/`](crashfuzz/).
GraphChecker motivated the target-directed, iteratively expanded causal graph,
and CrashFuzz motivated the fault-sequence search. Neither tool is a runtime
dependency or a source of required graph artifacts. The graph construction and
search rules contain no protocol-specific vocabulary.

## Inputs and result

An experiment supplies a bytecode build, one check site, a workload that reaches
that check in a fault-free run, a cluster lifecycle adapter, node-failure limits,
and a trial budget. Each node is an independently killable JVM process. The
concrete oracle is observation of the selected check's fatal outcome; graph
growth is search feedback, not a correctness claim. Replays and the workload
checker determine whether a candidate is stable and meaningful.

## Execution loop

1. Reset the real cluster, run the workload without faults, and collect JVM
   boundary events. Every subsequent trial begins from the same initial state.
2. Build a typed occurrence graph. Method calls, correlated asynchronous
   handoffs, correlated messages, and field accesses connect local executions.
   An unversioned field write preceding a read is only a candidate dependency;
   an adapter may provide versions to establish an exact read-from edge.
3. Start at occurrences of the selected check and traverse incoming causal
   edges. Normalize closure nodes, edges, and branch outcomes into feedback
   features that ignore process UUIDs and timestamps but preserve node roles
   and restart phases.
4. Add one legal crash or reboot after the last injected fault in a sequence.
   Rank points in or near the target closure, while reserving an exploration
   share for unseen points. Retain a bounded number of crash seeds without
   immediate graph gain because their later reboots may expose recovery paths.
5. Replay a fatal-check sequence from clean state and save the exact point
   journal, trace, planned and injected faults, closure, checker result, and
   replay outcomes. A point that does not recur makes the trial untriggered.

The fault controller acts only at configured boundaries, including I/O and
coordination-state calls and selected method entries. It does not claim to
control all scheduling or message order. An occurrence becomes an injection
point only when the probe explicitly records a fault-point event.

## Instrumentation and adapters

The Java 8 agent in `crashfuzz/agent` records selected application method
entries/exits, field accesses, branches, target outcomes, I/O points, and
common thread-pool handoffs. It emits per-process JSONL traces and fsyncs a
fault point before the controller can kill its JVM. Transport adapters publish
matching message correlations at real send and receive boundaries; a reused
bare RPC call ID is insufficient. Ambiguous or missing correlations remain
explicit graph gaps. A system adapter supplies cluster setup, workload,
checker, and any transport hooks needed for that system; the graph algorithm
does not change for HDFS, HBase, Solr, or ZooKeeper.

The first backend uses Docker CLI to run a genuine multi-container cluster on
one host. Containers and their volumes survive stop/start within a trial; the
setup command restores clean state between trials. No Compose plugin is
required. This workspace reaches the daemon through `sudo -n docker`; the
cluster path has passed a two-container Java 8 fixture, a real HBase 2.4.8
seed-plus-crash run, and a HBase 3.0.0 fault-free workload. Unit tests exercise
the Java agent and a simulated two-node campaign.

## Version and validation choices

The first cluster adapter uses HBase `rel/2.4.8` at commit `f844d09157`,
with Hadoop 2.10.0 and Java 8. The current twenty-check pilot uses the latest
published HBase release, `rel/3.0.0` at commit `da418afa69`, with Hadoop
3.4.3 and Java 17. Its 225 older HBase 2.6.6 `YES` candidates were rescanned
on 3.0.0 bytecode: 203 current `YES` checks, 168 unambiguously mapped explicit
throw/assert sites, 37 mapped throws with observed server method entries, and
20 frozen targets. Site IDs, source revisions, archive hashes, and workload
coverage are recorded in `crashfuzz/examples/hbase_300/`.

The current implementation and its verification commands are documented in
[`crashfuzz/README.md`](crashfuzz/README.md). The HBase 2.4.8 seed reached the
healthy `checkTableModifiable` guard; its target closure included a client-to-
server RPC and two asynchronous handoffs. An injected crash of the active
Master forced the backup Master to finish truncate without taking the fatal
check. A recovery path that reloads a procedure from HDFS currently lacks a
cross-process durable-state edge. A selected explicit throw is only a target
witness: an exception that is caught and retried by the caller is not thereby
a reliability bug. The batch report keeps target reachability, matched
injection, workload success, and replay status separate.
