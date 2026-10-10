# HDFS-37: normal DataNode rollback, full fault campaign stage

The selected instrumented check sites are `DataStorage.doRollback` at
`DataStorage.java:940–941`. The `InconsistentFSStateException` statement
starts at line 942 and its bytecode throw site maps to line 947. This package reuses
the isolated, SHA-pinned `TestDFSRollback#testRollback` normal phase. The
healthy-only run passed JUnit 1/0/0, reached both selected branches on
`hdfs-cluster-2/dn0`, and did not take the selected throw. The later invalid
rollback phase of the original test is deliberately absent because its throw
is expected behavior.

The recorded request and response RPC edges connect the DataNode
`BPServiceActor.retrieveNamespaceInfo` `versionRequest` door at line 260 and
the NameNode `Server$RpcCall.run` door at line 1246 to the target region.
These are the two initial `EXCEPTION` injection candidates. Hadoop source
shows that the DataNode catches `IOException` at `versionRequest` and retries.
The `StorageInfo.readPropertiesFile` door at line 272 occurs inside rollback
before the check, but it is outside the target's backward closure and an
injected `IOException` likely aborts this attempt. The scheduler excludes it
by setting `explore_outside_closure=false` with no static or validated
recovery sites.

The 80 trial, 3600 second, three fault budget is a cap. The queue can exhaust
earlier. Every full run begins with its own healthy seed and admits faults
only if its exact target identity, JUnit result, observed path and runtime
attestation pass. A target-losing trial is recorded but not expanded. An
exact target exception under injection is a candidate until replay and source
review; this package claims no new bug.

The prior healthy observation is bundled with its SHA-sealed archive and
receipt. `preflight.py --static` verifies the pinned healthy trace, source lines,
closure edges, initial scheduler output and config without Java. On node2,
`preflight.py --runtime` also checks the isolated compiled source and permits
an existing output only when its config and checkpoint match for resume.
Dispatch alone may set `MALLORY_HDFS37_FULL_NODE2_GRANT=1` and run
`run_full.sh`. The runner takes the shared node2 HDFS lane lock.
