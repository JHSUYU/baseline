# HDFS-24 / HDFS-34 old-image MiniDFSCluster healthy-only preparation, v1

Source-only review, 2026-10-09 UTC. No JVM run, fault trial, shared config edit, or result edit was made in this preparation. These configurations are isolated under `Mallory/adapters/hdfs/cases/old-image-v1/`; both set `calibration_only=true` and `auto_promote_if_healthy=false`.

## Pinned inputs

| Input | SHA-256 |
| --- | --- |
| Hadoop source commit | `9d50c6884666e794e45102260a4017bb31802e1b` |
| `TestDFSUpgradeFromImage.java` | `5b98a6ee667a9d2422b16bc53ab8bdfc36ba2acfae97fdeaea6aca101a98f951` |
| compiled `TestDFSUpgradeFromImage.class` | `a84ac55ffb306f4e0778bf641c9979a0876e14fafd590dd9f2b98bf31cb4f5a5` |
| `hadoop-22-dfs-dir.tgz` | `eaddf228d286f54fb431a12342550a9b473b189dc3a36cbf3eec668ce9000380` |
| `hadoop-dfs-dir.txt` | `189449068f059413468ecbc5fd81d9a075bec53f310edc1059e5fc6f82bb9d08` |
| Mallory agent JAR | `07c23da7699217aa4f51c389cde3539ee241ece05efa5d11575bc5d804cf4e80` |
| HDFS adapter v10 JAR | `1f65f6346288e92e514f6e815be35aea6d446cd0432a429fa130ad9aab581585` |

The selector is `org.apache.hadoop.hdfs.TestDFSUpgradeFromImage#testUpgradeFromRel22Image`. In `TestDFSUpgradeFromImage.java:295-300`, it unpacks the 0.22 image and starts a four-DataNode `MiniDFSCluster`. `upgradeAndVerify` at lines 598-625 starts with `format(false)` and `StartupOption.UPGRADE`, waits for the cluster and safe mode, and verifies the filesystem. Both required resources are already staged in `target/test-classes`; the configs explicitly set `test.cache.data` to that directory because the source reads this property at lines 108 and 120. `test.build.data` points into `{trial_dir}/hdfs-data` to isolate the unpacked image. The source archive's eight DataNode `current/VERSION` files have layout `-33` and namespace ID `-386152743`; its NameNode `current/VERSION` files have the same namespace ID. Python archive inspection found no `BP-*/current/VERSION` member.

## Admission decisions

### HDFS-34: admit only a healthy probe

Config: `Mallory/adapters/hdfs/cases/old-image-v1/HDFS-34-healthy.json`, SHA-256 `147f8af50cec89f4662c2c7611d976b35e962c3d8ab8035e66e2fa0ce59db09a`.

Exact target: `DataStorage#doTransition(...)Z@739:branch:5`, selected throw `@744:throw:1`, `DataStorage.java:739-744`. Source SHA-256 `170014db0bb1c4efd6a5be2428f880f5892b4fbc3573ea21762af26f3406b809`; compiled class SHA-256 `e0ad835edca2264c5aa1352e0a86926c602c6106315f3995b0e9fa32b0befd7f`; site catalog SHA-256 `8bf516358809fbc19b4a166027d3b7a4ac10481bac7fb3ad71757fdfcb06ee8f`.

`DataStorage.doTransition` reads the old DataNode `VERSION` before testing the pre-federation namespace ID. The archive has a matching NameNode/DataNode namespace ID, so source predicts the nonthrowing side of the exact guard. A healthy probe must still establish executed JUnit > 0, exact loaded class hash and branch, named DataNode receiver, zero selected throw, and a time-respecting pretarget `VERSION` file-I/O path. No fault campaign is authorized by this config.

The original `TestDFSStartupVersions#testVersions` selector is unsuitable: it deliberately iterates mismatched namespace/version combinations and tolerates failed DataNode starts. Its earlier calibration reached and threw the selected check on an unknown actor. That was expected test behavior, not a bug.

### HDFS-24: selector is unsuitable for the exact check

Diagnostic config: `Mallory/adapters/hdfs/cases/old-image-v1/HDFS-24-healthy.json`, SHA-256 `7f3c51b773d37709047689a5d6a8fbf611a5a60a2375f296cda25c27a860dfe0`. **Do not admit to fault fuzzing on source evidence.**

Exact target: `BlockPoolSliceStorage#doTransition(...)Z@414:branch:14`, selected throw `@424:throw:1`, `BlockPoolSliceStorage.java:414-424`. Source SHA-256 `3234d407e842dbc76ec4fd5c0671b39108988dfa36b6c6dea9d10f3ad949be8e`; compiled class SHA-256 `3585869cf95c5a58dd50ffb3766bceb797c09b532d46bdc08e811ae659c520a9`; site catalog SHA-256 `e87758a8550cd9b5a6fd0957ffc4e92d997a5c82e5908a406bbc6edb8e4df863`.

The 0.22 archive has no block-pool `VERSION`. During pre-federation upgrade, `DataStorage.doUpgradePreFederation` calls `bpStorage.format(curDir, nsInfo)` at `DataStorage.java:833-836`. `BlockPoolSliceStorage.format` at lines 283-291 writes the *current* DataNode layout and `nsInfo` cTime. A subsequent `BlockPoolSliceStorage.doTransition` returns early at lines 404-406 for that current layout and equal cTime, before the selected guard at 414. The exact target is therefore not supported by this selector even though the test is a clean four-DataNode upgrade. Keep the diagnostic config only to verify the predicted absence of the exact branch, if useful. The original `TestDFSUpgrade#testUpgrade` is unsuitable for clean admission because the one method mixes valid upgrades with deliberately incompatible DataNode state and expected block-pool startup failures. Its earlier healthy calibration threw the selected check on an unknown actor.

## Static validation and next step

Both new JSON configs parse, have their agent/adapter/site/test/target/fixture hashes pinned in `runtime_artifacts`, and pass `Mallory.core.campaign.validate_config` plus `Mallory.dispatch.scheduler.verify_runtime_artifacts` on node0. These checks do not execute Java. `mapping.healthy_seed_verified` and `mapping.node_identity_binding_verified` remain false, and `mapping.verified_healthy_probe` remains null. Hand HDFS-34 to the HDFS adapter/dispatcher for a single isolated healthy run when a lane is available; reject fault promotion unless the exact-site and causal-path gates above pass. For HDFS-24, find a clean existing MiniCluster method with a pre-existing, older block-pool `VERSION` that reaches `@414` without the selected throw, or record no suitable existing JUnit.

## HDFS-34 lane and disk admission note

Read-only fixture measurement: the 0.22 archive is 413,239 compressed bytes and contains 1,196 members, of which 1,138 regular files sum to 84,921,174 bytes when unpacked. The reference text is 3,122 bytes. Existing node0 HDFS healthy trial directories measured 0.3–2.2 MiB for sampled cases; these are other workloads, so they do **not** establish this upgrade test's peak. The existing `hdfs` build root is 785 MiB total, with a 426 MiB HDFS `target` directory already present. Use a planning allowance of **1 GiB new transient space for one healthy run**, then recheck free bytes before JVM launch. This is an admission allowance, not a measured peak or a quota. With a 5 GiB host reserve, launch only when free space is at least 6 GiB and no concurrent case uses this source/build root. Node0 had 6.2 GiB free during this source review while two other HDFS lanes were active; waiting for those lanes to release is preferable.

Preferred exclusive source/build root: `/users/ZhenyuLi/.mallory-worktrees/hdfs`, with a dedicated lane lock such as `node0-hdfs-old-image-v1.lock`; the case claim lock alone does not serialize Maven `target` writes across cases. Runner pins at this review: `Mallory/core/campaign.py` SHA-256 `658bf806c45117db61201042c43015cac8e504a4f82eb3a166dd71c8a2a6d8dd`, `Mallory/core/junit.py` `2575ba497b0bcf14c96f9ab8025e855a0602cbcb76f88c21f276d53234629595`, `Mallory/core/events.py` `db6b5ca756fe13d804e4356fdf01ef1924913b9977b5444797544f85cc98bd34`, `Mallory/dispatch/worker.py` `dbef7bd8f252a5bdff6fef36f544f62075f0e39b5326ed1fd3400886b89ada38`, and `Mallory/dispatch/scheduler.py` `fdcd27d9c41194ea6997b7fd9ee405edaef9b3d90cc9fd6017e73618182c0349`. Rehash these at actual admission, since other agents may update them.
