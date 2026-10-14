# Legacy to native dependency audit

The active campaign uses `native_graphchecker_campaign`,
`native_graphchecker_feedback`, `native_graphchecker_dispatch`,
`native_graphchecker_queue`, and the source-built GraphChecker engine in
`static_scope_port/original_engine`. This audit concerns source dependencies;
historical receipts in `data/mallory/graphchecker_port` remain evidence for the
earlier method and are not native campaign results.

| Legacy path | Current native dependency | Disposition |
| --- | --- | --- |
| `adapters/hbase/graphchecker_port` | None. `native_graphchecker_port/source_anchors.py` owns the checked source edits; its local `src/` owns the original-runtime bridges. | Retire old Python installer, tests, and Java bridge copies; retain historical audit prose cited by the archived 102-check readiness snapshot. |
| `adapters/zookeeper/graphchecker_port` | None. `native_graphchecker_port/src/main/java` owns the original-runtime protocol weave, bridges, and JUnit runner. | Retire old installer, Soot weave, runtime bridges, and Maven module; retain historical audit prose cited by the readiness snapshot. |
| `adapters/hdfs/graphchecker_port` | `native_original/build_native_overlay.py` needs an already patched generic HDFS overlay. The generic `install.sh` and `PatchEmbeddedIpc` produce that input. | Keep the generic patcher and source. The final native IPC bridge is byte-pinned under `native_original/templates/` and no longer generated from the custom-runtime bridge at build time. Move the generic patcher under `native_original/` only with an immutable-output equivalence test and updates to source-overlay receipts. |
| `adapters/solr/graphchecker_port` | `native_graphchecker_port/prepare_case.py` reads its `native_original/` transport patch, communication map, runner, and build script. The 102-check inventory also cites `solr40_original_test_failure.txt`. | Keep those files and the inventory evidence. Retire other old scripts only after current Solr campaign pins and the working-tree protocol edits are reconciled. |
| `graphchecker-runtime` | The old `instrumentation/graphchecker_port/pom.xml` and Java weaver classes compile against its `MessageDoors`. The active `native_original_weave.py` instead builds `static_scope_port/original_engine`; HBase's native source anchor mentions the old Maven coordinate only as text that it replaces. | Keep while old Java instrumentation remains buildable and main has uncommitted runtime changes. The migration point is the Java weaver module, not the source-built GraphChecker runtime. |
| `core`, `report`, and the remaining `dispatch` | No imports from the active native feedback/campaign/queue. Historical case runners and release snapshots still import `core` and `report`; `native_graphchecker_dispatch/checklist.py` reads `dispatch/shards/ownership.json`. | Keep until archived launchers are migrated or deliberately retired and the shared ownership file moves into the native dispatcher. Main also has uncommitted `core` edits. |

The deletion review searched tracked callers with `git grep` across the native
entrypoints, source port, instrumentation, and system adapters. No running
node0, node1, or node2 process invoked `Mallory.core`, `Mallory.report`, or
the retired HBase/ZooKeeper custom adapter entrypoints at review time.
Active campaigns use immutable source, engine, and protocol pins outside these
deleted paths; this cleanup does not modify campaign snapshots or result rows.
