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
  program order within each GraphChecker occurrence (its node, region and context: one sequential
  activation, whichever pool thread runs it), a send to its receipt (transport, correlation id, attempt,
  half), a store write to the reads and watch notifications of its version. Nodes are named by their role
  and an exchange by its transport and operation, since a run's placement and timing decide which DataNode
  or anchor plays a part. A run's observation is its edge set.
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

- **The workload: the system's own unit test.** A case runs a test of the system's repository, unchanged
  (`LeaderElectionSupportTest`, `TestBackupManager`, `TimeRoutedAliasUpdateProcessorTest`), as CrashFuzz's
  cases do; a test written to set up a bug is no workload of this baseline. GraphChecker's cluster adapter
  names the test's nodes (`cluster_automatic`); `marked_as` lets such a case check the target another
  GraphChecker case marked.
- **The oracle: the case's marked target check, counted.** GraphChecker reports every time the planted run
  takes the target's fatal arm (`PLANT_FATAL`). A run detects when it took it more often than any of three
  fault-free runs did, and more than twice as often where those already take it (`failure_threshold`: a
  test of the failure path, two sessions taking turns at a lock); the run goes on past the declared
  occurrence (`causynth.plant.continue`), so a failure that repeats is counted whole.
- **The graph.** GraphChecker records what its SEED selected: the full recorder is woven into the region
  skeleton methods of the target's backward Soot slice, transport and store events at every woven door
  and store hook, all inside the recording window. Mallory's feedback is therefore computed over the
  target's slice: this is the point of migrating GraphChecker's graph, and it is stated here because it
  steers the search toward the target.
- **Not the fault space.** GraphChecker explores only roots inside its window and its case scope. Mallory
  injects at every door of the system's catalog over the whole run, start-up and shutdown included, with
  no knowledge of which doors GraphChecker's analysis demands.

## GraphChecker and the systems

Mallory runs each system's cases on a GraphChecker checkout: GraphChecker's `system/<system>-cloudlab`
(`git@github.com:JHSUYU/GraphChecker.git`, at the commit [`graphchecker/bases.tsv`](graphchecker/bases.tsv) pins)
with the patches of [`graphchecker/`](graphchecker) applied. `graphchecker/apply.sh <GraphChecker clone>
<system>` makes it at `/bulk/wt/gc-mallory-<system>`, where `mallory/settings.py` looks for it, and builds the
jar.

- [`graphchecker/common/`](graphchecker/common), every system:
  1. *Native plant runs*: the `PLANT_MARKER` observation in `RecordingPlant`, `explore.TargetRows` (a plant's
     TARGET rows for the declared target, as `ConfirmMain` writes them), `run_engine.sh plant-run <run dir>
     <plant> [bound]` and `campaign_stop_after=PLAN`;
  2. *Doors outside the recording window*: `causynth.plant.outside`, `causynth.plant.outside.log`,
     `nanoTime` on marker rows, `CAUSYNTH_EXTRA_SCOPE` in `experiments/lib/case-env.sh`;
  3. an outside door call named by its nearest callers;
  4. `causynth.plant.continue`: a run goes on past the declared occurrence's fatal arm;
  5. `marked_as`: a case checking the target another case marked, with another workload.
- [`graphchecker/systems/<system>/`](graphchecker/systems), the cases this baseline adds on the systems' own
  tests: HBase `hbase-bugs-backup-lock-upstream` (`TestBackupManager`), HDFS `hdfs-17967-pathA-upstream`
  (`TestEncryptedTransfer`). Solr's `solr-adhoc-40` and ZooKeeper's `zk-bugs-election-offer` are GraphChecker's
  own cases, already on the systems' tests.

The system trees are GraphChecker's (its door hooks, the cluster adapters that name a test's nodes, the target
markers), unchanged; each fork's branch `baseline/mallory` pins the commit Mallory ran on:

| system | fork | tree (under `GC_TREES=/bulk/wt`) | `baseline/mallory` |
| --- | --- | --- | --- |
| HBase | `JHSUYU/hbase` (`graphchecker/hbase-checks`) | `hbase-checks` | b5d5cc6a20 |
| Solr | `JHSUYU/solr` (`graphchecker/solr-checks`) | `lucene-solr-checks` | 12d23091d1 |
| ZooKeeper | `JHSUYU/zookeeper` (`graphchecker/zookeeper-checks`) | `zookeeper-checks` | 889f0e9616 |
| HDFS | `JHSUYU/hadoop` (`graphchecker/hdfs-checks`) | `hadoop-hdfs-study-r7` | 899c200cc8 |

## Running it (CloudLab, node0-node4)

Set up the cluster, VM image and system trees as GraphChecker's REPRODUCE.md says for
`system/{hdfs,hbase,solr,zookeeper}-cloudlab` (each tree at its fork's `baseline/mallory`, under
`GC_TREES=/bulk/wt`), then `graphchecker/apply.sh <GraphChecker clone> <system>` for each system. Paths are in `mallory/settings.py`
(`MALLORY_GC_<SYSTEM>`, `MALLORY_WORK`, `MALLORY_NODES`).

```sh
cd mallory
python3 -m mallory prepare zk-bugs-election-offer --node node0     # SEED + PLAN, TARGET rows
python3 -m mallory run zk-bugs-election-offer --node node0         # the campaign (prepares if needed)
MALLORY_HEAP_BASIS_MB=32768 python3 -m mallory run hbase-bugs-backup-lock-upstream --node node0
python3 -m mallory report                                                     # every case's result
python3 -m unittest discover -s tests -t .
```

`run` prepares the case itself when it has no `prepared.json`. Budget flags: `--trials` (600), `--seconds`
(14400), `--max-faults` (3), `--trial-bound` (900, lowered to four times the healthy run),
`--continue-after-detection`, `--seed`. Output: `$MALLORY_WORK/<case>/gc` and `prepared.json` (shared by
every seed), `$MALLORY_WORK/<case>/seed-<n>/{runs,state.json,result.json}`; every run keeps its plant, its
log, its gzipped trace and its log of door evaluations outside the window.

## Results (2026-10-26, CloudLab)

Each bug was run on its system's own unit test, the whole pipeline from nothing twice (GraphChecker's SEED and
PLAN, three healthy runs, the campaign at the default seed), each run alone on one node. The time is wall clock
from the start of SEED to the end of the detecting run. `data/<case>/run-{a,b}/` keeps each run's result, every
trial (`trials.json`) and the detecting plant (`detecting.plant*.jsonl`, the input of `run_engine.sh plant-run`).

| bug | unit test | run a | run b | the detecting runs' faults |
| --- | --- | --- | --- | --- |
| SOLR-40: after a ZooKeeper failure a node's alias cache misses a routed alias; a valid update is rejected | `TimeRoutedAliasUpdateProcessorTest#test` | 46 trials, 1909 s | 45 trials, 1819 s | `SessionExpiredException` on a node's `SolrZkClient.getData` |
| HBase backup lock: a lost reply of the lock's compare-and-set; the retry finds its own lock forever | `TestBackupManager#testStartBackupExclusiveOperation` | 10 trials, 478 s | 9 trials, 464 s | lost or failed replies of the client's RPCs (`RpcConnection.finishCall`, `AbstractRpcClient.callMethod`) |
| ZooKeeper election recipe: a contender that fails reading the offers leaves its own offer behind | `LeaderElectionSupportTest#testNodes3` | 61 trials, 504 s | 81 trials, 637 s | `ConnectionLossException` on a contender's `ZooKeeper.getChildren` |

Every detecting run was checked against the bug's symptom:

- **SOLR-40**: the target throws 5 times (healthy runs: 0) and the log holds "Routed alias myalias appears
  to have been removed during request processing" 50 times.
- **HBase**: the target fails 214 times (healthy runs: 2, the second session waiting its turn); the test
  hangs until the trial bound with "Waiting to acquire backup exclusive lock" every minute: a session never
  acquires the lock again.
- **ZooKeeper**: the server refuses a getData of a node that no longer exists (the check GraphChecker marks
  for this bug), which no healthy run did. `testNodes3` itself passes: it asserts its failure count before
  its threads have run, and `start()` reports a failure only by entering FAILED.

Not detected: **HDFS-17967** (PR apache/hadoop#8698) on `TestEncryptedTransfer#testLongLivedClientPipelineRecovery`,
the only HDFS test that rotates block keys around a pipeline between DataNodes. Two runs of 294 trials (9729 s)
and 165 trials (4988 s) never failed the check more than its one deliberate stale-key rejection; the bug needs a
lost key-carrying heartbeat reply on the DataNode a random block placement makes the next mirror, within the two
seconds before the next rotation. Mallory was not run on it further.

Held-out checks: with the code unchanged, Mallory also ran on three checks never used while it was built
(Solr `solr-adhoc-09`, HBase `hbase-adhoc-08`, ZooKeeper `zk-adhoc-07`, each on its system's own test): every
run completed (1 hour, or every fault point of the test tried) with no false detection
([`data/heldout-2026-10-26.json`](data/heldout-2026-10-26.json); the repository README compares both baselines).

Earlier figures in this repository's history (2026-10-25: HDFS-17967 in 1 trial, Solr's RESTORE bug, HBase's
lock on `TestCausynthBackupLockReplyLost`) came from GraphChecker's own bug-shaped tests (`TestCausynth*`),
whose window and set-up leave only the fault to be found, and are withdrawn.
