# hdfs-adhoc-11 MC-4

TLC files of this finding: the specification modules (`*.tla`), the config that produced the counterexample
(`G_S4a_backward.cfg`, root module `MCGated.tla`), and the counterexample log TLC wrote (`counterexample-G_S4a_backward.out`).
Originally run with `TLC2 Version 2026.10.24.013619 (rev: 2ef2af8)` on JDK 21.0.13; the same jars are pinned in `../../../../tlc/` (`SHA256SUMS`).

Rerun from this directory (Java 11+):

```
java -XX:+UseParallelGC -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-11-MC-4 -config G_S4a_backward.cfg MCGated.tla
```

TLC must report `Invariant TargetSafeBackward is violated`; the trace follows in its output (and in the counterexample log).
State counts can differ from the log when the worker count differs.
Checked 2026-10-29: rerun (4 workers): Invariant TargetSafeBackward is violated; distinct states 2826.
