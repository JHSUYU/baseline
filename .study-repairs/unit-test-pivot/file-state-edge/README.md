# Persistent-file version edge repair for ZOOKEEPER-12

## Scope and implementation

GraphChecker worktree: `graphchecker`, branch `adhoc/persisted-file-edge-zk12`,
commit `f458270f88fb613976c9f7c36aa518daaa25ffec`, based on `3454d6210`.
Only the seven Java source/test files are committed. The two local ZK12
experiment path overrides remain uncommitted, so the code commit can be
cherry-picked without introducing this machine's absolute paths. Final
`GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar` SHA-256:
`7b764c6e3d14ba5335f659637b6587696b2f10d0a2d078f23dc319b60a344afd`.

The after-success Soot hooks record canonical real path, bounded file-content
SHA-256, size, modification time, file key, active call ID, method, source
identity and event sequence. In ZooKeeper 3.8.7 they cover normal returns of
`QuorumPeer.readLongFromFile` and `writeLongToFile`. They also cover both
direct `FileUtils.write(File, ...)` calls in the unchanged JUnit method.
The healthy weave log confirms two direct calls. A thrown/injected IOException
does not emit `FILE_WRITE_SUCCESS`.

`PersistentFileVersions` assigns a version to each **successful observed**
write to a canonical path, and joins a subsequent read only to the latest
prior write when its full post-write fingerprint matches the read fingerprint.
It maps both events to their runtime region occurrences using call IDs and
the method-call ancestry. The target-rooted demand walk crosses the resulting
edge only when the statically traced return of that read feeds a demanded
cell. Its writer row has `edgeEvidence=PERSISTED_FILE_VERSION_V1` and
`evidenceTier=EXACT`; the target occurrence remains retained. This evidence
is for the observed single-JVM execution. Hooks must be added at other
systems' actual file I/O boundaries before claiming complete file provenance
there. An unobserved same-content overwrite or overlapping same-path I/O
cannot be distinguished from the observed version by the fingerprint alone.

## Validation

`mvn -q -Dtest=PersistentFileVersionsTest test`: 3 tests, 0 failures/errors.
The fixture checks two successive versions of one path across peer-0 restarts,
a failed write that cannot become a version, an intervening peer-1 path that
must not connect to peer 0, and rejection when an unobserved change alters
the fingerprint. `mvn -q -DskipTests package` passed. `git diff --check`
passed before commit.

The unchanged original three-peer
`CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile`
passed with GraphChecker instrumentation (21-second JUnit run). The pinned
final target is `zk-peer-0#epoch2`, `QuorumPeer.loadDataBase`, source guard
line 1193 / fatal `#u62=false`; it was reached and nonfatal. The rebuilt
healthy graph has 13 exact persisted-file read-from edges, including the
previously absent peer-0 `acceptedEpoch` path:

| Run | Writer | Reader | File version | Target |
| --- | --- | --- | ---: | --- |
| Healthy | peer0 epoch1 `writeSeq=61258` | peer0 epoch2 `readSeq=101592` | 3 | reached, nonfatal |
| Four faults | peer0 epoch1 `writeSeq=82367` | peer0 epoch2 `readSeq=115497` | 3 | reached, nonfatal |

Both rows are in their respective `persistent_file_edges.jsonl` files and
their writer occurrences are `EXACT/PERSISTED_FILE_VERSION_V1` in
`concolic_region_plan.jsonl`. Two original JUnit file writes also enter the
target closure with exact file-version evidence. A cross-peer name collision
does not occur because the canonical paths differ.

## New fault trial and result

`run_new_writer_trial.py` appended **one** sequence from the newly proven
writer-side closure; the old five ZK12 trials were not rerun. The plan uses
the full `zk-peer-0#epoch1` runtime occurrence, source key, exact
`writeLongToFile` `#u11` site and hit ordinals 1–4. All four IOException
faults matched and applied (`seq=60569,69003,73455,77907`). The corresponding
method calls (`callId=60505,68985,73437,77889`) have no successful file-write
event. Retry `callId=82341` produced the first subsequent successful peer-0
`acceptedEpoch` write at seq 82367; its version feeds the final restart read
at seq 115497. The stock JUnit passed in **20.203 seconds**. The pinned target
was still reached after the fourth fault, its guard stayed nonfatal, and the
target exception was absent. This sequence gained one global branch-outcome
pair relative to this healthy run and no new method. It is an additional
negative *observation*, not a bug-negative verdict for the check.

The six total ZK12 trials now have 12/12 matched and applied faults; five
retained the pinned target, one lost it, and none triggered the target
exception. ZK12 remains **pending** for additional closure-guided fault
families and budget. `../cases/ZOOKEEPER-12/result.json` and `trials.json`
contain machine-readable results and measured times. The old case elapsed
time remains a separate checkpoint; this repair's timing is recorded
separately. `artifact-manifest.json` verifies both healthy and trial trace
streams; duplicate raw files were removed after SHA-256 verification. Restore
only a needed stream with `gzip -dk <path>.jsonl.gz` for reaggregation.

## Integration note

Cherry-pick the single commit above into the ZooKeeper system branch. The
likely merge locations are `GraphCheckerMain`, `ZooKeeperWeave`,
`CausynthTraceRecorder`, and `RuntimeSelectedRegionFinalizer` if that branch
has changed them since `3454d6210`. The ZooKeeper hook asserts the existing
`readLongFromFile(String)` and `writeLongToFile(String,long)` signatures;
recheck that assertion on other ZooKeeper versions. The common file-version
resolver and closure join do not automatically instrument HDFS, HBase, or
Solr; each system still needs successful read/write hooks at its relevant
application file boundaries.
