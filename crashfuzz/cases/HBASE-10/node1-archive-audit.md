# HBASE-10 node1 raw archive

`node1-independent-raw.tar.zst` contains the complete `HBASE-10/independent` directory from node1, including the original JUnit fault logs, ordered plans, checkpoints, JaCoCo `.exec` files, and decoded coverage. `node1-independent-raw-receipt.json` records the archive SHA-256 and a SHA-256 tree digest of all 765 source files. Every extracted file's size and SHA-256 matched the still-preserved node1 source.

HBASE-11 and the shared phase of HBASE-12 reuse these JVM executions. Their archives contain their own case evidence, not a second copy of this run root.
