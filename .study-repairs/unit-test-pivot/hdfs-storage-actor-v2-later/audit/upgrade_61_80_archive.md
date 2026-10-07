# HDFS-24 upgrade runs 61–80 archive

The node1 original `TestDFSUpgrade#testUpgrade` campaign had completed 89
distinct plans and 88 actor-qualified effective trials when its immutable
completed runs 61–80 were archived. The archive holds 220 files
(172,604,145 raw bytes), each recorded with SHA-256. Local extraction
verified every file; node2 independently extracted, restored, and verified
all 220 files. Only after node2's receipt returned did node1 prune 85
verified regenerable exports (123,162,719 bytes). Raw trace, fault plan,
original JUnit log, JaCoCo, manifest, and target-throw evidence remain.
Post-prune independent raw audit passed at 89/89 strict plans, 88 effective,
zero novel target exception signatures, and no identity issue.

| Artifact | SHA-256 |
| --- | --- |
| node1 manifest `upgrade-0061-0080.manifest.json` | `ac325556d7dc47d68014161f6217b621be143252aa421d4dbeeed45323cf8c2b` |
| node2 mirror archive `upgrade-0061-0080.tar.zst` | `f6bb21f235dfa4e9c6f4465626b51d579a813b03e823b36861e5b8cbbc5b3607` |
| node2 verified receipt | `a7e5f862e17c8c43a0ef773113c3673742e776ead0dc9d6ed9dbd7bc6768a8fa` |

Authoritative node1 path:
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/upgrade-constructor/archives/`.
The same relative path and restored raw files are mirrored in the isolated
node2 image.
