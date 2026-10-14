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
