# Remote disk cleanup (2026-10-09 UTC)

The Mallory campaign may use node1 and node2. SSH access worked on both nodes. Before cleanup, `df -h /users/ZhenyuLi` showed 11 GiB available on node1 (83% used) and 12 GiB on node2 (81% used). The largest directories under `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot` contain prior experiment evidence (about 31 GiB on node1 and 17 GiB on node2); these were retained. Existing source trees, run logs, traces, checkpoints, and tmux sessions were retained. No active Java, Maven, or Gradle campaign was found during the cleanup checks.

Only the following exact generated paths were deleted:

| Host | Path | `du -sb` before deletion | Reason |
| --- | --- | ---: | --- |
| node1 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-09/actor-v2/solr16257-diff/gradle-home/caches` | 469,099,701 bytes | Gradle cache; regenerable |
| node1 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-09/actor-v2/solr16257-diff/gradle-home/wrapper/dists` | 439,905,931 bytes | Gradle wrapper distribution; regenerable |
| node2 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-22/v5/graphchecker/target` | 28,234,157 bytes | Maven compiled build output; regenerable |
| node2 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-22/graphchecker/target` | 20,794,410 bytes | Maven compiled build output; regenerable |

Totals by logical size: node1 909,005,632 bytes; node2 49,028,567 bytes. After deletion, `df -h` showed 12 GiB available on node1 (82% used) and 12 GiB on node2 (81% used). Both hosts confirmed the exact paths no longer existed. The remaining large directories were retained because their evidence or source provenance was not shown to be redundant.

## Archived terminal HDFS runs

The two old `hdfs_recovery_shared/ha-effective-v2` campaigns were terminal (`checkpoint.json` had `active: null`), and no process used their paths. The current Mallory HDFS work is elsewhere. Their preexisting raw archives explicitly excluded `scratch`; I therefore archived each run's complete `scratch` directory separately before removing the duplicate run trees. `zstd -t` and `tar -d` against the live scratch directories succeeded.

| Host | Exact deleted path | `du -sb` before deletion | Preserved archives and verification |
| --- | --- | ---: | --- |
| node1 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/hdfs_recovery_shared/ha-effective-v2/runs` | 5,170,792,670 bytes | `shared-terminal-raw.tar.zst` (SHA-256 `7a9a126b7d8038835635bf0acebf59486b5cbb498960c3bfda9b9dc4976dfbe6`); `scratch-terminal-20261009.tar.zst` (5,315,573 bytes, SHA-256 `fdc83b0e2f5ee8a838148774020cdbda1a1f9cb98966c9bf9d433b4943410e9c`) |
| node2 | `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/hdfs_recovery_shared/ha-effective-v2/fallback28-junit-v1/runs` | 3,418,708,102 bytes | `terminal-raw.tar.zst` (SHA-256 `703bf087c8d72fcc94fe743cff9c0c723a254293c909a4db16685fabd74efa07`); `scratch-terminal-20261009.tar.zst` (56,627 bytes, SHA-256 `9b7cc9337119c501ae1e80583964a4f5e616aa15d8b6104763aaba2986a622c0`) |

Before deletion, the existing archive verifiers streamed and checked every archived member against the per-file manifest: node1 5,216 members, node2 4,029 members, both zero errors. A separate comparison of the current non-scratch `runs` files against the manifests checked node1 5,120 files (4,358,859,034 bytes) and node2 3,950 files (3,387,413,731 bytes) with no path, size, or SHA mismatch. The archive, manifest, receipt, checkpoint, ledger, scripts, and summary files remain in place. The duplicate run trees can be restored from the two archives on each host.

Immediately before this batch, `df -h /users/ZhenyuLi` showed 12 GiB free on both hosts (82% used). Afterward it showed 16 GiB free on node1 (74% used) and 15 GiB on node2 (76% used). A failed 22-byte scratch archive attempt and its path list were also removed from node1; it contained no data.

## Archived SOLR-31 actor trial copies on node2

The old SOLR-31 actor-v2 campaign had `status: budget_complete`, `active: null`, and 128 completed trials. Its raw archive and manifest had matching SHA-256 digests; streaming every archive member and checking every current non-scratch trial file against the manifest verified 1,032 files (424,902,095 bytes). The existing raw archive SHA-256 was `4b912e6ab70a1d334858fb8f3ce847cc9f0b2670f3e562d4a24afa7205d8e7f1`. The archive excluded scratch state, so all 129 trial scratch directories were separately archived, passed `zstd -t` and `tar -d`, and remain in `scratch-terminal-20261009.tar.zst` (3,260,925 bytes, SHA-256 `0cc006463c035f3c35e063483090ebe2674da280251f6351889bbf8d276a5962`). The Solr adapter confirmed its current work does not use the old paths.

After verification, only `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-31/independent/actor-v2/campaign/trials` was deleted (`du -sb`: 732,945,839 bytes). The campaign state, progress, audits, archive, manifest, receipt, and scratch archive remain. `df -h` still rounded node2's available space to 15 GiB immediately afterward.

## Final verification

At the final check, both deleted HDFS `runs` paths and the SOLR-31 `trials` path were absent. Their paired raw and supplemental scratch archives were present and nonempty. The archive verification scripts and manifests remain at:

- node1: `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/hdfs_recovery_shared/ha-effective-v2/archive_terminal_shared.py`, `shared-terminal-raw-manifest.json`, and `shared-terminal-archive-receipt.json`.
- node2 HDFS: `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/hdfs_recovery_shared/ha-effective-v2/fallback28-junit-v1/archive_terminal_alt.py`, `terminal-raw-manifest.json`, and `terminal-archive-receipt.json`.
- node2 SOLR-31: `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-31/independent/actor-v2/campaign/raw-trials-v2-manifest.json` and `raw-trials-v2-receipt.json`.

Final `df -B1 /users/ZhenyuLi`: node1 **17,096,933,376 bytes available** (74% used); node2 **15,862,071,296 bytes available** (76% used). HDFS-01's old archive covers `evidence/runs` and does not cover its 1.6 GiB `actor-v2/campaign-v3`, so that campaign was retained. Other unproven or unique experiment directories were retained, as was the active node2 Mallory ZooKeeper Maven build.
