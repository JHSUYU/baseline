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

Mallory runs each system's cases on a GraphChecker checkout: GraphChecker's `system/<system>-buggy-detect`
(`git@github.com:JHSUYU/GraphChecker.git`, at the commit [`graphchecker/bases.tsv`](graphchecker/bases.tsv) pins: the
liftlab branch that holds the system's ad hoc cases and its old-bug cases) with the patches of
[`graphchecker/<system>/`](graphchecker) applied. `graphchecker/apply.sh <GraphChecker clone> <system>` makes it at
`/bigtemp/vnr3ne/wt/gc-mallory-<system>`, where `mallory/settings.py` looks for it, and builds the jar.

Each system's series is the same five changes, then the system's own case:
  1. *Native plant runs*: the `PLANT_MARKER` observation in `RecordingPlant`, `explore.TargetRows` (a plant's
     TARGET rows for the declared target, as `ConfirmMain` writes them), `run_engine.sh plant-run <run dir>
     <plant> [bound]` and `campaign_stop_after=PLAN`;
  2. *Doors outside the recording window*: `causynth.plant.outside`, `causynth.plant.outside.log`,
     `nanoTime` on marker rows, `CAUSYNTH_EXTRA_SCOPE` in `experiments/lib/case-env.sh`;
  3. an outside door call named by its nearest callers;
  4. `causynth.plant.continue`: a run goes on past the declared occurrence's fatal arm;
  5. `marked_as`: a case checking the target another case marked, with another workload;
  6. the cases this baseline adds on the systems' own tests: HBase `hbase-bugs-backup-lock-upstream`
     (`TestBackupManager`), HDFS `hdfs-17967-pathA-upstream` (`TestEncryptedTransfer`). Solr's `solr-adhoc-40` and
     ZooKeeper's `zk-bugs-election-offer` are GraphChecker's own cases, already on the systems' tests.

The series were first made on CloudLab's `system/<system>-cloudlab` (now GraphChecker's tags
`archive/system/<system>-cloudlab`); on liftlab their added and removed lines are the same, and only HBase's
fourth change sits in another context (the buggy-detect branch's `plantFatal` call carries one more argument).

The system trees are GraphChecker's (its door hooks, the cluster adapters that name a test's nodes, the target
markers), unchanged. For the baseline bugs each fork's branch `baseline/mallory` pins the commit Mallory runs on;
`graphchecker/trees.sh <case>...` clones it under `MALLORY_GC_TREES` (default `/bigtemp/vnr3ne/wt/mallory-trees-1`)
and builds it for the case (`run.sh <case> build`, Maven repository `MALLORY_GC_M2`, default
`/bigtemp/vnr3ne/m2/mallory-1`):

| system | fork | tree | `baseline/mallory` |
| --- | --- | --- | --- |
| HBase | `JHSUYU/hbase` (`graphchecker/hbase-checks`) | `hbase-checks` | b5d5cc6a20 |
| Solr | `JHSUYU/solr` (`graphchecker/solr-checks`) | `lucene-solr-checks` | 12d23091d1 |
| ZooKeeper | `JHSUYU/zookeeper` (`graphchecker/zookeeper-checks`) | `zookeeper-checks` | 889f0e9616 |
| HDFS | `JHSUYU/hadoop` (`graphchecker/hdfs-checks`) | `hadoop-hdfs-study-r7` | 899c200cc8 |

The old bugs (below) run on the buggy-detect branches' own tree set, each bug's tree its fork's
`graphchecker/<system>-bug-<jira>` (GraphChecker's `experiments/<system>/trees.tsv` and `prepare-trees.sh`), with
`MALLORY_GC_TREES` and `MALLORY_GC_M2` pointing at it.

## Running it (liftlab)

The liftlab cluster: workers lift02-06, lift08-10 and lift12-14 (`MALLORY_NODES`), each with Java 8 at
`/usr/lib/jvm/java-8-openjdk-amd64`; lift11 is the control host the campaigns are driven from (a campaign's
GraphChecker commands run on its node over ssh); `/bigtemp/vnr3ne` is NFS-shared by every lift, `/localtmp` is each
lift's local disk. Maven is on the PATH of lift02-06 and lift08-10. The VM images are GraphChecker's
(`/bigtemp/vnr3ne/vm-force12` for HDFS and HBase, `vm-force13` for ZooKeeper, `vm-force10` for Solr;
`MALLORY_IMAGE_<SYSTEM>`). On a Maven host:

```sh
graphchecker/apply.sh ~/GraphChecker <system>                    # for hdfs hbase solr zookeeper
graphchecker/trees.sh solr-adhoc-40 hbase-bugs-backup-lock-upstream zk-bugs-election-offer hdfs-17967-pathA-upstream
```

Then, from `mallory/` on lift11 (paths in `mallory/settings.py`: `MALLORY_GC_<SYSTEM>`, `MALLORY_WORK`,
`MALLORY_GC_TREES`, `MALLORY_GC_M2`, `MALLORY_NODES`):

```sh
python3 -m mallory prepare zk-bugs-election-offer --node lift02     # SEED + PLAN, TARGET rows
python3 -m mallory run zk-bugs-election-offer --node lift02         # the campaign (prepares if needed)
python3 -m mallory report                                           # every case's result
python3 -m unittest discover -s tests -t .
```

`run` prepares the case itself when it has no `prepared.json`. Budget flags: `--trials` (600), `--seconds`
(14400), `--max-faults` (3), `--trial-bound` (900, lowered to four times the healthy run),
`--continue-after-detection`, `--seed`. Output: `$MALLORY_WORK/<case>/gc` and `prepared.json` (shared by
every seed), `$MALLORY_WORK/<case>/seed-<n>/{runs,state.json,result.json}`; every run keeps its plant, its
log, its gzipped trace and its log of door evaluations outside the window.

`replay <case>` runs a campaign's detecting plan again (`--repeats`, 10), through the same plant, matching and oracle,
into `seed-<n>/replay/replay.json`. `--generalize` plants each fault at its siblings in the detecting run instead, into
`seed-<n>/replay-generalized/`; the sibling rule is in `faults.generalized`.

### Reproducing the liftlab tables

1. Checkouts and baseline-bug trees, on a Maven host: `apply.sh` for each system, then `trees.sh` for the four cases,
   as above.
2. The old-bug trees: in each system's checkout, run
   `GC_TREES=<old-bug tree set> GC_M2=<its Maven repository> experiments/<system>/prepare-trees.sh <tree>...`. Use the
   trees its `trees.tsv` names `*-bug-<jira>`: `hadoop-hdfs-bug-<jira>`, `hbase-bug-<jira>`, `zookeeper-bug-<jira>` and
   `solr-bug-<jira>`. Each clones its fork's `graphchecker/<system>-bug-<jira>` from GitHub and builds it.
3. Each baseline-bug run, from nothing, alone on a node:
   `MALLORY_WORK=<work>/run-a python3 -m mallory run <case> --node <node>`; `run-b` is a second work directory.
4. Each old bug, on any node:
   `MALLORY_WORK=<work>/old MALLORY_GC_TREES=<old-bug tree set> MALLORY_GC_M2=<its Maven repository> python3 -m mallory run <case> --node <node>`.
5. Every detection: `python3 -m mallory replay <case> --node <node>` with the same environment, and `--generalize` where
   the exact plan replays less than 10/10.
6. `scripts/export-liftlab.py <work> data run-a=liftlab/run-a run-b=liftlab/run-b old=liftlab/old-bugs` copies the
   records into `data/`.

On liftlab: `<work>` is `/bigtemp/vnr3ne/mallory-work`, the old-bug tree set `/bigtemp/vnr3ne/wt/bd-trees-1` with
`/bigtemp/vnr3ne/m2/bd-1`.

## Results on liftlab (2026-10-29)

The CloudLab runs below were made again on liftlab, the cluster GraphChecker's results now come from:
- the same bugs, unit tests and protocol;
- each pipeline run from nothing (GraphChecker's SEED and PLAN, three healthy runs, the campaign at the default seed);
- twice, and each run alone on one node (lift02-04).

The time is wall clock from the start of SEED to the end of the detecting run. Every detection was then replayed 10 times
(`python3 -m mallory replay <case>`: the detecting plan through the same plant, matching and oracle). Where the exact plan
did not replay 10/10, it was also replayed generalized (`--generalize`: each fault planted at its siblings in the detecting
run, a replay aid, not the detection). `data/liftlab/run-{a,b}/<case>/` keeps each run's result, every trial
(`trials.json`), the detecting plant (`detecting.plant*.jsonl`), the detecting run's trace (`detecting.trace.jsonl.gz`) and the replays (`replay*.json`).

| bug | unit test | run a | replay a | run b | replay b | CloudLab a / b |
| --- | --- | --- | --- | --- | --- | --- |
| solr-adhoc-40 | `TimeRoutedAliasUpdateProcessorTest#test` | trial 45, 2201 s | 10/10 | trial 44, 2083 s | 9/10 (generalized 0/10) | 46 trials, 1909 s / 45 trials, 1819 s |
| hbase-bugs-backup-lock-upstream | `TestBackupManager#testStartBackupExclusiveOperation` | trial 14, 620 s | 3/10 (generalized 10/10) | trial 10, 656 s | 3/10 (generalized 10/10) | 10 trials, 478 s / 9 trials, 464 s |
| zk-bugs-election-offer | `LeaderElectionSupportTest#testNodes3` | not detected (225 trials, 217 applied, every candidate tried, 1859 s) | - | not detected (210 trials, 193 applied, every candidate tried, 1785 s) | - | 61 trials, 504 s / 81 trials, 637 s |
| hdfs-17967-pathA-upstream | `TestEncryptedTransfer#testLongLivedClientPipelineRecovery[1]` | not detected (370 trials, 272 applied, budget, 14712 s) | - | not detected (347 trials, 306 applied, budget, 14624 s) | - | not detected (294 + 165 trials) |

- **SOLR-40** (both runs detected):
  - Run a lost `SolrZkClient.create`'s session (`SessionExpiredException`), run b `SolrZkClient.getData`'s.
  - The target throws 6 times (healthy runs: 0), and "Routed alias myalias appears to have been removed during
    request processing" is logged 60 times.
  - Run b's exact plan replays 9/10. Its generalized plan replays 0/10: failing every node's alias read changes what the
    run does, so the exact plan is the reproduction there.
- **HBase backup lock** (both runs detected):
  - The detecting runs fail the target 211 and 204 times (healthy: 2) and hang to the trial bound, with "Waiting to acquire
    backup exclusive lock" every minute.
  - The exact plans replay 3/10. In every replay the lost reply is the same request, the first lock compare-and-set of
    `startBackupExclusiveOperation`. Whether it matters depends on which of the test's two sessions commits its
    compare-and-set first, a race the plan does not control.
  - Generalized, the reply of every such compare-and-set (each session's) is lost. Both detections then replay 10/10
    (140-170 target failures).
- **ZooKeeper election recipe** (neither run detected):
  - Both runs tried every fault point (225 and 210 trials).
  - On liftlab, two of a run's three fault-free runs already take the check once: the test's own race, a contender
    reading an offer another has just deleted. So Mallory's oracle asks for more than 2 failures in a run.
  - 21 and 12 trials failed the check once: a detection by CloudLab's healthy runs (0), not by liftlab's.
  - The oracle is kept as it is.
- **HDFS-17967**: not detected, as on CloudLab. Both runs spent the 4-hour budget: 370 trials (272 applied) and 347 (306 applied), with 506 and 566 candidates left. No trial failed the check more than its one deliberate stale-key rejection, which every healthy run takes too. The 98 and 41 trials that did not apply have whole traces: their planted point did not recur in that run.

A defect of the first liftlab runs, fixed before these:
- The driver (on lift11) looked up a run's directory before the node wrote it, and the NFSv3 lookup cache then hid the
  trace for up to a minute. About every other trial counted as not applied, though its fault and its fatal arm were in
  the trace.
- `campaign._run` now creates the run directory and the outside log first, and waits for a trace not yet visible.
- Those runs were discarded and every run here was made from nothing after the fix.

### The old bugs (liftlab, 2026-10-29)

The old bugs GraphChecker's buggy-detect branches put back by hand (`docs/handover/BUGGY-DETECT.md` on
`system/<system>-buggy-detect`): 16, of which 14 are runnable. HBASE-28533 has no workload (GraphChecker found its throw
unreachable on today's code), and SOLR-6763 has no tree.

Mallory ran each once, on GraphChecker's own case:
- the bug's tree (`graphchecker/<system>-bug-<jira>`, the buggy-detect tree set: `MALLORY_GC_TREES`);
- **the workload GraphChecker detected the bug with**, the case's `TestCausynth*` test. These are bug-shaped tests, which
  Mallory's own protocol above excludes. They are given here so that Mallory and GraphChecker are compared on one input:
  the release tests carry the fixes of these old bugs, and no existing test is known to reach most of them;
- the oracle at the point's own declared throw, the standard GraphChecker's old-bug table uses;
- the default budget (600 trials, 4 h), up to three campaigns per node.

`data/liftlab/old-bugs/<case>/` keeps each record.

| bug | case | Mallory (one run, 600 trials / 4 h) | replay | the detecting faults |
| --- | --- | --- | --- | --- |
| HDFS-11741 | `hdfs-buggy-11741` | trial 40, 572 s | 10/10 | FAULT:HADOOP_IPC:RESPONSE:SocketTimeoutException @ Client.getRpcResponse#u17; FAULT:HADOOP_IPC:RESPONSE:SocketTimeoutException @ Client.getRpcResponse#u17 |
| HDFS-17383 | `hdfs-buggy-17383` | trial 32, 790 s | 10/10 | FAULT:HADOOP_IPC:RESPONSE @ Client.getRpcResponse#u7 |
| HDFS-12931 | `hdfs-buggy-12931` | trial 5, 205 s | 10/10 | FAULT:HADOOP_IPC:REQUEST @ Client$Connection.sendRpcRequest#u41 |
| HDFS-5766 | `hdfs-buggy-5766` | trial 6, 242 s | 10/10 | FAULT:HADOOP_IPC:RESPONSE:SocketTimeoutException @ Client.getRpcResponse#u17 |
| HDFS-10609 | `hdfs-buggy-10609` | trial 41, 565 s | 10/10 | FAULT:HADOOP_IPC:REQUEST @ Client$Connection.sendRpcRequest#u41; FAULT:HADOOP_IPC:RESPONSE:SocketTimeoutException @ Client.getRpcResponse#u17 |
| HDFS-14075 | `hdfs-buggy-14075` | trial 1, 308 s | 10/10 | FAULT:LOCAL_IO:OPEN:FileNotFoundException @ EditLogFileOutputStream.<init>#u26 |
| HDFS-14311 | `hdfs-buggy-14311` | not detected (388 trials, 382 applied, budget, 14871 s) | - | - |
| HBASE-15039 | `hbase-buggy-15039` | trial 5, 394 s | 10/10 | FAULT:ZOOKEEPER:READ:KeeperException$ConnectionLossException @ ZKSecretWatcher.nodeChildrenChanged#u7 |
| HBASE-20642 | `hbase-buggy-20642` | trial 113, 3889 s | 10/10 | FAULT:HBASE_RPC:REQUEST @ AbstractRpcClient.callMethod#u60; FAULT:HBASE_RPC:RESPONSE:CallTimeoutException @ RpcConnection.finishCall#u44 |
| ZOOKEEPER-710 | `zk-buggy-710` | not detected (20 trials, 20 applied, every candidate tried, 298 s) | - | - |
| ZOOKEEPER-2886 | `zk-buggy-2886` | not detected (20 trials, 20 applied, every candidate tried, 314 s) | - | - |
| SOLR-9440 | `solr-buggy-9440` | trial 25, 1497 s | 10/10 | FAULT:ZOOKEEPER:READ:KeeperException$SessionExpiredException @ SolrZkClient.getChildren#u10; FAULT:ZOOKEEPER:WRITE:KeeperException$ConnectionLossException @ SolrZkClient.setData#u16 |
| SOLR-6101 | `solr-buggy-6101` | not detected (439 trials, 439 applied, budget, 14546 s) | - | - |
| SOLR-6197 | `solr-buggy-6197` | not detected (276 trials, 264 applied, budget, 14616 s) | - | - |

How each detection relates to its bug:
- **HDFS-12931, -5766, -10609, -17383**: a lost heartbeat request or reply leaves the DataNode without the rotated key.
  This is GraphChecker's mechanism for these bugs, with the same caveat for 12931, 5766 and 10609: the DataNode throws on
  the fixed code too.
- **HDFS-11741**: the same lost key-update heartbeat, on the Balancer's proxy DataNode. The point's own throw fires, but
  not by HDFS-11741's mechanism: the Balancer's expired cached key, which GraphChecker's witness moves the clocks for.
  The fix would not prevent this failure.
- **HDFS-14075**: the first trial's fault is GraphChecker's mechanism, a failed open of roll 1's edits file.
- **HBASE-15039**: the watcher's ZooKeeper read fails (`ZKSecretWatcher.nodeChildrenChanged`), the fault the case README
  accepts for a MARKER claim of this bug.
- **HBASE-20642**: a lost request, then a reply timeout; the client's retry, with a new nonce, meets the master's
  `preflightChecks`. This is GraphChecker's mechanism family.
- **SOLR-9440**: a `SessionExpiredException` before the window, then a lost `setData` of node0's Overseer state update.
  These are other faults than GraphChecker's witness (node1's leader-election create); the point's throw is the same.
- **ZOOKEEPER-710, -2886**: not detected. Their 20 fault points (the client's ZooKeeper calls) were all tried. The bugs
  need a request paired with a session's move to another server (GraphChecker's STATE re-pairing), which no injected
  failure makes.
- **HDFS-14311**: not detected in 4 h (388 trials). GraphChecker does not detect it either: it needs a STATE re-pairing of a volume's layout-version read.
- **SOLR-6101, -6197**: not detected in 4 h (439 and 276 trials, no failure of the check). Their mechanism is a cluster-wide configuration change (`legacyCloud` true -> false), which is not a fault.

Tally: Mallory detects 9 of the 14 (every detection replays 10/10), GraphChecker 13. HDFS-11741's and SOLR-9440's detections fire the point's own throw by other faults than the bug's; HDFS-14311 neither tool detects.

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
