# HBASE-12 node1 raw archive

`node1-independent-raw.tar.zst` contains the complete `HBASE-12/independent` directory from node1, including the unique RPC and META fault phases, original JUnit logs, ordered plans, checkpoints, JaCoCo `.exec` files, and decoded coverage. `node1-independent-raw-receipt.json` records the archive SHA-256 and a SHA-256 tree digest of all 677 source files. Every extracted file's size and SHA-256 matched the still-preserved node1 source.

HBASE-12 also uses shared HBASE-10 executions. Their full logs and JaCoCo files are in HBASE-10's `node1-independent-raw.tar.zst`; they are intentionally not duplicated here.
