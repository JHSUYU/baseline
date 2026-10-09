# HDFS-16 independent coverage and I/O campaign

## Target and original JUnit

Hadoop HDFS 3.4.3, released `BlockInfo.java:428`, function
`BlockInfo.setGenerationStampAndVerifyReplicas(long)`:

```java
Preconditions.checkState(uc != null && !isComplete());
```

The exact target oracle is the `IllegalStateException` from this guard. An
injected `IOException`, an unrelated JUnit failure, or an exception from a
different guard does not count as a target exception or a bug. A target
exception is a candidate pending the same selector replay and source review.

The unchanged release JUnit is
`org.apache.hadoop.hdfs.TestClientProtocolForPipelineRecovery#testUpdatePipeLineAfterDNReg`.
It starts a `MiniDFSCluster` with one NameNode and two DataNodes, creates and
flushes a file, marks one DataNode dead, re-registers it, and requests two
pipeline updates. Its original execution passed in 23.493 seconds. The
independent probed run passed in 27.450 seconds. Its exact guard was reached
three times on block 1073741825: twice through
`BlockManager.updateLastBlock` (proposed generation stamps 1002 and 1003),
then through `BlockInfo.commitBlock` (proposed stamp 1003). All three healthy
outcomes were true.

## Independent recorder and feedback

`source/` contains the relevant Hadoop 3.4.3 release source-JAR members, with
hashes in `source-provenance.json`. `system-test/build_probe.py` compiles
case-local source overrides of `BlockInfo`, Hadoop IPC `Client`, and
`EditLogFileOutputStream`. The original JUnit and installed Hadoop release
JARs stay unchanged. `system-test/Probe.java` records the exact target guard
and its block ID, caller, current and proposed generation stamps, together
with observed RPC responses and durable edit-log flushes. The healthy run
observed 53 I/O points in 14 API families. JaCoCo plus
`system-test/CoverageDump.java` records HDFS production method, branch-unit,
and class-probe coverage; the original test JAR and case recorder are excluded
from selection feedback. A branch unit is a covered count at a source line,
not an identified branch outcome. No GraphChecker graph, static slice,
closure, skeleton, prewoven recorder, or Docker cluster is read.

## Campaign and resume

Each fault selector is the exact observed `(marker, API, ordinal, exception)`
tuple. The recorder applies ordered selectors only when their actual runtime
identity matches. A strict trial applies every requested fault in order. A
trial remains relevant only if the selected `BlockInfo.java:428` guard on the
same block, caller, and proposed generation stamp occurs **after the last
applied fault**; other pipeline phases cannot stand in for it. Lost-target
and unmatched trials are recorded but do not seed mutations. Runtime feedback
adds new observed I/O points and new production coverage to the queue.

The base budget is 80 trials and at most eight ordered faults per sequence.
If the last eight trials add a production method, branch unit, or stable I/O
family, the same checkpoint extends to 128 trials and ten faults. The sustained
runner is the node0 tmux session `hdfs16-independent`; each JUnit runs in its
own case-local data and port space on node1. Run or resume with:

```bash
cd /users/ZhenyuLi/baseline/crashfuzz/cases/HDFS-16/independent-coverage-io
python3 campaign/run_campaign.py
```

`campaign/checkpoint.json` holds the selected current sequence, queue, and
completed rows. Every completed trial has an atomic `trial-result.json`, its
exact plan, JUnit manifest, runtime trace, coverage, and measured duration;
`campaign/trial-ledger.csv` and `../result.json` are atomically republished
after each trial. Resume reads existing trial results and remote manifests to
avoid repeating completed executions. The oracle is checked independently
from strict fault matching, target retention, JUnit exit, and coverage gain.

After trial 12, the runner paused to rescore the existing queue. Trial 11 had
timed out at 150 seconds with only three of four requested faults applied.
`campaign/checkpoint-before-priority-v2.json` preserves the old ordering and
`campaign/priority-migration-v2.json` records the migration. The new score
uses production method and branch gain and stable I/O-family novelty, penalizes
slow parents and repeated edit-log fault families, and samples at most two
I/O points from one family in each mutation. Existing completed rows and the
already selected trial 13 remain unchanged. Future trials use a 90-second
JUnit timeout, over three times the 27.450-second healthy probed duration;
a timeout is recorded separately from the target exception oracle.

After 61 completed trials, the runner paused a second time because the next
set of setup I/O families repeatedly removed the target. It preserved the
completed rows and already selected trial 62, then added an empirical target
retention bonus to queue selection: after at least three strict trials for a
last-fault API family, a family retaining the target receives up to 30 points
and a family repeatedly losing it receives up to a 30-point penalty. This
changes only future queue ordering; all candidates remain available, with
waiting rounds preventing starvation. `campaign/retention-policy-v3.json`
records the boundary and per-family observations.

## Completed result

The 80-trial budget finished with a maximum tested sequence depth of four
faults; 56 trials requested more than one fault. The final eight trials
(73–80) added no HDFS production method or branch unit and no stable I/O
family, so the conditional 128-trial extension did not apply. The remaining
queue stays in the checkpoint for an explicitly larger future budget.

| Measure | Result |
| --- | ---: |
| Requested / matched / applied fault events | 146 / 129 / 129 |
| Strict trials (all requested faults applied in order) | 63 |
| Strict trials retaining the selected guard after the last fault | 40 |
| Strict trials losing the target / incomplete injection | 23 / 17 |
| New HDFS production methods / branch units / class probes | 18 / 50 / 156 |
| Exact target exceptions; any-context target exceptions | 0; 0 |
| JUnit nonzero exits under injected I/O; of those, timeouts | 51; 2 |
| Confirmed new bugs | 0 |
| Measured healthy plus trial active time | 3,068.560 seconds |

The 51 nonzero original-JUnit exits are workload outcomes under injected
I/O exceptions, not the selected `BlockInfo.java:428` oracle. The 40 strict
target-retaining trials reached the guard with a normal true outcome. The
selected expression is a local `BlockInfo` under-construction invariant;
RPCs and edit-log writes influence the surrounding block lifecycle, but these
trials do not establish a multi-hop ad hoc coordination failure at this site.
The active time excludes pauses between tmux sessions.

`campaign/pack_coverage.py` stores all per-trial production coverage TSVs
losslessly in `coverage-evidence.tar.gz`. `campaign/audit_case.py` verifies
the plans, traces, JUnit manifests, exact guard contexts, coverage, ledger,
and aggregate result, reading coverage directly from that archive.
