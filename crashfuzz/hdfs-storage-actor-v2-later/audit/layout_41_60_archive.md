# HDFS-27 layout runs 41–60 archive

The node2 original `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout`
campaign completed 60 distinct plans, with 59 HDFS-27 effective trials. Only
completed runs 41–60 were archived. Their 220 files totalled 133,765,919
raw bytes and each was recorded with SHA-256. The compressed archive was
extracted and verified locally, then copied to node1, where all 220 files
were independently extracted, restored, and verified again. After node1's
receipt returned, node2 pruned 100 verified regenerable exports
(126,787,805 bytes). Raw trace, fault plan, original JUnit log, JaCoCo,
manifest, and target-throw evidence remain. The post-prune independent raw
audit passed at 60/60 exact plans, 59 effective, zero novel target exception
signatures, and no identity issue.

| Artifact | SHA-256 |
| --- | --- |
| node2 manifest `layout-0041-0060.manifest.json` | `026d99c3b1a1d00238a745740c740e921c3042ad8d5c3965fa978121e2f6ce68` |
| node1 mirror archive `layout-0041-0060.tar.zst` | `83fc3d232d907bd673eec6fe1bb5c8fd5eaa2445ecae56e12f9523b2ad92b254` |
| node1 verified receipt | `6807686960952a4c1bad17a0e6c2a020f8d5cfe5900b4a1224c2b7bd18c9f0c0` |

Authoritative node2 path:
`/users/ZhenyuLi/hdfs-storage-v2-layout-isolated-20261007/evidence/layout-upgrade-constructor/archives/`.
The same relative path and restored raw files are mirrored on node1.
