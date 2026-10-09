# HDFS-26/37 rollback runs 61–80 archive

While the original shared `TestDFSRollback#testRollback` campaign continued on node2, only completed sequences 61–80 were selected. The in-flight sequence was excluded. `archive_completed.py prepare` recorded SHA-256 for all 220 files (174,150,807 bytes), compressed them into an immutable `rollback-0061-0080.tar.zst`, extracted and checked every file, then published the manifest. Local `verify` passed. The archive and manifest were mirrored to node1; node1 extracted and independently verified all 220 files, restored the mirror, and returned its verification receipt to node2. Only then did `prune` remove 60 verified regenerable coverage/scratch files (86,858,301 bytes) from runs with no target throw; raw trace, original JUnit log, JaCoCo, fault plan, manifests, and candidate runs remain locally. Node2 `audit_checkpoint.py` passed after pruning at 81 completed, 40 effective for each check, zero issues.

| Artifact | SHA-256 |
|---|---|
| node2 manifest `rollback-0061-0080.manifest.json` | `aff70146491da60348e93b1922a4e95f36ebbdb69f1cdece14547073589c2c5e` |
| mirrored archive `rollback-0061-0080.tar.zst` | `50eabe33de1e05fb300652514fe41b32b120c85c30526cd7fe86467890ac0ef9` |
| node1 verified receipt | `e5bee8d8ad7c64e0e7590b6b317223126caae87979e9afb22628d3b40345a7a3` |

The authoritative node2 archive directory is `/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor/archives/`. The node1 mirror uses the same relative path under its isolated image. The completed checkpoint and all trial counts were unchanged by archiving.
