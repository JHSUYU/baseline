# HDFS-32 raw-run receipt

`raw-run-sha256-receipt.json` records SHA-256 and byte length for raw artifacts under `/users/ZhenyuLi/hdfs32-independent-runs`: `healthy-02` and `trial-001` through `trial-080`. All 81 directories have `run.json`, `events.tsv`, `junit.log`, and `jacoco.exec`. The receipt covers 636 files and 573,545,551 bytes. The run manifests identify the original HDFS-32 JUnit and report no GraphChecker or skeleton classpath entry.

Trials `030`, `033`, and `070` timed out before JaCoCo flushed. Their `jacoco.exec` files exist but have zero bytes, and their four decoded coverage files were not generated. The case final audit classifies these as timeouts before the selected target; their coverage is unavailable. The other 78 runs have nonempty JaCoCo and all four decoded coverage files.

The receipt's canonical file-index SHA-256 is `e4e9cdba765ba965fcfe856f0c03408e6833bf3808058b65f02ef1d81551029e`. The committed `raw-runs.tar.zst` contains the complete original run root, including scratch files. Its 941 files were compared by size and SHA-256 with the preserved source root, and all 636 files in the earlier per-file receipt matched. The receipt also records the archive SHA-256 and full-tree SHA-256.
