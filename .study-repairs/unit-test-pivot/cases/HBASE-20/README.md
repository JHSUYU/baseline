# HBASE-20: coprocessor check

This check is `ModifyTableProcedure.preflightChecks` at line 139. The unchanged
original `TestModifyTableProcedure#testModifyWillNotReopenRegions` evaluates it
and intentionally catches the corresponding `HBaseIOException` in test 5.
HBASE-19 and HBASE-20 share one isolated JUnit fault campaign because both
checks occur in that test. The two case `result.json` files separately count
post-fault guard reachability and target exceptions. Method, instrumentation,
runtime dependency, and checkpoint details are in [HBASE-19](../HBASE-19/README.md).
