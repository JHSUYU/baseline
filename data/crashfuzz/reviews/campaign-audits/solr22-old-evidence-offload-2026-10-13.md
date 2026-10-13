# Node2 retired SOLR-22 archive offload

On 2026-10-13 UTC, node2's old `unit-test-pivot/cases/SOLR-22/v5/fuzz-io-run/idle-trials.tar.zst` archive was copied to `node1:/users/ZhenyuLi/static-rerun/offloads/node2-unit-test-pivot/SOLR-22-v5-fuzz-io-run-idle-trials.tar.zst` to free space for active original JUnit campaigns. It is not part of the active SOLR-36/37 or SOLR-40 campaigns.

The source and destination were both 1,128,423,261 bytes with SHA-256 `c165551ec24e10a6d98a6ff36d524fd2c48211fed1fd51aa85f9ebfe26cdfb1d` before the old node2 copy was removed. The original parent directory, `idle-trials-files.sha256`, result, state, and compaction metadata remain on node2. Its receipt is `node2:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-22/v5/fuzz-io-run/idle-trials.offload-receipt.json`.
