# ZOOKEEPER-12: accepted epoch versus current epoch

This case uses the unchanged ZooKeeper 3.8.7 JUnit method
`CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile`.
It starts three in-JVM quorum peers, writes data, restarts them, replaces
peer 0's `currentEpoch` with the prior value and supplies the current value
in `currentEpoch.tmp`, then restarts and checks that peer 0 serves requests.
The native run passed: 1 test, 0 failures/errors/skips (16.672 seconds for
the test; 39.873 seconds including this isolated Maven build).

## Target and healthy graph

The selected source location is
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java:1197`,
inside `QuorumPeer.loadDataBase()`. The actual guard is line 1193,
`acceptedEpoch < currentEpoch`; `new IOException` starts at line 1194.
GraphChecker resolves the throw to `#u76` and the fatal guard to `#u62=false`.
The untouched JUnit exercises the guard nine times, all with the nonfatal
outcome `#u62=true`. Its final restarted peer-0 call is pinned in
`final-target-occurrence.txt` and `final-target-summary.json`, rather than
selecting the first startup call by default. The final peer-0 epoch reads
return 1 (`currentEpoch`), 2 (`currentEpoch.tmp`), and 2 (`acceptedEpoch`),
respectively, in the healthy trace.

The static slice and JUnit recording use this case's separate ZooKeeper and
GraphChecker worktrees. `run/final-target/runtime/concolic_region_plan.jsonl`
has an explicit `EXACT/TARGET` occurrence for the pinned failure target and
two `CANDIDATE/SHARED_LOCATION_DEMAND_V1` regions, with no `BLOCKING` gap.
All three rows say `edgeEvidence=UNAVAILABLE`. In particular, the plan has
no exact persisted-file read-from edge from the earlier peer-0
`setAcceptedEpoch() → writeLongToFile(acceptedEpoch)` to the final peer-0
`readLongFromFile(acceptedEpoch)`. Those methods execute in different peer
lifetimes. The original test's two `FileUtils.write` calls also mutate the
`currentEpoch` files outside the current production file-door trace. The
observed three-region membership therefore does not prove the complete
causal predecessor set for the selected target.

## Fault trials

`run_trial.py` takes the exact `FAULT_POINT_OBSERVED` marker, site, full
occurrence address, peer source key, and hit ordinal from the prior run.
`ExceptionTrialController` records each match and applied IOException. The
target oracle is the *same pinned peer-0 final restart* guard after the last
fault. A JUnit failure alone is not counted as this coordination exception.

| Trial | Fault sequence | JUnit | Time (s) | Applied | Pinned guard after fault | New global branch outcomes vs healthy |
| --- | --- | --- | ---: | ---: | --- | ---: |
| `other_peer_final_accepted_read` | peer 2 final accepted-epoch READ | pass | 52.451 | 1/1 | true, nonfatal | 3 |
| `target_peer_accepted_read` | peer 0 final accepted-epoch READ | fail | 80.502 | 1/1 | absent; discarded | 1 |
| `earlier_target_peer_accepted_write` | peer 0 preceding start accepted-epoch WRITE | pass | 18.185 | 1/1 | true, nonfatal | 15 |
| `double_accepted_writes` | preceding WRITE, then its newly exposed retry WRITE | pass | 20.215 | 2/2 | true, nonfatal | 15 |
| `triple_accepted_writes` | preceding WRITE and two subsequent retry WRITEs | pass | 22.257 | 3/3 | true, nonfatal | 26 |

Only the peer-0 final READ lies inside the currently proven target occurrence;
it aborts `loadDataBase()` before the guard, so it is a strict injection with
`lost_target`. The other four are exploratory, source-relevant trials. The
first accepted-epoch WRITE fault exposes a new WRITE on the same full
occurrence and a changed retry branch; the two-fault and three-fault sequences
use those newly observed I/O points. For all four target-retaining trials,
the union gains 30 global branch-outcome pairs, two branch-outcome pairs in
the target skeleton's methods plus epoch file methods, and one method over
the healthy run. The final GraphChecker aggregates for the one-fault and
three-fault target-retaining runs each preserve the exact target and have no
`BLOCKING` gaps. They still lack the persisted-file edge.

ZooKeeper writes the `acceptedEpoch` file before assigning its in-memory
field in `setAcceptedEpoch()` (QuorumPeer.java:2243-2246). The injected
pre-constructor IOException prevents that write and causes the follower to
retry. The final target peer's three file reads still return 1, 2, 2 after
the three-fault sequence, and the guard stays nonfatal. The strict final
READ fault instead makes peer 0 fail to start and the original JUnit fail its
server-up assertion; the selected guard never runs after that fault. No run
contains the selected “accepted epoch ... less than the current epoch”
exception. No new bug is confirmed.

This section records the original five-trial checkpoint: its graph did not
connect accepted-epoch state across restarts. The later persisted-file
repair and sixth trial are recorded below. The experiments can resume from
the recorded selector plans and traces. `result.json` and each
`trials/*/summary.json` record timing, match counts, target reach, and
branch feedback.

The completed raw runtime and schedule streams are archived as `.jsonl.gz`
to keep this isolated case small. `artifact-manifest.json` records each
stream's original size and SHA-256, plus its compressed size and SHA-256.
To run `run_trial.py` again or reaggregate from a recorded trace, restore
the required raw stream with `gzip -dk <path>.jsonl.gz`; retain the archive
so the manifest remains verifiable.

## Persisted-file repair and sixth trial

The isolated [repair report](../../file-state-edge/README.md) describes
GraphChecker commit `f458270f88fb613976c9f7c36aa518daaa25ffec` and
its three passing version-edge fixtures. The unchanged original JUnit passed
again (21 seconds). The repaired healthy graph now joins peer-0 epoch-1
`acceptedEpoch` write seq 61258 to its final epoch-2 read seq 101592 as a
version-3 `EXACT/PERSISTED_FILE_VERSION_V1` edge. The JUnit's two direct
`FileUtils.write` calls are also represented. The old five trials were not
rerun.

One new four-fault sequence targeted that proven writer-side occurrence.
All 4/4 IOException faults matched and applied. Each failed call lacks a
successful write-version event; a later retry did write the file, and the
final restart read consumed its observed version. The stock JUnit passed in
20.203 seconds and the pinned guard was reached after the fourth fault,
still nonfatal. Across six trials, 12/12 faults matched and applied, five
trials retained the target, and no target exception appeared. This case
remains pending for further closure-guided fault families; these observations
do not establish that the check cannot fail.

The later [merged-build check](../../file-state-edge/merged-validation/README.md)
reran the same original JUnit without faults using the ZooKeeper common
branch JAR that combines ACKEPOCH and persisted-file hooks. It passed in 20
seconds. Six ACKEPOCH sends and six receives were traced; the peer-0
accepted-epoch cross-restart file edge and exact target closure remained
present. This compatibility check adds no fault trial to the six above.
