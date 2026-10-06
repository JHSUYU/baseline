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
Its test 3 deliberately adds `NewCF` and catches the HBASE-19 exception. Its
test 5 deliberately adds a coprocessor and catches the HBASE-20 exception.
These are healthy expected exceptions, not bugs. The successful fault-free
run took 57.83 seconds, executed both guards, and passed 1/1 JUnit test.

The case-local ByteBuddy agent records two `getColumnFamilyCount` calls within
each preflight invocation to prove the HBASE-19 comparison was evaluated. It
records the `isCoprocModified` result to prove HBASE-20 evaluation. Call IDs
associate guard events and exact exceptions. It intercepts real metadata
file-read and file-write method boundaries in `FSTableDescriptors`, restricted
to the test table. A runtime fault selector consists of I/O family, stable
logical table path, production call site, and hit ordinal. Three checked
`IOException` variants are available. JaCoCo records production method and
branch coverage in `ModifyTableProcedure`,
`AbstractStateMachineTableProcedure`, and `FSTableDescriptors`. There is no
GraphChecker JAR, prewoven class, skeleton, static map, closure, or graph
feedback in the agent, runner, or campaign.

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
