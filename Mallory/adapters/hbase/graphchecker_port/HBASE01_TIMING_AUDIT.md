# HBASE-01 frozen-campaign timing audit (2026-10-13)

This is a read-only audit of the node1 v3 campaign at
`/proj/silentfailure-PG0/ZhenyuLi/mallory-hbase01-v3`. Its runtime, weaver,
scope, config, core and checkpoint remain pinned. Measurements below use the
13 complete trial receipts r0000–r0012, sampled while the campaign was
running. The campaign later reached its 1800-second trial budget with 39
fault trials; the timing statistics below remain an early-run sample.

| Stage | Median seconds | Measurement |
| --- | ---: | --- |
| Original JUnit JVM | 45.6 | `result.json.elapsed_seconds`; agrees with `process.json` to `stderr.log` file times |
| JVM end to graph feedback | 42.8 | `stderr.log` to `graphchecker-feedback.json` file times; includes trace window scan and graph analysis |
| Feedback to raw/window gzip sealed | 24.0 | `graphchecker-feedback.json` to `graphchecker-trace.jsonl.gz` file times |
| Window gzip to graph gzip sealed | 6.3 | gzip file times |
| Graph gzip to result write | 1.1 | `graphchecker-graph.jsonl.gz` to `result.json` file times |
| Result write to next trial start | 29.3 | `result.json` to next `process.json` file times; includes full evidence verification and scheduler/checkpoint |

The median archive wall interval from `process.json` to `result.json` is
119.2 seconds; with the inter-trial interval the observed cycle is about
148.5 seconds. The file-time stages are approximate because completion times
are inferred from modification times. They do not individually time the
functions. The explicit JUnit duration is a direct receipt field.

In r0010, `raw_trace` and `window_trace` receipts each record exactly
840,627,896 content bytes and equal content SHA-256; the two gzip files each
occupy 15,796,065 bytes. The graph is 137,970,040 content bytes and
5,872,500 gzip bytes. Source inspection shows `_archive_jsonl` verifies each
gzip by re-reading its uncompressed content, and `verify_trial_artifacts`
reads/decompresses it again after `result.json` is written. These checks are
sound but repeat work on two identical traces.

Reusable optimization for a later pinned release:

1. Add explicit phase durations to each result receipt.
2. When raw and window bytes are equal by digest and size, seal one gzip
   archive, hardlink both logical names and verify its inode once while
   checking both logical receipts. Retain both logical artifact references.
3. Pass the verified archive digest from `_archive_jsonl` into the final
   receipt check instead of decompressing the same newly written archive
   again. Keep full byte verification on campaign resume.
4. Cache Soot application facts per HBase bytecode, ordered classpath and
   planner version, then run each target's backward demand from the cached
   facts. The v3 planner log reports 38,732 methods indexed in 88.9 seconds
   and target scope selected in 112.9 seconds total. The full weave receipt
   appeared about 109 seconds after the node1 prepare started.
5. Cache a validated healthy closure summary per selected target set. Current
   `analyze_trial` expands the same 840 MB healthy gzip to `/dev/shm` and
   `TrialGraphMain` parses it again for every fault trial. `TrialGraph.feedback`
   consumes only healthy node families, edge families and coverage sites up to
   target cutoffs for novelty; a versioned, hashed summary could replace this
   repeated prior-trace parse while keeping the original healthy archive for
   replay and audit. Validate equivalent feedback against the full trace in
   tests before using the summary in a campaign.

These changes preserve the trial budget, exact GraphChecker relations and
durable trace evidence. None is applied to the active HBASE-01 campaign.
