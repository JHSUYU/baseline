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
healthy native runs ---- graph G0, fault points (every door evaluation, in and out of the window)
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
- **Fault points** (`mallory/faults.py`): every door of the system's transports in GraphChecker's library
  catalog is woven (`settings.System.doors`, added to the case's scope through `CAUSYNTH_EXTRA_SCOPE`), and
  a planted run states every evaluation of one, over the whole workload. Inside GraphChecker's recording
  window (`PLANT_MARKER`: transport fault kind, call site, enclosing occurrences) a fault point is the site,
  innermost occurrence and invocation, exactly what a GraphChecker plant's `FAULT` row names. Outside it,
  where GraphChecker names no occurrence (cluster start-up, set-up, shutdown), it is the site, its place
  (before or after the window, the node, the thread) and the invocation per place (`OUTSIDE_MARKER`,
  planted through `causynth.plant.outside`). Either way a point an earlier run reached can be planted in
  the next; every row carries the JVM's `nanoTime`, which orders the two.
- **The policy** (`mallory/policy.py`): Q-learning as in Mallory. A state is where the fault point stands in
  GraphChecker's graph (node, region, the message exchange or root it serves, its call path) with its node's
  last two abstract events; an action is which failure at which code site. Untried actions are optimistic;
  ties are drawn at random from the campaign's seed (never the order a run evaluated its points);
  epsilon-greedy (0.1) keeps random choices; the reward saturates with the run's new edges beyond the
  workload's own noise (`1 - exp(-max(0, new - noise)/10)`, where `noise` is the edges a second fault-free run
  adds to the first); the update looks one fault point ahead in the run the fault produced.
- **The campaign** (`mallory/campaign.py`): one trial at a time on one node; a plan extends a corpus run with
  one more fault after its last (at most three); a run joins the corpus only when it adds more edges than
  the noise; a trial is bounded by four times the healthy run (at least
  120 s). The state is checkpointed after every trial (`<case>/seed-<n>/state.json`); the result
  (`result.json`) states the time to detect three ways: the trials alone, with the two healthy runs, and
  with GraphChecker's SEED and PLAN of the case.

Different cases run side by side on different nodes; a case's own trials never run in parallel, and its
seeds run one after another.

## What Mallory takes from GraphChecker, and what it does not

- **The workload and the oracle, as GraphChecker gets them.** A case's workload is its GraphChecker test
  (`TestCausynth*`), which drives the bug's set-up and leaves the fault to be found; the oracle is the
  case's declared target taking its fatal arm at the declared occurrence, which GraphChecker's native run
  reports (`PLANT_FATAL`, the JVM halts there). Both tools get these same inputs.
- **The graph.** GraphChecker records what its SEED selected: the full recorder is woven into the region
  skeleton methods of the target's backward Soot slice, transport and store events at every woven door
  and store hook, all inside the recording window. Mallory's feedback is therefore computed over the
  target's slice: this is the point of migrating GraphChecker's graph, and it is stated here because it
  steers the search toward the target.
- **Not the fault space.** GraphChecker explores only roots inside its window and its case scope. Mallory
  injects at every door of the system's catalog over the whole run, start-up and shutdown included, with
  no knowledge of which doors GraphChecker's analysis demands.

## GraphChecker and the systems

| system | GraphChecker branch (`git@github.com:JHSUYU/GraphChecker.git`) | system tree (fork branch `baseline/mallory`) |
| --- | --- | --- |
| HDFS | `baseline/mallory-hdfs` (= `system/hdfs-cloudlab` + native plant runs) | `JHSUYU/hadoop` 899c200cc8 (`graphchecker/hdfs-checks`, tree `hadoop-hdfs-study-r7`) |
| HBase | `baseline/mallory-hbase` (= `system/hbase-cloudlab` + native plant runs) | `JHSUYU/hbase` b5d5cc6a20 (`graphchecker/hbase-checks`, tree `hbase-checks`) |
| Solr | `baseline/mallory-solr` (= `system/solr-cloudlab` + native plant runs) | `JHSUYU/solr` 12d23091d1 (`graphchecker/solr-checks`, tree `lucene-solr-checks`) |

Mallory needs no change in a system tree: the system's adaptation (its door hooks, the cluster's node
identities, the bug workloads) is GraphChecker's, in the fork's `graphchecker/*-checks` branch; `baseline/mallory`
pins the commit Mallory ran on. The GraphChecker branches add two commits. *Native plant runs for the Mallory
baseline*: the `PLANT_MARKER` observation in `RecordingPlant`, `explore.TargetRows` (a plant's TARGET rows for the
declared target, as `ConfirmMain` writes them), `run_engine.sh plant-run <run dir> <plant> [bound]` and
`campaign_stop_after=PLAN`. *Fail and observe doors outside the recording window*: `RecordingPlant`'s outside
evaluations (`causynth.plant.outside`, `causynth.plant.outside.log`), `nanoTime` on marker rows and
`CAUSYNTH_EXTRA_SCOPE` in `experiments/lib/case-env.sh`.

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
`--continue-after-detection`, `--seed`. Output: `$MALLORY_WORK/<case>/gc` and `prepared.json` (shared by
every seed), `$MALLORY_WORK/<case>/seed-<n>/{runs,state.json,result.json}`; every run keeps its plant, its
log, its gzipped trace and its log of door evaluations outside the window.

## Results (2026-10-25, CloudLab)

The three targets are bugs a single injected fault exposes: HDFS-17967 (PR apache/hadoop#8698) on its
`replaceBlock` proxy path, Solr's RESTORE retry that leaves a shard in CONSTRUCTION, and HBase's lost
backup-lock reply. Each case ran alone on one node, one trial at a time; the time to detect counts from the first
trial (the two healthy runs come before it). `data/<case>/` keeps each campaign's result, every trial
(`trials.json`) and the detecting run's plant (`detecting-plant.jsonl`, the input of `run_engine.sh plant-run`).

| case | bug | node | trials | time to detect | healthy noise | the detecting run's fault |
| --- | --- | --- | ---: | ---: | ---: | --- |
| hdfs-17967-pathB | HDFS-17967, `DataXceiver.replaceBlock` proxy | node2 | 1 | 9 s | 66 edges | `FAULT:HADOOP_IPC:REQUEST` on the proxy DataNode's `sendHeartbeat` (`Client$Connection.sendRpcRequest#u41`) |
| solr-bugs-restore-construction | a failed RESTORE leaves its slices in CONSTRUCTION | node1 | 51 | 893 s | 57 edges | `FAULT:SOLR_HTTP2:RESPONSE` on the Overseer's apply-buffered-updates shard request (`RestoreOnANewCollection.requestReplicasToApplyBufferUpdates`, `Http2SolrClient.processErrorsAndResponse#u11`) |
| hbase-bugs-backup-lock-reply-lost | lost reply of the backup lock's checkAndMutate | node0 | 169 | 2579 s | 0 edges | `FAULT:HBASE_RPC:RESPONSE` on the lock CAS's reply (`RpcConnection.finishCall#u39`, occurrence `95f9b23c7997b9e9`) |

Every detecting run applied its one planted fault and ended at the target's fatal arm at the declared occurrence
(GraphChecker's `AT_ANCHOR` end of a native run):

- **HDFS**: the workload's first fault marker is the heartbeat whose loss keeps the new block key from the
  DataNode, so the policy's first, optimistic choice found it (the run's graph: 62 edges added to the healthy
  graph, 136 lost).
- **Solr**: the failed shard request makes the first RESTORE fail ("operation: restore failed"); the test's
  second RESTORE succeeds on the existing collection, a path that never marks the slices ACTIVE, and the next
  update is refused with "No active slice servicing hash code ... in causynthRestore-target". This is the fault
  the bug report names (an HTTP fault at a RESTORECORE or apply-buffer shard request), not the ZooKeeper
  `setData` fault GraphChecker's own reproduction planted. 41 edges added, 119 lost.
- **HBase**: the client's retry re-runs the committed CAS and fails on its own lock row
  (`startBackupExclusiveOperation`'s throw arm). The policy reached it in its sweep of the healthy run's fault
  points (index 207 of its 219, each in a state of its own); 9 edges added, 29 lost.

Two fault-free runs of the same workload differ (thread interleavings, retries, timing): the healthy noise above is
how many edges the second added to the first. Before the reward discounted it, every Solr trial looked novel
(all of 38 trials had new edges, 32 of them no more than the noise) and the corpus filled with runs that showed
nothing a fault caused. The HDFS and HBase campaigns started before that change; HDFS detected at its first choice and
HBase's noise is 0, so neither run would differ under the current code. A second Solr case,
`solr-bugs-migrate-buffer-leak` (any fault after the buffer step leaves the target core BUFFERING), ran on node2
as a fallback and was stopped at 27 trials, undetected, once the RESTORE case had detected.
