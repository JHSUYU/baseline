# HBASE-19/20 descriptor-read full stage

This package stages separate 80-trial, 3600-second, maximum-three-fault Mallory campaigns for the existing MiniHBaseCluster selector
`TestModifyTableProcedure#testModifyTableWithCoprocessorAndColumnFamilyPropertyChange`.
No JVM or fault trial was run while preparing it. Dispatch owns the node1 capacity gate.

## Exact target and prior runtime evidence

The HBase 2.6.6 test at `TestModifyTableProcedure.java:737-747` reads the old table descriptor with `Admin.getDescriptor`, modifies only the column-family compression property, and constructs `ModifyTableProcedure` directly with `reopenRegions=false`. The constructor calls `preflightChecks` before procedure submission. HBASE-19 retains `@133:branch:7` and `@135:throw:1` (family count); HBASE-20 retains `@138:branch:8` and `@139:throw:1` (coprocessor descriptors). Both throws have class `HBaseIOException`.

The pinned `calibration_v8` result for each case records one passing JUnit test, the selected guard reached, and no selected throw. The offline causal audits report 46 eligible generic RPC doors before the guard, zero observed paths from a door into either guard, and zero closure edges. This is a limitation of that graph and fault model. It does not invalidate the existing test's exact guard reach.

The v8 HBASE-19 trace shows `MasterService.GetTableDescriptors` sent at sequence 2960, received on `master0` at 2965, and completed at 2983; the HBASE-19 guard occurs at 2998 on the test thread. The trace alone does not prove table or descriptor identity. The source bridge from `getDescriptor(tableName)` at test line 737 to the descriptor passed to the constructor at lines 738-747 makes the read a concrete pretarget candidate. HBASE-20 uses the same test path, with its distinct exact check.

## Fault point and limits

The new site files instrument only `MasterRpcServices.getTableDescriptors:1114`, immediately before `master.listTableDescriptors(...)`. A checked `IOException` there is caught and wrapped in `ServiceException` at line 1124; the HBase admin descriptor read calls `RpcRetryingCallerImpl.callWithRetries`, whose loop can retry after a retryable failure. This permits a service-level fault on a descriptor read while leaving the selected guard unchanged. The service method is specific to `GetTableDescriptors`; it still may serve more than one table or more than one invocation. A source and v8 timing review cannot establish that a given injected door is the exact read that supplies the later procedure.

The full configurations use one explicit `EXCEPTION` site, strict event-time graph settings, and bounded outside-closure exploration. They do not promote the v8 generic RPC door or claim a causal path that was not observed. A fault's table/request identity, successful retry, and postfault exact guard retention must be read from the new trial events and test outcome before any causal or bug claim. An injected fault that causes setup failure or loses the target remains a negative trial.

## Fresh healthy and execution

The old lane6v2 runtime paths are absent and this package pins a newer agent, adapter, runner, core release, and site file. Therefore the v8 seed is historical selector/target evidence only. Each full campaign starts with its own fresh healthy `r0000`; `auto_promote_if_healthy` requires runtime target and class attestation before fault trials. No extra standalone calibration is staged.

On node1, after dispatch has checked its independent disk, RAM, JVM, and lock gate:

```sh
python3 Mallory/adapters/hbase/pilot/HBASE-19-20-descriptor-read-v1/preflight.py
Mallory/adapters/hbase/pilot/HBASE-19-20-descriptor-read-v1/run_full.sh 19
Mallory/adapters/hbase/pilot/HBASE-19-20-descriptor-read-v1/run_full.sh 20
```

The runners use distinct output directories under `data/mallory/HBASE-19` and `data/mallory/HBASE-20`. A prior `budget_exhausted` or `queue_exhausted` result is never rerun. Per the study's completion rule, only those two terminal statuses complete a full campaign, regardless of graph paths or selected throws. Keep source review and causal quality separate from terminal completion.

`preflight.py` reads only files. It validates the v8 receipts, exact target/site files, HBase source and class SHA-256 values, all runtime artifacts, Xerial codec override, core manifest, and full budget. Its passing result is a staging check; it is not fresh healthy or injected runtime evidence.
