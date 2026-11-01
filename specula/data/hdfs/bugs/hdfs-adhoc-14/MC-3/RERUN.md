# hdfs-adhoc-14 MC-3

TLC files of this finding: the specification modules (`*.tla`), the config that produced the counterexample
(`MC_hunt_s3_ha_key_source.cfg`, root module `MC.tla`), and the counterexample log TLC wrote (`counterexample-s3_ha_key_source_r1.out`).
Originally run with `TLC2 Version 2026.10.24.013619 (rev: 2ef2af8)` on JDK 21.0.13; the same jars are pinned in `../../../../tlc/` (`SHA256SUMS`).

Rerun from this directory (Java 11+):

```
java -XX:+UseParallelGC -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-14-MC-3 -config MC_hunt_s3_ha_key_source.cfg MC.tla
```

TLC must report `Invariant TargetSafe is violated`; the trace follows in its output (and in the counterexample log).
State counts can differ from the log when the worker count differs.
Checked 2026-10-30: rerun (4 workers): Invariant TargetSafe is violated; distinct states 83124.
