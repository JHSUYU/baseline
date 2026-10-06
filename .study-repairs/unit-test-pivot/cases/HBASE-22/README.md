# HBASE-22: namespace region quota check

The selected check is the second quota condition in
`NamespaceStateManager.checkAndUpdateNamespaceTableCount(TableName,int)` at
`hbase-server/src/main/java/org/apache/hadoop/hbase/namespace/NamespaceStateManager.java:172`.
It compares current namespace region count plus the new table's region count
against `TableNamespaceManager.getMaxRegions` and throws
`QuotaExceededException` if the sum is too large. The earlier table-count
condition is a different check and is recorded separately.

The unchanged original Apache HBase 2.6.6
`TestNamespaceAuditor#testTableOperations` runs a two-master embedded
MiniHBaseCluster. It defines max regions 5 and max tables 2. After the first
table occupies one region, its second table request asks for five more
regions. The original test **expects and catches** the resulting target
`QuotaExceededException`, then retries with four regions successfully. Its
third table request intentionally hits the earlier table-count condition.
Therefore an occurrence of the target exception alone is not a new bug.

The case-local ByteBuddy agent in `work/src/HBase22Agent.java` records exact
method invocation IDs, region-guard evaluation, table name, requested region
count, and outcome. It observes related ZooKeeper namespace create, update,
children-read, and data-read I/O at their runtime call sites. A fault plan
matches I/O family, exact znode path, production call site, and hit ordinal
in order; applied faults throw ZooKeeper I/O exceptions. JaCoCo records
production method and branch coverage for the target and three related
namespace classes. No GraphChecker prewoven class, region skeleton, static
map, closure, or graph feedback is used in this campaign.

The graph-free campaign uses the original JUnit as its workload, with a
default budget of 80 trials and eight ordered faults. If one of the final 16
strict target-retaining trials adds a production method, branch, or stable
I/O family, the same checkpoint extends to 128 trials and ten faults.
Only fully matched and applied trials that evaluate the selected guard after
their final fault contribute coverage and I/O feedback. A region-quota throw
with the same table and requested region count as the healthy run is labeled
expected. A new signature is only a candidate pending source review and
replay. The campaign checkpoint and per-trial results are written atomically.

All mutable files are inside this case directory. `hbase22_fuzz`,
`hbase22_watchdog`, and `hbase22_supervisor` are the persistent tmux sessions.
