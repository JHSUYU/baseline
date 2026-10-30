# CrashFuzz-style baseline for ad hoc coordination checks

CrashFuzz fuzzes a distributed system by injecting faults at the points its
I/O actually executes and steering later fault sequences toward runs that
reach new code or new I/O. This baseline applies that idea to the 102 ad hoc
coordination checks of [`data/checklist102.json`](data/checklist102.json)
(HDFS 3.4.3, HBase 2.6.6, Solr 8.11.4, ZooKeeper 3.8.7), with each system's
**own cluster JUnit test, unchanged,** as the workload:

1. **Select.** A coarse Soot pass ([`static-selection/`](static-selection)) walks
   bounded callers and callees of the check's method, field reads to their
   possible writers, thread hand-offs and RPC producer mappings, and selects the
   methods to cover, their branches, the I/O callsites that may fault, and the
   check's typed throw sites with the branches that control them.
2. **Observe.** An ASM agent ([`runtime-agent/`](runtime-agent)) records only the
   selected sites. The healthy run lists every selected I/O execution as a fault
   point: callsite, runtime actor (with a stable logical-node suffix where the
   system has one), hit ordinal, and phase -- `before` a call, or `after` a
   call that completed, i.e. its reply is lost. If the healthy run executes no
   selected I/O, the selection widens (callers 6 deep, then 800 methods).
3. **Fuzz.** Each trial reruns the same JUnit with an ordered sequence of exact
   fault selectors (`IOException`; `ConnectionLossException` for ZooKeeper
   calls; a statically declared typed exception as a variant before a call). A
   fault counts only when its full runtime identity matched. A run that still
   executes the check after its last fault seeds descendants: the sequence
   extended by one I/O point the run executed after that fault. The queue
   prefers untried I/O sites, new temporal families and new coverage; a fixed
   table of bounded slots ([`crashfuzz/scheduler.py`](crashfuzz/scheduler.py))
   reserves shares for multi-node reply loss, repeated reply loss on one actor,
   cross-node plans, same-actor follow-ups, deep sequences and late
   occurrences of a callsite.
4. **Oracle.** A candidate is the check's typed exception, on a complete fatal
   route inside the target call, after the last applied fault, more often than
   in the healthy run. The selected `throw` is seen at its source line; when it
   throws a callee's result (`throw make(x)`, Soot's `thrown_by_call`) the
   callee throws, so the target method's typed exit in its call is the throw. A candidate is a hypothesis: its fault plan is replayed
   and the source reviewed before it is called a bug.

New campaigns start with 80 trials and at most ten faults per sequence and
continue to the budget (240 by default) only while at least one trial keeps
the target after its faults and fewer than 30 do.

## Layout

| path | what |
| --- | --- |
| `crashfuzz/` | the Python package (stdlib only): `trace`, `faults`, `oracle`, `scheduler`, `campaign`, `selection`, `runners/`, `tree`, `worker`, `cluster`, `report`, `settings`, `systems` |
| `crashfuzz/runners/` | one module per system running one unchanged JUnit method under the agent, and `tree` for a built source tree's; the JUnit 4 and Jupiter launchers (`java/`) and HBase's test-only SSL utility |
| `runtime-agent/`, `static-selection/` | the Java agent (with the tree mode's `NeutralAdapter`) and the Soot selector (Maven) |
| `systems/` | the HDFS RPC wire mapping the selector follows; the ZooKeeper tree workloads' logging configuration |
| `scripts/setup-deps.sh` | the Apache releases and sources, verified, in the expected layout |
| `tests/` | `python3 -m unittest discover -s crashfuzz/tests` (from the repository root) |
| `data/` | the 102-check selection, the baseline bugs, the old-bug tree rows, the campaign records and the source reviews |
| `vendor/` | the JUnit Platform launcher the Jupiter runner uses |

## Setup

Paths come from the environment (`crashfuzz/settings.py`); the defaults are
the liftlab cluster's, where `/bigtemp/vnr3ne` is NFS-mounted at the same path
on every lift (the home directory is NFS too, under a 100 G quota, so nothing
bulky goes there; `/localtmp` is each lift's local disk):

| variable | default | what |
| --- | --- | --- |
| `CRASHFUZZ_DEPS` | `/bigtemp/vnr3ne/baseline-deps` | release binaries; `sources/` beside them |
| `CRASHFUZZ_RESULTS` | `/bigtemp/vnr3ne/crashfuzz-results` | results root |
| `CRASHFUZZ_JAVA_HOME` | `/usr/lib/jvm/java-8-openjdk-amd64` | the JDK every JUnit and every Maven build runs on |
| `CRASHFUZZ_M2` | `/bigtemp/vnr3ne/m2/crashfuzz` | the Maven repository of every build and test-only jar (bouncycastle, minikdc, JaCoCo, ...) |
| `CRASHFUZZ_MVN` | `mvn` on `PATH`, else `/usr/lib/maven/bin/mvn` | Maven (lift02-06 and lift08-10 have it on `PATH`, lift11-15 under `/usr/lib/maven/bin`) |
| `CRASHFUZZ_BUILD` | `crashfuzz/build` | compiled launchers, unpacked test jars (shared by the nodes through the checkout) |

```sh
crashfuzz/scripts/setup-deps.sh      # on a lift with Maven: downloads, verifies, unpacks; builds the
                                     # ZooKeeper tree, the agent and the selector
python3 -m unittest discover -s crashfuzz/tests
```

## Run

From `crashfuzz/` (the package directory's parent):

```sh
python3 -m crashfuzz run --case-id SOLR-40                   # one case, end to end, resumable
python3 -m crashfuzz worker --system HBase                   # every HBase case
python3 -m crashfuzz cluster --nodes lift08 lift09 lift10 lift12 lift13 lift14 --system Solr -- --max-trials 240
python3 -m crashfuzz replay --case-id SOLR-40 --plan plan.json --repeats 10 --name aliases
python3 -m crashfuzz report --output /bigtemp/vnr3ne/crashfuzz-results/table.tsv
```

`cluster` starts one detached worker per node over ssh, in this checkout's
`crashfuzz/` directory: the repository must be at the same path on every node
(on liftlab a checkout under `/bigtemp`, which every lift mounts).
Node `i` of `N` takes every `N`-th case of the system. A case's flock and
heartbeated lease keep two workers from running it at once, and a restarted
worker resumes unfinished cases without rerunning finished trials. `replay` runs one fault sequence (a
JSON list of fault points, or a trial's `fault-trial.json`) a number of times
on the case's selection and healthy run, through the same matching and oracle.

## Tree mode: a workload on a built source tree

A checklist row normally runs its system's Apache release. A row with a
`tree` field runs a built checkout instead -- for an old bug put back by hand
on today's code, whose fix the releases already hold
([`crashfuzz/tree.py`](crashfuzz/tree.py), [`runners/tree.py`](crashfuzz/runners/tree.py)):

```json
"tree": {"path": "/bigtemp/vnr3ne/wt/bd-trees-1/hadoop-hdfs-bug-11741",
         "jvm_properties": ["-Dtest.build.data={data}", "-Dtest.cache.data={test_classes}"]}
```

- **Classpath:** the `java.class.path` the tree's own test run recorded in its JUnit XML report (Surefire's or
  Ant's), with every jar of a tree module replaced by that module's compiled classes, and every entry holding
  GraphChecker's classes (`edu/uva/liftlab/graphchecker`) dropped.
- **Neutral adapter:** a tree may call an adapter API it builds against as a `provided` dependency
  (GraphChecker's bug trees call GraphChecker's runtime doors, `MessageDoors`, `Sessions`, and Hadoop's
  `CausynthMessagePropagation` shim). The agent jar's `NeutralAdapter` reads the tree's classes and writes a
  stand-in for exactly the classes of that namespace they reference and nothing provides: every method returns
  `false`, zero, `""`, an empty array, a neutral instance or `null`; a `void` door handed a `Runnable` runs it
  (delivering a watch notification); nothing is recorded, held or deferred. No GraphChecker class is on the
  classpath (`<case>/tree-adapter/neutral-adapter.json` lists every stand-in member and its answer).
- **Selection:** Soot analyses the tree's classes of the modules the release analysis reads
  (`SystemSpec.analysis_jars`: for HDFS hadoop-hdfs, -hdfs-client, -common; for Solr solr-core and solrj; ...).
- **Run:** the test's JUnit flavour (Jupiter or JUnit 4) is read off its class; the JVM runs in a fresh scratch
  directory, never in the tree, with the row's `jvm_properties` (`{tmp}`, `{data}`, `{scratch}`, `{tree}`,
  `{test_classes}`, `{systems}`).
- The oracle is the row's own: the typed throw at `exact_check_location` in the tree's source.

[`data/old-bugs.json`](data/old-bugs.json) holds such rows for GraphChecker's buggy-detect cases.

## Reproduce on liftlab from a fresh clone

Every path below is a `settings.py` default that the environment overrides (`CRASHFUZZ_DEPS`, `CRASHFUZZ_RESULTS`,
`CRASHFUZZ_M2`, `CRASHFUZZ_TREES`, `CRASHFUZZ_MVN`, `CRASHFUZZ_JAVA_HOME`, `CRASHFUZZ_RUNTIME_AGENT_JAR`). The
checkout must sit at the same path on every lift (under `/bigtemp`, which they all mount); run JUnit only on
lift08-10 and lift12-14 (lift02-06 are GraphChecker's, lift11 is the control host).

1. **Dependencies** (once, on a lift with Maven, e.g. lift08):

   ```sh
   git clone git@github.com:JHSUYU/baseline.git && cd baseline
   crashfuzz/scripts/setup-deps.sh                      # releases, sources, ZooKeeper build, agent, selector
   python3 -m unittest discover -s crashfuzz/tests
   ```

2. **The old-bug trees** (tree mode only). GraphChecker builds them; CrashFuzz only reads them. Each row of
   [`data/old-bugs.json`](data/old-bugs.json) names its tree (`tree.path`, under `CRASHFUZZ_TREES`, default
   `/bigtemp/vnr3ne/wt/bd-trees-1`), the fork branch it is (`tree.branch`, `graphchecker/<sys>-bug-<jira>` of
   github.com/JHSUYU/hadoop, hbase, zookeeper or solr) and the commit the runs used (`tree.commit`). A tree is a
   clone of that branch built with its workload test run once: that run's JUnit report is the classpath CrashFuzz
   reads. GraphChecker's branch `system/<sys>-buggy-detect` (github.com/JHSUYU/GraphChecker; `<sys>` = hdfs,
   hbase, zookeeper, solr) does both:

   ```sh
   git clone git@github.com:JHSUYU/GraphChecker.git && cd GraphChecker
   git checkout system/hdfs-buggy-detect && mvn -q package -DskipTests   # the trees compile against its jar
   GC_TREES=/bigtemp/vnr3ne/wt/bd-trees-1 GC_M2=/bigtemp/vnr3ne/m2/bd-1 \
     bash experiments/hadoop/prepare-trees.sh hadoop-hdfs-bug-11741 hadoop-hdfs-bug-17383   # ... every HDFS tree
   # likewise system/hbase-buggy-detect + experiments/hbase, system/zookeeper-buggy-detect + experiments/zookeeper,
   # system/solr-buggy-detect + experiments/solr, with the rows' tree names
   ```

   GraphChecker's jar is a `provided` dependency of the trees, needed to compile them; at run time CrashFuzz drops
   it from the classpath and supplies its neutral adapter instead (see Tree mode). Check each tree out at its row's
   `tree.commit` if the branch has moved since. A tree built at another path is re-rooted from its report.

3. **Runs.** From `crashfuzz/`. Each baseline-bug run alone on its node, the two runs of a bug in their own results
   roots; the old-bug campaigns may share a node, at most three, each with its own `CRASHFUZZ_WORKER_ID` (1-3,
   `CRASHFUZZ_WORKER_COUNT=3`), started below 60 % memory:

   ```sh
   R=/bigtemp/vnr3ne/crashfuzz-results/liftlab-2026-10-29
   # baseline bugs, runs a and b (detected on CloudLab: no budget options; not detected: the 4-hour budget)
   python3 -m crashfuzz --checklist data/baseline-bugs.json run --case-id SOLR-40 --stop-at-candidate --results $R/baseline-a
   python3 -m crashfuzz --checklist data/baseline-bugs.json run --case-id HBASE-BACKUP-LOCK --stop-at-candidate --results $R/baseline-a
   python3 -m crashfuzz --checklist data/baseline-bugs.json run --case-id ZK-ELECTION-OFFER --stop-at-candidate \
     --max-trials 10000 --max-seconds 14400 --results $R/baseline-a
   python3 -m crashfuzz --checklist data/baseline-bugs.json run --case-id HDFS-17967-A --stop-at-candidate \
     --max-trials 10000 --max-seconds 14400 --results $R/baseline-a
   # (the same four with --results $R/baseline-b)
   # old bugs, one run each (case ids: the rows of data/old-bugs.json)
   CRASHFUZZ_WORKER_ID=1 CRASHFUZZ_WORKER_COUNT=3 python3 -m crashfuzz --checklist data/old-bugs.json run \
     --case-id HDFS-11741 --stop-at-candidate --max-trials 10000 --max-seconds 14400 --results $R/old-bugs
   ```

   **Replays** of a candidate's plan, 10 times, on the selection and healthy run of the run that found it (the
   exact command is in the case's evidence file; the plan is the file beside it):

   ```sh
   python3 -m crashfuzz --checklist data/baseline-bugs.json replay --case-id SOLR-40 \
     --plan data/evidence/SOLR-40/plan-liftlab-a-trial33.json --repeats 10 --name liftlab-a-trial33 --results $R/baseline-a
   ```

4. **Results** land under the results root: `<root>/<case>/case-summary.json` (status, trials, first candidate and
   its time), `<root>/<case>/campaign*/<case>/` (checkpoint, `result.json`, `trials/NNNN-*/` with each trial's fault
   plan `fault-trial.json`, traces and JUnit logs), `<root>/<case>/replay-<name>/<case>/` (the replays), and for a
   tree row `<root>/<case>/tree-workload.json` and `tree-adapter/neutral-adapter.json` (its classpath and the
   stand-ins it got). `data/evidence/<case>/` keeps, per run, the summary, the first candidate, the plan file, the
   replay command and k/10.

## Results

```
<results>/<case>/
  case-summary.json            the case's status, counts and pointers
  soot-selection.json          (caller-expanded*/ when widened)
  healthy*/                    the healthy run: manifest.json, runtime_trace.jsonl, junit.log
  campaign-config.json
  campaign*/<case>/state.json  the resumable checkpoint (queue, completed trials)
  campaign*/<case>/result.json the campaign record
  campaign*/<case>/trials/NNNN-<sequence>/  fault-trial.json, attempt-NN/, result.json
```

A completed non-candidate trial's traces and logs are gzipped; candidates stay
uncompressed for review.

## Data

[`data/`](data/README.md) holds the earlier campaigns: the 104-row checklist
(102 selected checks and two HDFS known-issue controls), the Soot-selected
rerun table [`static102-rerun.tsv`](data/static102-rerun.tsv), per-case records,
evidence and source reviews.

## Results on liftlab (2026-10-29/30)

Reran here with the CloudLab protocol. Every detection's candidate plan was replayed 10 times on the run's own
selection and healthy run; the table gives the exact plan's k/10, and beside it a general replay variant's where
one was used (see below). Each row links its evidence file in `data/evidence/<case>/`, which holds per run the
command, the summary, the first candidate, the plan file and every replay's command, agent and k/10.

### Baseline bugs

Each run alone on its node (times are wall clock to the first candidate, as on CloudLab; JUnit seconds in the
evidence). SOLR-40 and HBASE-BACKUP-LOCK are the detections; ZK-ELECTION-OFFER and HDFS-17967-A are not detected,
as on CloudLab.

| bug | unit test | liftlab a | liftlab b | CloudLab a | CloudLab b | detected? replay k/10 | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SOLR-40 (stale routed-alias cache after a ZooKeeper failure) | `TimeRoutedAliasUpdateProcessorTest.test` | trial 33, 1595 s | trial 103, 5749 s | trial 44, 2719 s | trial 37, 1999 s | detected; a 4/10, 8/10 (siblings), b 1/10 | [link](data/evidence/SOLR-40/time-to-detect-2026-10-29-liftlab.json) |
| HBase backup lock (lost compare-and-set reply) | `testStartBackupExclusiveOperation` | trial 11, 760 s | trial 17, 946 s | trial 23, 1182 s | trial 11, 783 s | detected; a 10/10, b 10/10 | [link](data/evidence/HBASE-BACKUP-LOCK/time-to-detect-2026-10-29-liftlab.json) |
| ZooKeeper election recipe (orphaned offer) | `testNodes3` | trial 1326, 40436 s (FP, JUnit passes) | not in 1383 trials (14401 s) | not in 273 trials | not in 271 trials | not detected; a 0/10 | [link](data/evidence/ZK-ELECTION-OFFER/time-to-detect-2026-10-29-liftlab.json) |
| HDFS-17967 path A (pipeline relay missing the block key) | `testLongLivedClientPipelineRecovery[0]` | not in 454 trials (14426 s) | not in 445 trials (14426 s) | not in 80+166 trials | not in 80+126 trials | not detected; - | [link](data/evidence/HDFS-17967-A/time-to-detect-2026-10-29-liftlab.json) |

### Old bugs in tree mode

GraphChecker's buggy-detect cases, run on the bug's built tree ([`data/old-bugs.json`](data/old-bugs.json)) with the
test GraphChecker used and the point's own throw as oracle; one run each, `--stop-at-candidate --max-trials 10000
--max-seconds 14400`.

| bug | GraphChecker point | healthy s / reached | result | trials | JUnit s | replay k/10 | first candidate plan | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HDFS-11741 | hdfs-adhoc-11 | 11.336 / yes | detected | 7 | 85 | 10/10 | IOException after sendHeartBeat#u75 on hdfs:dn:data1; IOException after sendHeartBeat#u75 on hdfs:dn:data1 | [link](data/evidence/HDFS-11741/old-bug-2026-10-29-liftlab.json) |
| HDFS-17383 | hdfs-adhoc-12 | 9.684 / yes | not detected | 593 | 14488 | - | - | [link](data/evidence/HDFS-17383/old-bug-2026-10-29-liftlab.json) |
| HDFS-12931 | hdfs-adhoc-11 | 10.834 / yes | not detected | 788 | 14405 | - | - | [link](data/evidence/HDFS-12931/old-bug-2026-10-29-liftlab.json) |
| HDFS-5766 | hdfs-adhoc-11 | 16.944 / yes | not detected | 822 | 14402 | - | - | [link](data/evidence/HDFS-5766/old-bug-2026-10-29-liftlab.json) |
| HDFS-10609 | hdfs-adhoc-11 | 12.638 / yes | not detected | 833 | 13714 | - | - | [link](data/evidence/HDFS-10609/old-bug-2026-10-29-liftlab.json) |
| HDFS-14075 | hdfs-adhoc-45 | 13.193 / yes | not detected | 918 | 14406 | - | - | [link](data/evidence/HDFS-14075/old-bug-2026-10-29-liftlab.json) |
| HDFS-14311 | hdfs-adhoc-24 | 42.381 / yes | not detected | 493 | 14412 | - | - | [link](data/evidence/HDFS-14311/old-bug-2026-10-29-liftlab.json) |
| HBASE-15039 | hbase-adhoc-34 | 13.748 / yes | not detected | 137 | 14469 | - | - | [link](data/evidence/HBASE-15039/old-bug-2026-10-29-liftlab.json) |
| HBASE-20642 | hbase-adhoc-04 | 26.967 / yes | detected | 46 | 2424 | 2/10, 9/10 (shape) | IOException after call#u18 on RpcServer.default.FPBQ.Fifo.handler=2,queue=0,port=port | [link](data/evidence/HBASE-20642/old-bug-2026-10-29-liftlab.json) |
| ZOOKEEPER-710 | zk-adhoc-02 | 8.63 / yes | not detected | 1072 | 14404 | - | - | [link](data/evidence/ZOOKEEPER-710/old-bug-2026-10-29-liftlab.json) |
| ZOOKEEPER-2886 | zk-adhoc-02 | 7.798 / yes | candidate, not stable | 369 | 4281 | 0/10 | IOException before doTransport#u6 on main-SendThread(127.0.0.1:port); IOException before validateSession#u11 on NIOServerCxnFactory.SelectorThread-anonymous; IOException before validateSession#u12 on NIOServerCxnFactory.SelectorThread-anonymous | [link](data/evidence/ZOOKEEPER-2886/old-bug-2026-10-29-liftlab.json) |
| SOLR-9440 | solr-adhoc-31 | 60.663 / yes | detected | 23 | 1480 | 10/10 | ConnectionLossException after writePendingUpdates#u78 on OverseerStateUpdate-id-127.0.0.1:port_solr-n_id | [link](data/evidence/SOLR-9440/old-bug-2026-10-29-liftlab.json) |
| SOLR-6101 | solr-adhoc-19 | 29.314 / no | not detected | 149 | 6152 | - | - | [link](data/evidence/SOLR-6101/old-bug-2026-10-29-liftlab.json) |
| SOLR-6197 | solr-adhoc-19 | 22.106 / no | not detected | 243 | 12833 | - | - | [link](data/evidence/SOLR-6197/old-bug-2026-10-29-liftlab.json) |

not run: HBASE-28533 (throw unreachable on today's code, GraphChecker found it so), SOLR-6763 (no tree branch). See data/old-bugs.json.

### Making the detections reproduce; the general replay fixes

A candidate's exact plan can replay below 10/10 when the decisive event is a race between equivalent actors or a
timing-dependent count, not the fault itself. Each was met with a general change to the fault **identity** (no
per-case code), committed and covered by tests; the evidence keeps the exact plan's k/10 beside any variant's:

- **Per-run identifiers in an actor name** are masked in the fault's occurrence identity (agent `OccurrenceIdentity`
  and `faults.stable_occurrence`): a run of >= 10 digits (a ZooKeeper session id in an Overseer thread name, a hash,
  a timestamp), and any trailing `-<n>` index of a thread (the JVM's `Thread-<n>`, a pool's `PEWorker-<n>`). So
  SOLR-40's and HBASE-BACKUP-LOCK's selectors match whichever equivalent thread/session is decisive.
- **One call failing on several distinct nodes has no order of its own** (`faults.concurrent_calls`): every node's
  watch for one change fires concurrently, so the plan's faults apply in any order (SOLR-40's aliases watch on
  nodes 4 and 2).
- **A lost reply is named by its ordinal among the actor's replies of that shape** (`shapeOrdinal`), not by how many
  unrelated polls the handler served first (HBASE-20642's lost `DisableTableResponse`).

With these, HBASE-BACKUP-LOCK replays 10/10 both runs and HDFS-11741, SOLR-9440 replay 10/10. HBASE-20642's exact
plan is 2/10 but its shape-ordinal plan (`crashfuzz plan --trial ... --output ...`, a general variant) is 9/10.
SOLR-40's exact plan is 4/10 (run a) / 1/10 (run b): the remaining variance is the system's own randomness (SolrJ's
unseeded `Collections.shuffle` routing a request to a node that refreshed its alias view, and which replica hosts the
next time-partition), which no fault identity controls; its siblings plan (all four nodes' first alias read failed)
is 8/10. **ZOOKEEPER-2886 is a candidate, not a detection:** the oracle fired once (trial 369) but the exact plan
replays **0/10** -- the throw needs the second old multi's `checkSession` to read `session.owner` after the takeover
thread's `REVALIDATE` set it, a thread-scheduler order CrashFuzz's fault injection cannot pin (GraphChecker held the
write on its own thread). ZOOKEEPER-710, the same mechanism, reached no candidate at all.

### Summary

Baseline (as on CloudLab): SOLR-40 and HBASE-BACKUP-LOCK detected and replay stably; ZK-ELECTION-OFFER and
HDFS-17967-A not detected. Old bugs (14 runnable): detected and stably replayed HDFS-11741 (10/10), HBASE-20642
(shape plan 9/10), SOLR-9440 (10/10); ZOOKEEPER-2886 a candidate that does not reproduce (0/10); the other ten not
detected in the budget. HBASE-28533 and SOLR-6763 were not runnable (no reachable throw / no tree). The non-detections
are consistent with each bug's mechanism: a STATE or CONFIG race the Apache release's own test never drives into the
throw with an injected I/O fault (HBASE-15039, SOLR-6101/6197, HDFS-14075/14311), or the lost-key-update interleaving
of the HDFS block-key family not reached in budget (HDFS-12931/17383/5766/10609).

## Time to detection on the baseline bugs (2026-10-26, CloudLab; the earlier run)

[`data/baseline-bugs.json`](data/baseline-bugs.json) holds the bugs both baselines are measured on, each with
its system's own unit test, unchanged. Each was run from nothing twice (Soot selection, healthy run, campaign)
with `run --stop-at-candidate` (and `--max-trials 10000 --max-seconds 14400` where it was not detected); the
time is wall clock from the case's start to the end of its first candidate trial
(`data/evidence/<case>/time-to-detect-2026-10-25.json`).

| bug | unit test | run a | run b |
| --- | --- | --- | --- |
| SOLR-40 (stale routed-alias cache after a ZooKeeper failure) | `TimeRoutedAliasUpdateProcessorTest#test` | trial 44, 2719 s | trial 37, 1999 s |
| HBase backup lock (lost compare-and-set reply) | `TestBackupManager#testStartBackupExclusiveOperation` | trial 23, 1182 s | trial 11, 783 s |
| ZooKeeper election recipe (orphaned offer) | `LeaderElectionSupportTest#testNodes3` | not in 273 trials (3523 s) | not in 271 trials (3523 s) |
| HDFS-17967 (pipeline relay to a DataNode missing the block key) | `TestEncryptedTransfer#testLongLivedClientPipelineRecovery[0]` | not in 80 + 166 trials | not in 80 + 126 trials |

Each candidate was checked against the bug's symptom: SOLR-40's runs fail the JUnit test with "Routed alias
... appears to have been removed during request processing"; the HBase runs throw the lock's
`ExclusiveOperationException` 275 and 276 times (healthy run: 2) and hang until the JUnit timeout. On the
ZooKeeper recipe the Soot selection, built from the server-side check's static neighbourhood, holds 42 I/O
calls of the server and the client library and none of the recipe's: the failing read that leaves the offer
behind is outside its fault space. HDFS-17967's first 80 trials of each run ended by the adaptive budget;
the runs given a 4-hour budget were stopped after 166 and 126 trials without a candidate.

Held-out checks: with the code unchanged, CrashFuzz also ran on three checklist rows never used while the
refactor was built (SOLR-09, HBASE-08, ZOOKEEPER-07): 120, 59 and 373 trials, no candidate, no trial failing the
check ([`data/evidence/heldout-2026-10-26.json`](data/evidence/heldout-2026-10-26.json)).

### Earlier campaigns

SOLR-40 was first found by a 240-trial Soot-selected campaign of the 102-check list at trial 31, 2102 s
after the campaign started (the whole campaign took 21292 s); see `data/evidence/SOLR-40/`. The refactored
code replays its fault strictly in all 10 replays and fails the target in 1, the run whose JUnit test fails
(`data/evidence/SOLR-40/replay-2026-10-25.json`).

**HBASE-32** (`RegionReplicaFlushHandler.triggerFlushInPrimaryRegion`) is not a detection of generic
CrashFuzz. Its Soot-selected rerun ran 80 trials (10915 s) with no candidate. The earlier candidates came
from a case-specific agent that injected flush-RPC failures (185 trials plus a supplemental 272; 34934 s of
JUnit time in all). Each one was a 360 s JUnit timeout reaching the check's rethrow, which is the documented
reaction to a `DoNotRetryIOException`. Every isolated replay of those plans passed, so the record keeps
`new_bug=false` (`data/cases/HBASE-32/`, `data/evidence/HBASE-32/`).
[`DESIGN.md`](DESIGN.md) records the campaign protocol.
