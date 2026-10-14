# HBASE-02 r0002 original Recorder profile

The CLOSED r0002 trace and static artifacts are frozen under
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-02-20261014-native-v1/`.
The exact original Recorder argument array is
`campaign/trials/r0002/original-graph/recorder-command.json` there. Its first
classpath entry is the immutable engine JAR with SHA-256
`5fbd163d6af04955ee011da65b889b5df35ea4fed697e5fcfe2c5ad885c3894d`.
Each replay kept the same JDK 8, `-Xmx8192m`, loop bound, trace, static inputs,
test and target occurrence. Only the output directory changed for the old
replays; the optimized replay also replaced the first classpath entry with
this worktree's compiled classes.

Commands, stdout/stderr, 141 RUNNABLE application-stack samples, and result
receipts are in
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/recorder-profile-r0002-20261014/`.
`recorder-command.json` is the sampled old replay;
`old-unsampled-command.json` is the comparable old replay;
`optimized-command.json` is the indexed replay. These commands only write to
their own `/dev/shm/mallory-hbase02-r0002-*-v1/` output directories.
The indexed output was copied and SHA-verified into the evidence directory's
`optimized-recorded/` subdirectory for durable review.

## Where the old Recorder spends time

The sampled old Recorder exited 0 after 440.884 seconds. Stack collection
pauses the JVM, so this wall time is not comparable with an unsampled run.
The top application frame among 141 RUNNABLE observations was:

| Source path under `vendor/src/main/java/edu/uva/liftlab/graphchecker/` | Observations | Caller and cause |
| --- | ---: | --- |
| `plan/StaticScopeMap.java:1564` (`ofRole`) | 42 | All called by `declaredSitesAt` at line 1754; scans all sites per activation capture. |
| `causynth/StaticProgram.java:460` (`serviceLoopCandidate`) | 25 | Called by `serviceLoops`; scans all region edges for each retained loop. |
| `causynth/RuntimeSelectedRegionFinalizer.java:1935-1941` (`callReturnValueCells`) | 20 | Scans candidate edges for each call-return port. |
| `causynth/RuntimeSelectedRegionFinalizer.java:2363-2372` (`RegionDemandIndex.edgesInto`) | 26 | Traverses incoming cell edges in the closure. |

These are stack observations, not measured CPU-time percentages. The phases
appear in the same order during this replay: input read (0-60 s), service
loop classification (60-150 s), call-return matching (roughly 120-210 s),
closure edges (roughly 180-300 s), and declared-site lookup (roughly
300-440 s). The source lines above refer to the exact old engine source at
`/proj/silentfailure-PG0/ZhenyuLi/mallory-hbase-native-original/engine-opt/vendor/src/main/java/`.

## Ordered region-and-method index

`StaticProgram.regionGraphInMethod` lazily groups each region's existing
`edgesByRegion` rows by their recorded `method`. It preserves row identity,
source order, and duplicates. `serviceLoopCandidate` reads only the group for
its loop owner, with the original `loopContains`, HEAP_WRITE and port checks
unchanged. The focused `StaticProgramRegionMethodIndexTest` compares indexed
results with the old filter across overlapping regions, methods, and repeated
rows. The earlier `StaticScopeMap.declaredSitesAt` index is also present in
this branch, so the full replay measures their combined effect.

The full original-engine Maven test suite passed with `mvn -q test` (13 tests,
0 failures, 0 errors, 0 skipped). The optimized Recorder exited 0 in
**184.817 seconds** without stack sampling. An independent old-engine replay
without stack sampling also exited 0, in **329.682 seconds**. The old replay
ran later under heavy concurrent host load (load average about 15), so the
two isolated wall times must not be read as a controlled speedup ratio.
The old campaign's `analysis_elapsed_seconds=237.957` includes target
resolution and summary work, so it is not a Recorder-only comparator. File
timestamps in the frozen campaign put the old Recorder command at
19:03:35.792 and its completed stdout at 19:06:53.951, about 198 seconds;
this gives a second, load-dependent old-Recorder observation. Across these
three runs the indexed engine is faster, but only the byte-identical outputs
are a strict equivalence result. The saved command files have SHA-256
`24eb79661e6ae1d42baab8da7c0fd0f4bf6d56ad843c4784f9e8d7877bd8ce01`
(sampled old),
`cc727961fdbd09e2548b5664729bb0236a3c872df950a08e415b7fca677c31c9`
(unsampled old), and
`21c268c8ab1f38f92fe02849c9b84730884de8f028f560c54a6abccf21c36fda`
(optimized), respectively.

| Output | Bytes | SHA-256, frozen old = sampled old = unsampled old = optimized |
| --- | ---: | --- |
| `region_skeletons.jsonl` | 31,308,722 | `48fc3042326d4b9c0e0248f414b2af8999c352ecbd84f8577c835ade708dddd2` |
| `concolic_region_plan.jsonl` | 51,517,239 | `649b773a3df43a0e85b141904a772747ee5df1f2dc4df1fa3c319f81eaee7a38` |

This is one frozen HBase trial and one host with concurrent experiments. It
establishes byte-identical Recorder output, and its timing does not establish
a universal speedup across systems or trials. Active campaign pins were not
changed.
