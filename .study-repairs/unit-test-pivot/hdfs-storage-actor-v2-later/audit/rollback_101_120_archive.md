# HDFS-26/37 rollback runs 101–120 archive

At the complete checkpoint for plan 120, the node2 shared original-JUnit
campaign had 60 HDFS-26 and 59 HDFS-37 effective trials. The archive contains
only the immutable completed runs 101–120. It records per-file SHA-256 for
220 files (174,238,870 raw bytes); local extraction verified every file.
The archive and manifest were copied to node1, where all 220 files were
independently extracted, restored, and SHA-verified. Only after the node1
receipt returned did node2 prune 60 verified regenerable exports
(86,890,653 bytes). Raw trace, fault plan, original JUnit log, JaCoCo,
manifest, and target-throw evidence remain available. The post-prune raw
checkpoint audit passed at 120/120 exact sequences, zero actor issues,
zero novel target exception signatures.

| Artifact | SHA-256 |
| --- | --- |
| node2 manifest `rollback-0101-0120.manifest.json` | `6921c10a0192ea547d7f883b91ed9e6d3c5b1b104cfa20c6709270e32da70428` |
| node1 mirror archive `rollback-0101-0120.tar.zst` | `33e38251f39f5d603ba35ce5832e5f7593408045151c63e6fffa2947c5d41cec` |
| node1 verified receipt | `392ed27745bb977641473de339104a9b0cb51f269773bf69011a7078b1f85c17` |

Authoritative node2 path:
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor/archives/`.
The same relative path and restored raw files are mirrored in the isolated
node1 image.
