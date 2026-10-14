# Region demand index memory reduction

The frozen HBASE-15 r0000 v6 replay used the service-loop-optimized original
engine and passed `StaticProgram.serviceLoopCandidate`. It then failed at
`RuntimeSelectedRegionFinalizer.RegionDemandIndex.add` with
`OutOfMemoryError: GC overhead limit exceeded` after 666.703 seconds under
`-Xmx16384m`. Its maximum RSS was 17,581,240 KiB. A captured GC sample had
Eden and Old both at 100%, with 38 full collections totaling 165.760 seconds.
The command/input hashes and terminal status are in
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-15-20261014-native-v6/receipt.json`;
the stack and GC sample are beside it.

The old index built `(region, destination cell) -> source cell -> edge methods`
for every graph edge in every selected skeleton holding its method. On broad
region sets, that repeats graph adjacency across many regions and creates a
large number of composite string keys, maps, sets, and nodes. The new index
stores graph row references once by destination cell, in graph order. A demand
query checks its performed regions and observed methods against the skeletons.
For each region it keeps source insertion order from the first edge in that
region, even if a later edge is the one whose method ran. This preserves the
old closure order and folded-region order. Results retain the existing bounded
8,192-entry lookup caches.

`RegionDemandIncomingOrderTest` covers shared graph edges across overlapping
skeletons, first-source order before observed-method filtering, folded-region
order, guard-only adjacency, duplicate rows, and an unselected region. The
full `mvn -q test package` suite passed in the isolated worktree.

The candidate JAR replayed the frozen HBASE-02 r0000 command to
`/proj/silentfailure-PG0/ZhenyuLi/mallory-demand-index-equivalence/hbase02-r0000/`.
It exited 0 and both artifacts matched the originals byte for byte:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `region_skeletons.jsonl` | 31,228,571 | `faf22d0240eee9e06326d4504adf78336542d3b431ce84645bee34fa69c79785` |
| `concolic_region_plan.jsonl` | 50,385,166 | `50cb9def12b58f4dca41a1b6a2d8f7bfee7048152b1a424805943b9be07044ff` |

The replay took 84.752 seconds with maximum RSS 5,818,364 KiB. These host
measurements are not a controlled speed or memory comparison. The HBASE-15
memory effect requires a separate frozen replay after its resource gate. No
active campaign pin was changed.
