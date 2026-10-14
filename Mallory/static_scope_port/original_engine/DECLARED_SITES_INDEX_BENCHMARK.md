# Declared-site lookup index

`StaticScopeMap.declaredSitesAt(siteId, declaredCallee)` now indexes declared
rows once when the map is loaded. Each lookup still applies the original
candidate-edge deduplication key in source-row order and returns a fresh list.
The published `static_scope_map.jsonl` format and bytes are untouched.

## Frozen HBase differential

Read-only inputs from the closed HBASE-02 original healthy run:

| Input | SHA-256 |
| --- | --- |
| `inputs/static/original/static_scope_map.jsonl` | `bd13ccd2493237897d95a8ec56f9e871bff1bbc17cace680e8c3e2f41d6003a4` |
| `inputs/healthy/healthy-trace/runtime_trace.jsonl` | `1fadd4713744d1f68d107aa8107a68edac638ce0be74928645ff2d8b54d1b923` |

Both are under
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-02-20261014-native-v1/`.
The map has 147,238 rows, including 6,197 `DECLARED_SITE` rows. The probe
reads all 15,089 `CALL_SITE_ENTER` `(siteId, declaredCallee)` queries from the
frozen trace. The old class was loaded from immutable JAR
`original-engine-ownership-dispatchcache-5fbd163d6af04955.jar` (SHA-256
`5fbd163d6af04955ee011da65b889b5df35ea4fed697e5fcfe2c5ad885c3894d`).
The new class was loaded from this worktree's `target/classes`. Both used
the same probe class, JVM options (`-Xms512m -Xmx4g`), dependencies, map,
and trace, in sequential runs on node0.

| Engine | Map load | Lookup wall | Lookup CPU | Whole probe wall | Matched queries | Returned sites | Output SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Old full scan | 16.000 s | 233.155 s | 228.336 s | 253.202 s | 7,752 | 7,752 | `6aa89937c4c50f322bcdc487cf0fde3866665324c99b027012a64122c4082b6a` |
| Indexed | 14.821 s | 0.206 s | 0.206 s | 18.397 s | 7,752 | 7,752 | `6aa89937c4c50f322bcdc487cf0fde3866665324c99b027012a64122c4082b6a` |

The lookup stage was about 1,132 times faster; the complete read-and-lookup
probe was about 13.8 times faster. These are frozen-trace lookup measurements,
not an estimate of a full HBase test or campaign runtime. The probe hashes
the ordered returned site fields for every query, including empty results;
the identical digest and unit test demonstrate byte-identical lookup content.
`StaticScopeMapDeclaredTraceProbe` is kept with the tests for reruns.

## Full original Recorder and Scheduler differential

The old invocation arrays are frozen at `inputs/plan/recorder/command.json`
and `inputs/plan/scheduler/command.json` beside the inputs above. For the
indexed run, each array retained its JDK 8 executable, `-Xmx8g`,
`-Dcausynth.loop.default.bound=1`, target occurrence, and all other flags.
The first classpath entry was replaced with this worktree's `target/classes`
(`StaticScopeMap.class` SHA-256
`7454985e210b7ebb0ed02fb47e06e751b2eaec6f4ebf2856d4cc7a5788caa44d`).
The command's old `/dev/shm` input paths were replaced with the byte-identical
durable frozen copies under `inputs/healthy/healthy-trace/` and
`inputs/static/original/`; output paths alone pointed to
`/dev/shm/mallory-hbase02-declared-index-diff-v1/`. The exact indexed arrays
were saved as `recorder-command.json` (SHA-256
`2414ceb8e447b9b21ea943246d9a3b8bad52f31d92c34ad809825dad534209dd`)
and `scheduler-command.json` (SHA-256
`9a557482857feb22e37e3f613a5e749ccaee17d72e560be35d3a046650726666`).
The command files, stdout/stderr, and new output artifacts are preserved in
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/declared-sites-index-diff-20261014/`.

| Stage | Old frozen wall | Indexed wall | Output | SHA-256 of both byte-identical files |
| --- | ---: | ---: | --- | --- |
| Recorder | 207.644 s | 198.340 s | `region_skeletons.jsonl` (31,228,571 B) | `faf22d0240eee9e06326d4504adf78336542d3b431ce84645bee34fa69c79785` |
| Recorder |  |  | `concolic_region_plan.jsonl` (52,496,829 B) | `1c72588eeea6ddb888b53863495db2c322618c08f5fbb35be5151b809afa5fc3` |
| Scheduler | 75.538 s | 92.085 s | `execution_task_plan.jsonl` (115,364,468 B) | `a43adcc4107ba90f392d3dab7ceeaf1d39e4daaf6c0ecbb34390c5092a47e07a` |
| Scheduler |  |  | `runtime_workflow_schedule_index.json` (120,119 B) | `aa9d7d45ea18d081b7f0693e3fe42cbf7837eb8dbc2ab68cc87450d1bbd4f8fe` |

Both new stages exited 0 with empty stderr. The Scheduler used the indexed
Recorder's byte-identical region plan. These wall times include concurrent
node0 work and do not establish a full-workflow speedup. In particular,
`declaredSitesAt` is called on selected activation captures, not every raw
`CALL_SITE_ENTER`: the frozen healthy region plan has 542 captures, and
completed HBASE-02 fault trials r0000/r0001/r0002 have 534/542/561.
Per-trial `original-graph` invokes Recorder but not Scheduler. The observed
233-second improvement from querying every raw call is therefore an upper
stress test, not a forecast for each fault trial's roughly 238-second graph
analysis. The index is behavior-preserving and improves its own lookup stage;
other Recorder costs remain to be profiled separately.
