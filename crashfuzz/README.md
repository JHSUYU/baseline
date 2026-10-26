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
| `crashfuzz/` | the Python package (stdlib only): `trace`, `faults`, `oracle`, `scheduler`, `campaign`, `selection`, `runners/`, `worker`, `cluster`, `report`, `settings`, `systems` |
| `crashfuzz/runners/` | one module per system running one unchanged JUnit method under the agent; the JUnit 4 and Jupiter launchers (`java/`) and HBase's test-only SSL utility |
| `runtime-agent/`, `static-selection/` | the Java agent and the Soot selector (Maven) |
| `systems/hdfs/` | the HDFS RPC wire mapping the selector follows |
| `scripts/setup-deps.sh` | the Apache releases and sources, verified, in the expected layout |
| `tests/` | `python3 -m unittest discover -s crashfuzz/tests` (from the repository root) |
| `data/` | the 102-check selection, the campaign records and the source reviews |
| `vendor/` | the JUnit Platform launcher the Jupiter runner uses |

## Setup

Paths come from the environment (`crashfuzz/settings.py`); the defaults are
the CloudLab cluster's, where `/bulk` is NFS-shared by every node:

| variable | default | what |
| --- | --- | --- |
| `CRASHFUZZ_DEPS` | `/bulk/baseline-deps` | release binaries; `sources/` beside them |
| `CRASHFUZZ_RESULTS` | `/bulk/crashfuzz-results` | results root |
| `CRASHFUZZ_JAVA_HOME` | `/usr/lib/jvm/java-8-openjdk-amd64` | the JDK every JUnit runs on |
| `CRASHFUZZ_M2` | `~/.m2/repository` | test-only jars (bouncycastle, minikdc, JaCoCo, ...) |
| `CRASHFUZZ_BUILD` | `crashfuzz/build` | compiled launchers, unpacked test jars |

```sh
crashfuzz/scripts/setup-deps.sh      # downloads, verifies, unpacks; builds the ZooKeeper tree,
                                     # the agent and the selector
python3 -m unittest discover -s crashfuzz/tests
```

## Run

From `crashfuzz/` (the package directory's parent):

```sh
python3 -m crashfuzz run --case-id SOLR-40                   # one case, end to end, resumable
python3 -m crashfuzz worker --system HBase                   # every HBase case
python3 -m crashfuzz cluster --nodes node0 node1 node2 node3 node4 --system Solr -- --max-trials 240
python3 -m crashfuzz replay --case-id SOLR-40 --plan plan.json --repeats 10 --name aliases
python3 -m crashfuzz report --output /bulk/crashfuzz-results/table.tsv
```

`cluster` starts one detached worker per node over ssh, in this checkout's
`crashfuzz/` directory: the repository must be at the same path on every node
(on CloudLab a clone under `/bulk`; each node's home directory is its own).
Node `i` of `N` takes every `N`-th case of the system. A case's flock and
heartbeated lease keep two workers from running it at once, and a restarted
worker resumes unfinished cases without rerunning finished trials. `replay` runs one fault sequence (a
JSON list of fault points, or a trial's `fault-trial.json`) a number of times
on the case's selection and healthy run, through the same matching and oracle.

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

## Time to detection on the baseline bugs (2026-10-26, CloudLab)

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
