# HDFS-31 raw-run receipt

`raw-run-sha256-receipt.json` records SHA-256 and byte length for the eight top-level raw artifacts in every run under `/users/ZhenyuLi/hdfs31-independent-runs`: `healthy-01` and `trial-001` through `trial-080`. It covers 648 files and 552,113,168 bytes. All 81 directories have `run.json`, `events.tsv`, `junit.log`, a nonempty `jacoco.exec`, and four decoded production-coverage files. The run manifests identify the original HDFS-31 JUnit and report no GraphChecker or skeleton classpath entry.

The receipt indexes existing raw files; it does not include their contents in Git. Its canonical file-index SHA-256 is `9f7f126dfc67fa65d23cee4017d086a9dbd2dfe1f4beafbd820e8f40ad128cb1`. Keep the raw directory for a full replay or independent hash check.
