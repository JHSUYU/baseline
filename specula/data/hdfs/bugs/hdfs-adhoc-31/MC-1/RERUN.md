# hdfs-adhoc-31 MC-1

TLC files of this finding: the specification modules (`*.tla`), the config that produced the counterexample
(`MC_hunt_s1_inflight_transfer.cfg`, root module `MC.tla`), and the counterexample log (`counterexample-MC_diag_s1_hook_nnreject.out`). Originally run
with `TLC2 Version 2026.10.24.013619 (rev: 2ef2af8)` on JDK 21.0.13; the same jars are pinned in `../../../../tlc/` (`SHA256SUMS`). Whether this finding is
a verified bug is in `../../../VERIFIED-BUGS.md` (and the classifications).

```
java -XX:+UseParallelGC -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-31-MC-1 -config MC_hunt_s1_inflight_transfer.cfg MC.tla
```

TLC must report `Invariant TargetSafe is violated`. State counts can differ from the log when the worker count differs.
Checked 2026-11-02: rerun (4 workers): Invariant TargetSafe is violated; distinct states 2796.
