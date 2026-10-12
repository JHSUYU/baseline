# HBASE-24 abort watcher source preflight

This is an isolated **healthy-only** configuration for the unchanged
`TestZKProcedure#testMultipleMembers` JUnit. It stages a checked
`ConnectionLossException` at `ZKProcedureMemberRpcs.watchForAbortedProcedures`
line 137. The existing HBase adapter can name the member because the site
catalog makes that method a region; `start(memberName, listener)` registers the
same controller before calling it. No adapter or production source changed.

The offline [source receipt](source-receipt.json) pins source, local agent and
adapter JARs, config, site catalog, and prior results. Run
`python3 verify_bytecode.py` for a JVM-free check of the compiled call,
`KeeperException` catch, member startup call order, and injected exception
type. The `healthy.json` runtime paths are node1 lane9 staging destinations;
dispatch must synchronize `sites.json` to its configured `site_file` and
verify every runtime SHA before starting a healthy run.

Admit a fault pilot only after that healthy run passes the JUnit and records a
named line-137 door before the exact PB-magic check at line 205 for the **same
member**, with the required observed causal path. A postfault pilot must
retain the check on that member, not count another member's check. The prior
line-204 data-read pilots applied their faults, but same-member execution
returned through the `KeeperException` catch before the guard; their two
postfault target checks belonged to other members. The abort watcher fault is
not a source-level explanation for malformed PB data, so an exact target
exception would still require a separate causal replay and source argument.
