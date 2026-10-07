# HDFS-24 completed plans 101–120 archive

At the completed-plan boundary on 2026-10-07, HDFS-24 had 120 distinct
plans, 120 strict ordered injections, and 119 same-actor postfault effective
runs. The selected original `TestDFSUpgrade#testUpgrade` campaign continued
from its existing checkpoint while this completed prefix was archived.

Node1 archived all 220 regular files in the completed run directories
101–120 (173464487 original bytes). It extracted the 9879774-byte zstd tar
and verified every file size and SHA-256 before publishing the immutable
manifest. The archive SHA-256 is
`9f6b5281e39feb6ea56beceba9fa999b3a4f2dedf935f1223b6bdc57299ee56b`;
manifest SHA-256 is
`abfe51f224359653fa44f011885cb447d18207c93426bb56cb5cbea9b3b71e12`.

The tar and manifest were copied to node2 under the same isolated evidence
anchor. Node2 extracted, restored, and independently SHA-verified all 220
files. Its verification receipt SHA-256 is
`b991af8d6bd69fc0779ba6b7d68c2567351280a59bce37467ab1223907b7fea8`.
Only after receiving that receipt did node1 prune 70 verified regenerable
scratch/coverage-export files (101537570 bytes). It retained raw traces,
fault plans, JUnit logs, JaCoCo data, manifests and any candidate evidence.

The postprune independent raw audit remains `pass=true`, 120/120 strict,
119 same-actor effective, zero novel target signatures, and zero issues.
The immutable artifacts are under
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/upgrade-constructor/archives/upgrade-0101-0120.*`
on node1 and node2. The campaign checkpoint and plan queue were not reset.
