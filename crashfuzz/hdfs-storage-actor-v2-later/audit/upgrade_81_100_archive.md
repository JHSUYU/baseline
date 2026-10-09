# HDFS-24 upgrade runs 81–100 archive

The node1 original `TestDFSUpgrade#testUpgrade` campaign had completed 100
distinct plans and 99 actor-qualified effective trials when completed runs
81–100 were archived. The immutable archive contains 220 files (173,279,422
raw bytes), each recorded with SHA-256. Local extraction verified every file;
node2 independently extracted, restored, and verified all 220 files. Only
after node2's receipt returned did node1 prune 50 verified regenerable
exports (72,494,962 bytes). Raw traces, fault plans, original JUnit logs,
JaCoCo, manifests, and target-throw evidence remain. The post-prune
independent checkpoint audit passed at 100/100 strict plans, 99 effective,
zero novel target exception signatures, and no identity issue.

| Artifact | SHA-256 |
| --- | --- |
| node1 manifest `upgrade-0081-0100.manifest.json` | `b63d5284ccda1727707445620dc8c331f438e9afffc89c0ee310ce2e98cb5b48` |
| node2 mirror archive `upgrade-0081-0100.tar.zst` | `75d885709997cfcf3014ed95693083586cbc5577c6b99bf1d3ed5efb26c44d0e` |
| node2 verified receipt | `1daa0738dad94fbcbeaf94e0d27658449d68a86c17fe5c07fdf057fe1dc7f4b0` |

Authoritative node1 path:
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/upgrade-constructor/archives/`.
The same relative path and restored raw files are mirrored in the isolated
node2 image.
