# HBASE-19 and HBASE-20: modify-table checks

Both selected checks are in `ModifyTableProcedure.preflightChecks` from the
unchanged Apache HBase 2.6.6 source commit
`d5f63f523c065f963992ea4e74db268d17816631`:

- HBASE-19, line 135: adding or removing column families when
  `reopenRegions=false` throws `HBaseIOException`.
- HBASE-20, line 139: modifying a coprocessor when `reopenRegions=false`
  throws `HBaseIOException`.

The original embedded-cluster JUnit
`TestModifyTableProcedure#testModifyWillNotReopenRegions` reaches both checks.
Its test 3 (lines 637–648) deliberately adds `NewCF` and catches the HBASE-19
exception. Its test 5 (lines 673–684) deliberately adds a coprocessor and
catches the HBASE-20 exception.
These are healthy expected exceptions, not bugs. The successful fault-free
run took 57.83 seconds, executed both guards, and passed 1/1 JUnit test.

The case-local ByteBuddy agent records two `getColumnFamilyCount` calls within
each preflight invocation to prove the HBASE-19 comparison was evaluated. It
records the `isCoprocModified` result to prove HBASE-20 evaluation. Call IDs
associate guard events and exact exceptions. It intercepts real metadata
file-read and file-write method boundaries in `FSTableDescriptors`, restricted
to the test table. A runtime fault selector consists of I/O family, stable
logical table path, production call site, and hit ordinal. Three checked
`IOException` variants are available. The `FS_READ` hook is at entry to
`getTableDescriptorFromFs`; the `FS_WRITE` hook is at entry to
`updateTableDescriptor`, before its internal read and write. Thus the latter
models failure of a descriptor-update I/O operation, not a partial disk write.
JaCoCo records production method and
branch coverage in `ModifyTableProcedure`,
`AbstractStateMachineTableProcedure`, and `FSTableDescriptors`. There is no
GraphChecker JAR, prewoven class, skeleton, static map, closure, or graph
feedback in the agent, runner, or campaign.

The unchanged HBase server and test JARs have SHA256
`27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696`
and `b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5`.
The case-local agent source and built JAR have SHA256
`817b3e55efde17a34bd20206efe51add0bc109a184c936d7346c79b79f134da9`
and `8cba969e41b961fa46339ba0f7130a0263ee22ce3d16f935fdd944453c1a8bc2`.

One graph-free CrashFuzz-style campaign executes the original JUnit afresh per
fault plan, with a default 80-trial budget and at most eight ordered faults.
If one of its final 16 strict target-retaining trials adds production method
or branch coverage or a stable I/O family, the same checkpoint extends to
128 trials and ten faults. All fault steps must match their recorded selector
and kind. HBASE-19 and HBASE-20 separately record whether their guard executes
after the final fault and whether the exact target exception differs from the
healthy signature. A target exception is only a candidate until source review
and replay. The checkpoint and both case results are replaced atomically after
each trial; tmux sessions `hbase1920_fuzz` and `hbase1920_supervisor` resume
after interruption without repeating completed rounds. All mutable run data
is inside `HBASE-19/work`, with separate result files for the two check IDs.

The original JUnit changes a column family's compression to SNAPPY and
reopens its region. This host lacked `libsnappy.so.1`, so an initial diagnostic
healthy run stalled during that reopen. The successful run uses only a local
unpacked Ubuntu Jammy `libsnappy1v5` package, version `1.1.8-1build3`, from
`http://us.archive.ubuntu.com/ubuntu`; package SHA256
`245a0f6b5a9dda0bee20c6a62f78a88bf885be831b1f1108f19231b2a97a797e`.
The native library and `libhadoop.so` paths are set only for this JUnit
process. No host library was installed or modified. The first two diagnostic
runs, one exposing a probe access error and one the missing Snappy dependency,
are excluded from campaign counts.

## Completed campaign

The campaign finished 80 distinct fault plans (maximum depth eight) in
4943.42 seconds including the healthy run. All 512 ordered faults matched
their exact runtime selectors and kinds. All 80 original JUnit runs passed,
and both target guards executed after the final fault in all 80 runs. The
expected HBASE-19 column-family exception occurred after the final fault in
46 runs; the expected HBASE-20 coprocessor exception did so in all 80. The
remaining HBASE-19 plans place their last fault after test 3 but still reach
later column-family comparisons. No post-fault target exception differed from
the healthy signature, so neither check yielded a new bug candidate.

The JaCoCo union added zero production methods and two branches over the
healthy run, in `ModifyTableProcedure`'s I/O exception retry and rollback
handling (source lines 303 and 340). No stable I/O site was new. The final
16 strict, target-retaining trials added no production coverage or stable I/O
family, so the conditional 128-trial extension was not taken. Every trial was
rechecked against its raw log for ordered fault identity, post-fault guard
reachability, exact exception signature, JUnit status, and elapsed time; the
coverage union was independently recomputed. The 80-trial checkpoint, logs,
and JaCoCo execution files are archived in
[`evidence/hbase1920-coverage-io-80.tar.gz`](evidence/hbase1920-coverage-io-80.tar.gz)
(SHA256 `34c4b825bcbdb54f5620ac831595840ace0e9a2e5727435c76bfea857a009199`).
