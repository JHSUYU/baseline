# HDFS-26/37 rollback runs 81–100 archive

The node2 campaign completed its first 100 distinct original-JUnit fault
plans, with HDFS-26 49 and HDFS-37 50 effective. Only immutable completed runs
81–100 were archived; the in-flight run was excluded. `archive_completed.py`
recorded a SHA-256 for each of 220 files (173,991,727 raw bytes), compressed
them, extracted and compared every file, and verified the archive locally.
The archive and manifest were mirrored to node1, where all 220 files were
independently extracted, restored, and verified. After the node1 receipt was
returned to node2, `prune` removed only 50 verified regenerable coverage and
scratch files (72,310,916 bytes) from runs without target throws. Raw trace,
fault plan, original JUnit log, JaCoCo, manifests, and any candidate run
remain on node2. The post-prune raw audit passed at 100/100 strict, zero
identity issues; neither plan order nor effective counts changed.

| Artifact | SHA-256 |
|---|---|
| node2 manifest `rollback-0081-0100.manifest.json` | `b232b02bbd3908ed87c08cbbeefec031fa34e9341b5f9f4a1d9c37c0b777729a` |
| mirrored archive `rollback-0081-0100.tar.zst` | `067175f0f82d1e3828148f39d516a4dad415356139dadfd839729c3833759df7` |
| node1 verified receipt | `d584b54bcd00d6d89cd6fe094fcc3370d1bdbe36d39749434747f15224c50699` |

Authoritative path:
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor/archives/`
on node2, with the same relative path mirrored under the isolated image on
node1.
