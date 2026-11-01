# hdfs-adhoc-20 MC-2

TLC files of this finding: the specification modules (`*.tla`), the config that produced the counterexample
(`MC_hunt_s2_ha_crash_failover.cfg`, root module `MC.tla`), and the counterexample log TLC wrote (`counterexample-MC_hunt_s2_ha_crash_failover_bfs.out`).
Originally run with `TLC2 Version 2026.10.24.013619 (rev: 2ef2af8)` on JDK 21.0.13; the same jars are pinned in `../../../../tlc/` (`SHA256SUMS`).

Rerun from this directory (Java 11+):

```
java -XX:+UseParallelGC -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-20-MC-2 -config MC_hunt_s2_ha_crash_failover.cfg MC.tla
```

TLC must report `Invariant TargetSafe is violated`; the trace follows in its output (and in the counterexample log).
State counts can differ from the log when the worker count differs.
Checked 2026-10-30: rerun (4 workers): Invariant TargetSafe is violated; distinct states 210496.
