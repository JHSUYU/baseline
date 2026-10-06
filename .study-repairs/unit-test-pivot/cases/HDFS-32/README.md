# HDFS-32: independent recorder replay pending

The earlier 3 fault trials used a static-analysis/region-woven recorder. Those trials are preserved in [legacy-graph-result.json](legacy-graph-result.json) and excluded from the current graph-independent campaign. The original cluster JUnit and target check must be recorded with case-local I/O/coverage probes before new trials count.

Source review corrected the workload mapping. The prior
`TestDeleteBlockPool#testDfsAdminDeleteBlockPool` first removes one NameNode
from the DataNode configuration and then verifies the DFSAdmin command. The
same original test class has `testDeleteBlockPool`, a two-NameNode,
two-DataNode embedded cluster test that explicitly calls `deleteBlockPool`
while the block pool is still running, expects this exact `IOException`,
refreshes Namenodes, and then verifies permitted deletion. That is the
workload for the independent healthy probe. Since the healthy test expects
the guard exception, an injected run must distinguish a new unexpected
failure from those original expected calls before claiming a bug. No new
graph-independent fault trial has been counted yet.
