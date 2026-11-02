# hdfs-adhoc-12 MC-4

TLC files of this finding: the specification modules (`*.tla`), the config that produced the counterexample
(`staleissuer_alllost.cfg`, root module `MCRefine.tla`), and the counterexample log (`counterexample-staleissuer_alllost_bfs.out`). Originally run
with `TLC2 Version 2026.10.24.013619 (rev: 2ef2af8)` on JDK 21.0.13; the same jars are pinned in `../../../../tlc/` (`SHA256SUMS`). Whether this finding is
a verified bug is in `../../../VERIFIED-BUGS.md` (and the classifications).

```
java -XX:+UseParallelGC -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -metadir /tmp/tlc-hdfs-adhoc-12-MC-4 -config staleissuer_alllost.cfg MCRefine.tla
```

TLC must report `Invariant TargetSafeAllLost is violated`. State counts can differ from the log when the worker count differs.
Checked 2026-11-02: rerun (4 workers): Invariant TargetSafeAllLost is violated; distinct states 167723.
