# Fixed-count service-loop evidence index

The frozen HBASE-15 r0000 original Recorder remained in
`StaticProgram.serviceLoopCandidate` after about ten minutes. Its captured
RUNNABLE stack is
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-15-20261014-native-v5/r0000-service-loop-jstack-0447utc.txt`
(SHA-256 `f3e3232ee32a202c776e5ba3e86217e22a28ea206789a9d11580cc4764ff8786`).
The stack runs from `LinkedTreeMap.get` through `serviceLoopCandidate`,
`serviceLoops`, `loopBodyRoot`, and `RuntimeSelectedRegionFinalizer`.
The frozen skeleton input has 6,517 regions, 40,855 fixed-count retained loops,
and up to 604 retained loops in a single region. Before this change, every
fixed-count loop scanned every graph edge in its region and owner method.

For each region and owner method, `serviceLoops` now builds an ordered set of
unit positions that can qualify a fixed-count loop: a declared-field heap
write, a call to a port definition outside that port's frame method, or a
direct port definition in the owner. A loop queries the first position at or
after its header and applies the original `loopContains` rule to that position.
The evidence set is local to one `serviceLoops` call; condition-bounded loops,
the frame-method exclusion, and the retained-loop result order are unchanged.
This changes repeated edge scans into one edge scan per region and owner plus
one logarithmic lookup per fixed-count loop.

`mvn -q test package` passed in the isolated worktree. The focused
`StaticProgramServiceLoopEvidenceTest` compares the index against the former
scan across overlapping loops, direct and called ports, frame exclusions,
dynamic dispatch, field writes, malformed loop IDs, and duplicate graph rows.

The candidate JAR replayed the frozen HBASE-02 r0000 Recorder command to an
isolated output directory. It exited 0; both files match the frozen originals
byte for byte:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `region_skeletons.jsonl` | 31,228,571 | `faf22d0240eee9e06326d4504adf78336542d3b431ce84645bee34fa69c79785` |
| `concolic_region_plan.jsonl` | 50,385,166 | `50cb9def12b58f4dca41a1b6a2d8f7bfee7048152b1a424805943b9be07044ff` |

Replay command, JAR, output, and receipt are in
`/proj/silentfailure-PG0/ZhenyuLi/mallory-service-loop-equivalence/hbase02-r0000/`.
This equality establishes output equivalence for that frozen trial. Its
168.718-second runtime was under concurrent node load, so it is not a
controlled speedup measurement. No campaign engine pin was changed.
