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
