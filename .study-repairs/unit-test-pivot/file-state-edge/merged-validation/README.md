# ZK12 merged ZooKeeper build compatibility check

This is a separate, fault-free run of the unchanged ZooKeeper 3.8.7 JUnit
`CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile`
with the ZooKeeper common-branch build at `4d87a7c24` after combining the
ACKEPOCH and persisted-file hooks. It does not repeat or alter any of the six
fault trials. The read-only JAR was
`/users/ZhenyuLi/.graphchecker-builds/unit-test-zookeeper-4d87a7c24c-28d298f0e310.jar`,
SHA-256 `28d298f0e310e88ee1e685e76bf7bfa5cfece8bb79099f068a509cb293e571c6`.
All output and the temporary case declaration are isolated under this
directory (the declaration is under the ZK12 repair GraphChecker worktree).

The merged static slice succeeded in 28.987 seconds. Its weave log states
that `LEADERINFO` and `ACKEPOCH` write/read hooks, epoch-file read/write
hooks and two direct JUnit `FileUtils.write` hooks were woven together. The
original JUnit recording passed in 20 seconds and activated the target.
Its trace contains six matched `ZOOKEEPER_QUORUM_TCP_ACKEPOCH` sends and six
receives, plus 27 `FILE_WRITE_SUCCESS` and 13 `FILE_READ_SUCCESS` events.

Using that same JAR, `reaggregate.py` pinned the final
`zk-peer-0#epoch2` target occurrence. `final-target-summary.json` reports
one activated occurrence and zero fatal occurrences. The target closure
still contains the exact peer-0 cross-restart file edge: epoch-1 successful
`acceptedEpoch` write seq **60793** to epoch-2 read seq **93550**, version
3. The writer row has `evidenceTier=EXACT` and
`edgeEvidence=PERSISTED_FILE_VERSION_V1`; 13 persisted-file read-from
edges were resolved. This confirms the two merged hook families coexist in
the stock workload. It is not an injected-fault result or a new bug claim.

The full runtime and schedule streams are compressed as `.jsonl.gz`. Their
uncompressed and compressed SHA-256 hashes and sizes are in
`artifact-manifest.json`; each decompressed stream was verified before the
duplicate raw file was removed.
