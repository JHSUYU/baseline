# HBASE-11 node1 raw archive

`node1-independent-raw.tar.zst` contains HBASE-11's `independent` mirror, replay, and case-specific checkpoint evidence from node1. `node1-independent-raw-receipt.json` records the archive SHA-256 and a SHA-256 tree digest of all 148 source files. Every extracted file's size and SHA-256 matched the still-preserved node1 source.

HBASE-11 shares the original JUnit fault runs with HBASE-10. Their full logs and JaCoCo files are in HBASE-10's `node1-independent-raw.tar.zst`; they are intentionally not duplicated here.
