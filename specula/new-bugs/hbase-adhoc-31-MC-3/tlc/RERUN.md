# hbase-adhoc-31-MC-3: rerun the TLC counterexample

Files: the specification modules (`*.tla`), the config that produced the counterexample (`MC_hunt_s3_late_register.cfg`, root module `MC.tla`), and the counterexample log (`counterexample-MC_hunt_s3_late_register.out`). TLC `2026.10.24.013619 (rev: 2ef2af8)` on JDK 21; the jars are pinned in `../../../data/tlc/` (`SHA256SUMS`).

```
cd new-bugs/hbase-adhoc-31-MC-3/tlc   # from specula/
java -XX:+UseParallelGC -cp ../../../data/tlc/tla2tools.jar:../../../data/tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hbase-adhoc-31-MC-3 -config MC_hunt_s3_late_register.cfg MC.tla
```

TLC must report `Invariant TargetSafe is violated`. State counts can differ from the log when the worker count differs.
