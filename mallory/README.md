# Mallory baseline: graph-change-guided fault injection on GraphChecker's graph

Mallory (Meng, Pîrlea, Roychoudhury, Sergey: *Greybox Fuzzing of Distributed Systems*, CCS 2023) fuzzes a
distributed system by injecting faults while it runs, observes each run as Lamport timelines (one per node,
joined by the messages between them), abstracts the events, and steers later faults by reinforcement learning:
a fault that makes the run show causal relations no earlier run showed is rewarded. This baseline keeps that
idea and takes the observation from GraphChecker: every run's graph is the one GraphChecker's own
instrumentation records, unchanged, and Mallory compares how that graph changes from run to run.

## How a campaign runs

```text
GraphChecker SEED + PLAN of the case        recording weave, static scope, declared target resolved
        |                                    (TARGET rows: the target's fatal arm at its occurrence)
        v
healthy native run  ---- graph G0, fault points (every fault marker it evaluated)
        |
        v   repeat, one run at a time
Q-policy picks a fault point (state = where it stands in the graph, action = which failure where)
        |
plant it (plus its parent run's faults) -> native run of the case's workload on the recording weave
        |
graph G -> new happens-before edges vs every earlier graph = reward; Q-update;
           a run with new edges joins the corpus, its later fault points become choices
        |
oracle: PLANT_FATAL at the declared target occurrence, every planted fault applied
```

- **The graph** (`mallory/graph.py`): a run's GraphChecker trace (`runtime_trace.jsonl`) names every event by
  the node that ran it (GraphChecker's source identity, e.g. `auto0/master0#epoch0`) and pairs what crosses
  nodes. Abstract events: method entries, branch outcomes, message sends and receipts, ZooKeeper store writes,
  reads and watch notifications, the injected faults and the target's fatal arm. Abstract happens-before edges:
  program order on each node's timeline, a send to its receipt (transport, correlation id, attempt, half), a
  store write to the reads and watch notifications of its version. A run's observation is its edge set.
- **Fault points** (`mallory/faults.py`): with `-Dcausynth.plant.observe=true` a planted run states every fault
  marker GraphChecker wove at a door (`PLANT_MARKER`: transport fault kind, call site, enclosing occurrences).
  A fault point is one marker evaluation: its site, innermost occurrence and invocation, exactly what a
  GraphChecker plant's `FAULT` row names, so a point any earlier run reached can be planted in the next.
- **The policy** (`mallory/policy.py`): Q-learning as in Mallory. A state is where the fault point stands in
  GraphChecker's graph (node, region, the message exchange or root it serves, its call path) with its node's
  last two abstract events; an action is which failure at which code site. Untried actions are optimistic;
  epsilon-greedy (0.1) keeps random choices; the reward saturates with the run's new edges
  (`1 - exp(-new/10)`); the update looks one fault point ahead in the run the fault produced.
- **The campaign** (`mallory/campaign.py`): one trial at a time on one node; a plan extends a corpus run with
  one more fault after its last (at most three); a trial is bounded by four times the healthy run (at least
  120 s). The state is checkpointed after every trial (`state.json`); the result is `result.json`.

Different cases run side by side on different nodes; a case's own trials never run in parallel.

## GraphChecker and the systems

| system | GraphChecker branch (`git@github.com:JHSUYU/GraphChecker.git`) | system tree (fork branch `baseline/mallory`) |
| --- | --- | --- |
| HDFS | `baseline/mallory-hdfs` (= `system/hdfs-cloudlab` + native plant runs) | `JHSUYU/hadoop` 899c200cc8 (`graphchecker/hdfs-checks`, tree `hadoop-hdfs-study-r7`) |
| HBase | `baseline/mallory-hbase` (= `system/hbase-cloudlab` + native plant runs) | `JHSUYU/hbase` b5d5cc6a20 (`graphchecker/hbase-checks`, tree `hbase-checks`) |
| Solr | `baseline/mallory-solr` (= `system/solr-cloudlab` + native plant runs) | `JHSUYU/solr` 12d23091d1 (`graphchecker/solr-checks`, tree `lucene-solr-checks`) |

Mallory needs no change in a system tree: the system's adaptation (its door hooks, the cluster's node
identities, the bug workloads) is GraphChecker's, in the fork's `graphchecker/*-checks` branch; `baseline/mallory`
pins the commit Mallory ran on. The GraphChecker branches add one commit, *Native plant runs for the Mallory
baseline*: the `PLANT_MARKER` observation in `RecordingPlant`, `explore.TargetRows` (a plant's TARGET rows for the
declared target, as `ConfirmMain` writes them), `run_engine.sh plant-run <run dir> <plant> [bound]` and
`campaign_stop_after=PLAN`.

## Running it (CloudLab, node0-node4)

Set up the cluster, GraphChecker checkouts, VM image and system trees as GraphChecker's REPRODUCE.md says for
`system/{hdfs,hbase,solr}-cloudlab`, but check out `baseline/mallory-<system>` at `/bulk/wt/gc-mallory-<system>`
(`mvn -q package -DskipTests`); trees under `GC_TREES=/bulk/wt`. Paths are in `mallory/settings.py`
(`MALLORY_GC_<SYSTEM>`, `MALLORY_WORK`, `MALLORY_NODES`).

```sh
cd mallory
python3 -m mallory prepare hbase-bugs-backup-lock-reply-lost --node node0     # SEED + PLAN, TARGET rows
python3 -m mallory run hbase-bugs-backup-lock-reply-lost --node node0         # the campaign
python3 -m mallory report                                                     # every case's result
python3 -m unittest discover -s tests -t .
```

`run` prepares the case itself when it has no `prepared.json`. Budget flags: `--trials` (600), `--seconds`
(14400), `--max-faults` (3), `--trial-bound` (900, lowered to four times the healthy run),
`--continue-after-detection`. Output: `$MALLORY_WORK/<case>/{gc,runs,state.json,result.json}`; every run keeps
its plant, its log and its gzipped trace.

## Results (2026-10-25, CloudLab)

The three targets are bugs a single injected fault exposes (GraphChecker's claims for them move one fault root):
HDFS-17967 (PR apache/hadoop#8698) on its `replaceBlock` proxy path, Solr's RESTORE retry that leaves a shard in
CONSTRUCTION, and HBase's lost backup-lock reply. Each case ran alone on one node, one trial at a time.

| case | bug | node | detected | trials | time to detect | the detecting run's fault |
| --- | --- | --- | --- | ---: | ---: | --- |
| hdfs-17967-pathB | HDFS-17967, `DataXceiver.replaceBlock` proxy | node2 | yes | 1 | 9 s (+11 s healthy run) | `FAULT:HADOOP_IPC:REQUEST` on the DataNode's `sendHeartbeat` |

The HDFS workload's first fault marker is the heartbeat whose loss keeps the new block key from the DataNode, so
the optimistic first choice found it; its run added 7 edges to the healthy graph and lost 61.
