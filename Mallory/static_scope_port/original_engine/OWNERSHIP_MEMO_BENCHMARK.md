# Static scope ownership memo

`StaticScopeMap.sites()` now builds a method-to-region index once and caches
the innermost holders for each method during that call. It preserves the
original region order, retains all equal-size and incomparable regions, and
keeps the empty region authority for an unheld root or declared site. The
cached data is local to one call; no static state persists between analyses.

The upstream `StaticScopeMap.java` SHA-256 is
`14c7d27183c954c76fa9bcf7bf0dda3be33b12b506c78d75c3a4a1c6d60c4b85`;
the modified source SHA-256 is
`8e47257f86a8e180b4020ce2b6579b26328bbb5ef4fc49ee56f107328893d4ff`.
The only engine source difference between the two benchmark JARs is this
file. `mvn -q test package` passed all 12 module tests, including the focused
nested, sibling, equal-size, and unheld ownership test.

The frozen SOLR-01 input was
`/proj/silentfailure-PG0/mallory/solr01-native-impl-v3/mapped-static-input-draft.json`
(SHA-256 `6e5e1854a43c4bc20771680c1a7037ad2a83b6bd6a809efa4508a93cd4539c65`).
Both runs used the same 119 physical Solr implementation classes and ordered
Soot classpath. They ran sequentially on node1 with separate output and
temporary directories. The comparison receipt and complete command lines are
under `/proj/silentfailure-PG0/ZhenyuLi/mallory-static-scope-ownership-benchmark/`.

| Engine | JAR SHA-256 | Wall time | Original scope rows |
| --- | --- | ---: | ---: |
| Baseline | `208405fdc9c3b156560cb4537aff3f482502eae4dea45595cf5ca1df1d9a9b65` | 34.343 s | 2,674 |
| Memo | `0eb6c3fc7e69903d14c116bdb4b45f89fefbaac0eec4948bdc700bae5e8539e7` | 31.313 s | 2,674 |

The original scope map was byte-identical in both runs (SHA-256
`ce04b2f5dfe274399afdf058e1e87eaa67bb3c89647dd8e94cf8da252`). Its
2,674 JSONL rows also had equal ordered sequences and equal canonical row
sets. The translated 574-row scope map (SHA-256
`3505e2540e6071d98064d61717297a1e8f54a7b3c4357b6cfb53affb17e1bb8f`),
weave manifest, candidate dataflow edge gzip, and region skeleton gzip were
also byte-identical. The wall-time difference is one pair of complete Soot
runs; it is not a precise estimate of the isolated `holders()` speedup or a
guarantee that a larger SOLR-05 scan completes within its time cap.

## SOLR-05 559-class scale run

The original 559-class scan used frozen input
`/proj/silentfailure-PG0/mallory/solr05-native-register-bounded-v1/static-input.json`
(SHA-256 `956b1d5a9eaa9d9a2618d17b9878ae77d1bed691c2523a714056c5173d8d6ceb`).
Its pinned original engine's `StaticScopeMap.class` is byte-identical to the
rebuilt baseline class (SHA-256
`e4843094c94050629a1d350b8b2d091caa68601291419bfd7e5ddd5881b3e3ef`).
The original run reached the 1,200-second cap at 1,200.556 seconds and did
not publish a manifest. Its 8-minute stack was in
`StaticScopeMap.holders → addRootSite`; the 16-minute stack was still in
`StaticScopeMap.holders → add`.

The separate memo-engine run changed only the invoked engine JAR and its
output and temporary directories. It retained the same frozen Soot
classpath, application classes, target, communication map, planner JAR,
heap, and 1,200-second cap. It completed with exit code 0 in 673.695 seconds
and peak sampled child RSS of 6,365,044 KiB. By 8 minutes it had passed
`StaticScopeMap.sites()` and written the original scope artifact; its sampled
stack had moved to subsequent `LatentFaults/FaultPropagation` processing.
The complete command, timed receipt, and 2-, 5-, and 8-minute stack samples
are under
`/proj/silentfailure-PG0/ZhenyuLi/mallory-static-scope-ownership-benchmark/solr05-559-optimized/`.

The completed run emitted 63,296 original static scope rows (SHA-256
`cb2d108ca8a0fb3f7d9dc719151f96ef2d6183b59d7e1324db6adf09693c0d33`),
17,321 translated rows (SHA-256
`a4d96dde18a09a92aeba28df7584f7d280dcde7ae1e00740fa5bc7cc159afe41`),
and a manifest (SHA-256
`9efa2b160f47d7811a0e73989a3a669b0075881d8d50e2abf01e113f0137b753`)
with 1,564 regions, two targets, 287 typed doors, and one RPC port. Since
the original large run timed out before publishing its scope, large-case
row-by-row equivalence is unavailable; the complete 119-class pair above is
the equivalence check.
