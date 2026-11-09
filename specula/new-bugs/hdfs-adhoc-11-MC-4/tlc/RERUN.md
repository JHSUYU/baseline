# hdfs-adhoc-11-MC-4: rerun the TLC counterexample

Files: the specification modules (`*.tla`), the config that produced the counterexample (`G_S4a_backward.cfg`, root module `MCGated.tla`), and the counterexample log (`counterexample-G_S4a_backward.out`). TLC `2026.10.24.013619 (rev: 2ef2af8)` on JDK 21; the jars are pinned in `../../../data/tlc/` (`SHA256SUMS`).

```
cd new-bugs/hdfs-adhoc-11-MC-4/tlc   # from specula/
java -XX:+UseParallelGC -cp ../../../data/tlc/tla2tools.jar:../../../data/tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-11-MC-4 -config G_S4a_backward.cfg MCGated.tla
```

TLC must report `Invariant TargetSafeBackward is violated`. State counts can differ from the log when the worker count differs.
