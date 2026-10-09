# HDFS-26/37 rollback runs 121–140 archive

The node2 original `TestDFSRollback#testRollback` shared campaign had
completed 140 distinct plans, with 70 HDFS-26 and 69 HDFS-37 actor-qualified
effective trials, when completed runs 121–140 were archived. The immutable
archive contains 220 files (174,231,755 raw bytes), each recorded with
SHA-256. Local extraction verified every file; node1 independently extracted,
restored, and verified all 220 files. Only after node1's receipt returned did
node2 prune 60 verified regenerable exports (86,848,608 bytes). Raw traces,
fault plans, original JUnit logs, JaCoCo, manifests, and target-throw
evidence remain. The post-prune independent checkpoint audit passed at
140/140 strict plans, 70/69 effective, zero novel target exception signatures,
and no identity issue.

| Artifact | SHA-256 |
| --- | --- |
| node2 manifest `rollback-0121-0140.manifest.json` | `19915e56dc66f719e2528d8809448a7a6b5d92d0793c0bfb7ee4b634a85fc4b2` |
| node1 mirror archive `rollback-0121-0140.tar.zst` | `359fa9134e210e5154cccc139917cb63604c0c74323376f2e9b97e9a92231a30` |
| node1 verified receipt | `543b559359b095966cbd2ffe061eddfb891f1616b72f8da664733500288aec8c` |

Authoritative node2 path:
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor/archives/`.
The same relative path and restored raw files are mirrored in the isolated
node1 image.
