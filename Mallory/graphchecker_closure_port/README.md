# Original GraphChecker closure port (experimental)

This isolated module executes the **original** GraphChecker `Corpus` and
`ClosurePlanner` against a translated Mallory trace. The three Java sources
under `edu/uva/liftlab/graphchecker/explore` are byte-for-byte copies of
GraphChecker commit `c4a90033c654737206466ed36ce837c5b3c12457`:

| Source | SHA-256 |
| --- | --- |
| `Corpus.java` | `fd789a447537ca8b441256462e9082365cf7b7c73be10ca3f4b7fce18aac8379` |
| `ClosurePlanner.java` | `a812324dd31fbf9b2bf96e54e4e080d763db42f8e6587bac212faf1d96ca8418` |
| `Branches.java` | `bc872c09cec2e58c54eea46da0db15ddabd1ecc25269096a680554193f1b5542` |

Their remaining dependencies come from the pinned GraphChecker jar. Run
`bash verify_upstream.sh` to check the source copy, repository commit, and
thin/fat jar SHA-256 before use. The adapter verifies jar provenance again
at runtime. This module is not in the running campaign path.

## Trace adapter

`NativeClosureMain` converts actual Mallory `ACTIVATION` and `TARGET_CHECK`
or `TARGET_THROW` rows into GraphChecker contract rows. A persisted-resource
`WRITE` receives a per-resource integer version in observed order. A `READ`
is translated only when its writer endpoint and opaque version identify one
earlier write exactly. `WIRE` pairs are reported only for exact matching
`EXPORT`/`ATTACH` envelope tuples. They are not translated to native symbolic
export/attach rows because the current trace lacks payload expressions.

The translated read/write rows preserve observed identity and order, but
carry fresh abstract value symbols rather than captured payload bytes. The
separately reported `PROGRAM_ORDER_FAULT_PREDECESSOR` is a Mallory extension
for an immediately preceding same-thread completed region. It is not a
GraphChecker value-dependency edge.

Build and test:

```bash
bash verify_upstream.sh
mvn -q test
```

Reproduce the ZooKeeper 07 healthy-trace comparison from this directory:

```bash
java -Xmx2g -cp target/classes:../../GraphChecker/target/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar \
  edu.uva.liftlab.mallory.closureport.NativeClosureMain \
  /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-07-20261013-v3/validation/healthy/graphchecker-trace.jsonl.gz \
  /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-07-20261013-v3/config/scope/static_scope_map.jsonl \
  '<org.apache.zookeeper.server.quorum.Learner: long registerWithLeader(int)>#u51' \
  /tmp/zk07-native-closure-v3.json \
  /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-07-20261013-v3/validation/healthy/graphchecker-feedback.json
```

The original planner found two target occurrences and their `#u40` branch
flip sites in this trace. Mallory's `TrialGraph` additionally included twelve
occurrences via structural edges outside the native value-demand closure.
The current Mallory trace does not have expression DAGs or concrete shared
field read versions; native symbolic READ/WRITE, EXPORT/ATTACH, and target
predicate causality still require runtime hooks before this port can replace
the campaign analyzer.
