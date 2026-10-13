# Native GraphChecker session feedback bridge

This opt-in module reads **one landed native GraphChecker session per trial**.
It calls the original `SessionReader`, `Corpus`, `Branches`, and
`ClosurePlanner` from Mallory's source-built GraphChecker port. The resulting
closure members and flip sites are original planner results. It reports
recorded `WIRE` export/attach pairs, exact `STATE` write-version/read pairs,
and explicit `MESSAGE_START` activation anchors *within* those members.
`MESSAGE_START` is a control edge, not a value handoff. The output does not
promote static may-scope sites to observed edges.

The engine port records its upstream provenance as GraphChecker commit
`c4a90033c654737206466ed36ce837c5b3c12457` in
`Mallory/static_scope_port/original_engine/README.md`. This module compiles
against that port and checks the selected JAR at runtime. It does not
reimplement GraphChecker's post-run closure algorithm.

The caller binds `targetSiteId`. Within each native run, the bridge selects
an exact `OccurrenceAddress.id()` and requires that event in the target rows
and original planned closure. A fresh distributed JUnit run can assign a new
exact ID as its process epoch or root schedule changes. Across runs, `delta`
compares the stable target site, node name, and region family; it retains the
separate exact IDs as evidence. A unique target is required in single mode.
For a site reached multiple times, target-set mode plans each occurrence
separately and unions only the resulting feedback for scheduling. It never
asserts an edge between distinct target occurrences. `observedFatal` is only
the GraphChecker target branch metadata; a target exception still needs an
exact runtime throw receipt and the campaign oracle.
Only occurrences with a recorded `reachedAnchor=true` enter the target set.
Unreached target rows are preserved in `unreachedTargetRows` but cannot add
closure members or satisfy the oracle. A run with one reached and one
unreached occurrence retains the reached target.

Target-set mode makes one Java invocation per trial. It reads the native
`SessionReader` target list and builds one original `Corpus`, then calls the
original `Branches` and `ClosurePlanner` independently for each selected exact
target. The original `Corpus.read` currently performs its own `SessionReader`
read, so there are two full session reads per trial, independent of the number
of target occurrences. The campaign calls this mode directly; it does not
start a separate target-listing JVM first. In three runs of a two-target
synthetic session, median wall time was 1.821 s for the previous listing plus
two exact analyses and 0.668 s for the single-invocation mode on this host.
This is a small-fixture timing, not a real-system throughput claim.

Use from Python after building `Mallory/static_scope_port/original_engine`:

```python
from pathlib import Path
from Mallory.native_graphchecker_feedback import summarize, delta

healthy = summarize(Path("/path/to/healthy/iteration"), "exact#target#site",
                    Path("/tmp/healthy-native-summary.json"),
                    static_scope_map=Path("/path/to/static_scope_map.jsonl"))
trial = summarize(Path("/path/to/fault/iteration"), "exact#target#site",
                  Path("/tmp/trial-native-summary.json"),
                  static_scope_map=Path("/path/to/static_scope_map.jsonl"))
print(delta(healthy, trial))
```

If a site can execute more than once in a run, use target-set mode and
optionally constrain physical actors by node name:

```python
from Mallory.native_graphchecker_feedback import summarize_target_set, delta

healthy = summarize_target_set(Path("/path/to/healthy/iteration"),
                               "exact#target#site", Path("/tmp/healthy-set.json"),
                               static_scope_map=Path("/path/to/static_scope_map.jsonl"),
                               actor_names={"nn0", "nn1"})
trial = summarize_target_set(Path("/path/to/fault/iteration"),
                             "exact#target#site", Path("/tmp/trial-set.json"),
                             static_scope_map=Path("/path/to/static_scope_map.jsonl"),
                             actor_names={"nn0", "nn1"})
print(delta(healthy, trial))
```

The returned `perTargetOccurrences` retains each exact plan, target row,
observed edge set, branch outcomes, gaps, and truncation. The union fields
are a fuzz queue score. A target-set comparison requires the same target site
and at least one common target region; actors can move after failover.
Runtime fault matching must still use the exact event identity within its
own run.

For reproducible runs, pass `engine_jar=Path("/path/to/pinned-engine.jar")` to
both calls. The bridge records the exact engine, static map, static map plus
neighboring region skeleton, bridge source, and native session digests in the
saved JSON and rejects changed inputs during extraction. It
also verifies that `SessionReader`, `Corpus`, `Branches`, `ClosurePlanner`, and
`StaticScopeMap` were loaded from that one selected source-built JAR.
Original native session row files use the GraphChecker JSONL layout. The
static scope map and neighboring region skeleton may be plain JSONL or gzip;
both forms are covered by the target-set tests. The
`staticScopeMapSha256` field hashes only the map; `staticScopeBundleSha256`
also hashes the skeleton file GraphChecker reads.

`NativeFeedbackMain` currently emits only **observed** edge families. The
original `ClosurePlanner` can admit static candidate writers/producers that
were not observed in a trial; those remain closure members with planner
`why`, `flipSites`, gaps, and truncation, but have no invented edge.
`branchCoverage` is observed GraphChecker `DecisionRow` site/outcome coverage
inside planned members. It is not JVM basic-block coverage. The existing
Mallory coverage collector can be combined at the campaign layer.

Run focused tests after building the original engine:

```bash
python3 -m unittest Mallory.native_graphchecker_feedback.test_feedback -v
GC_NATIVE_FIXTURE=/path/to/unchanged-junit-fixture \
GC_NATIVE_ENGINE_JAR=/path/to/pinned-engine.jar \
  python3 -m unittest Mallory.native_graphchecker_feedback.test_feedback -v
```

The synthetic native-row fixture proves three typed edges in a planned
three-region closure: a paired cross-process `WIRE`, an explicit message-start
anchor, and an exact same-process versioned `STATE` read. With the handoff
expression withheld, the original planner drops the sender; the output keeps
only the state edge. The unchanged JUnit fixture proves native session ingress
and repeat-run zero delta. A second synthetic target occurrence proves the
two exact plans remain separate while the target-set score is combined.
Neither fixture proves that HDFS, HBase, Solr, or
ZooKeeper adapters currently publish complete physical transport pairings.

Current compatibility limits: sessions must be single-session iterations;
the source-built original engine must include its post-run `explore` sources;
this module does not inject faults. It does not
infer program order from `threadKey` because activation rows do not state an
order. Native sessions that record no standalone `ReadRow` produce no `STATE`
edge even if the VM expression log has a guarded `ReadFromExpression`; the
original planner may still use that expression through its own rules. A plan
with nonempty `gaps`, `waiting`, `exposed`, or `truncated` is reported as such;
the bridge does not label it a complete causal reconstruction.
