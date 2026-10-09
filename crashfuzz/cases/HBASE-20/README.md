# HBASE-20: coprocessor check

This check is `ModifyTableProcedure.preflightChecks` at line 139. The unchanged
original `TestModifyTableProcedure#testModifyWillNotReopenRegions` evaluates it
and intentionally catches the corresponding `HBaseIOException` in test 5
(lines 673–684).
HBASE-19 and HBASE-20 share one isolated JUnit fault campaign because both
checks occur in that test. The two case `result.json` files separately count
post-fault guard reachability and target exceptions. Method, instrumentation,
runtime dependency, and checkpoint details are in [HBASE-19](../HBASE-19/README.md).

The shared campaign completed 80 strict plans and 512 matched faults in
4943.42 seconds including the healthy run. The HBASE-20 guard and its expected
coprocessor rejection both occurred after the final fault in all 80 trials;
all 80 original JUnit runs passed. Its exception signature remained identical
to the healthy run, so there is no new bug candidate for this check. The
shared audit, coverage details, and archived evidence are in HBASE-19.
