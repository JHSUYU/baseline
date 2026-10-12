# ZOOKEEPER-11 next bounded admission

The existing three-peer
`CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile`
reaches the exact `QuorumPeer.loadDataBase()@1169:branch:2` guard on a named
peer without taking the selected line-1175 `IOException`. The test source is
unchanged in the immutable clone
`/users/ZhenyuLi/.mallory-worktrees/zookeeper-zk11-clean-v2-lane2`;
`zookeeper-3.8.7-zk11-clean-v2-overlay.json` pins its source and compiled
bytes, with SHA-256 `17a5e2be07f19c24a288eced66e72569c7d3f68db209fc994bc807f72507b611`.

The older opt-in 5a healthy trace observed `currentEpoch` file I/O before
the target in the same named occurrence. Its six-fault pilot did not prove an
affected-actor continuation: the direct file-read exception prevented the
guard, and other later checks belonged to different occurrences. That
campaign remains negative evidence, not a completed high-quality check.
Source review confirms `QuorumPeer.start()` calls `loadDataBase()` before
quorum networking. The existing test writes a stale `currentEpoch` and a
valid `currentEpoch.tmp`; the guard is taken and recovers through the temp
file. An exception on the initial `currentEpoch` read aborts startup before
the guard, so quorum I/O or a later peer's guard cannot substitute for a
same-attempt fault-to-check path.

`prepare_zk11_scoped_healthy.py` created the fresh calibration-only config
`cases/ZOOKEEPER-11-fa5f-scoped-healthy.json` (SHA-256
`45c6ed582fdd50b6fdaa455ecced93b9bc31593122270ceff48ed1e31a0fc617`).
It pins scoped-root agent JAR SHA-256
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`
and immutable event-time core release
`fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f`.
It enables `reject_coarse_roots` and `require_event_time_paths`, retaining
the opt-in exact local timeline rule for the source-relevant file read.

## Fresh result

The pinned healthy run completed in 39.922 seconds: existing JUnit 1/1 passed,
loaded `QuorumPeer.class` SHA-256 matched `446279eb1dfd...`, and the exact
nonthrowing guard ran on `zk0` epoch 2. The fa5f audit passed with one
`observed_local_timeline` door, `readLongFromFile@2190` event 793 followed by
the selected guard event 794 in the same occurrence and JVM thread; it found
zero observed graph-path doors.

The bounded one-fault pilot injected `IOException` at that exact door on
`zk0` epoch 2 (fault event 734). The guard did not run afterward. Its result
is `target_lost`, with 1/1 strict injection, zero retained target trials and
zero target throws in 101.329 seconds; offline gate failed. Source confirms
that the general `IOException` leaves `loadDataBase` through its outer catch
before the epoch comparison. The existing test supplies a valid temp epoch
file and does not restart again after the selected recovery. No full budget
was launched. The source and SHA-bound trace receipt is
`data/mallory/admissions/ZOOKEEPER-11-fa5f-fault-model-target-lost.json`
(SHA-256 `fa47f1854b7d9810d3c4c3c7fe1f8d947ed9f2cf6f7750d5b14ddeb8c95e0837`).
