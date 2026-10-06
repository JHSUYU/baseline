# HBASE-22: namespace region quota check

The selected site is recorded as
`NamespaceStateManager.checkAndUpdateNamespaceTableCount(TableName,int):172`
in the checklist. In the original HBase 2.6.6 source, the second quota
predicate is at lines 165–167; line 172 reads the current count while
constructing that predicate's exception message. The check compares current
namespace region count plus the new table's region count against
`TableNamespaceManager.getMaxRegions` and throws
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
When repeated system-namespace faults after the same first-fault site abort
both masters and lose the guard, the queue lowers the priority of that
failure class so other observed I/O sites receive budget.

All mutable files are inside this case directory. `hbase22_fuzz`,
`hbase22_watchdog`, and `hbase22_supervisor` are the persistent tmux sessions.

## Completed campaign and source review

The independent graph-free campaign completed its 80/8 budget. All 80 trial
plans matched and applied every requested runtime I/O fault (446 applied
events). In 63 trials the first evaluation of the region quota comparison
occurred after the final fault; those 63 original JUnit executions passed.
The other 17 trials lost the selected check and were excluded from feedback.
All 63 admitted quota exceptions reported requested regions 5, maximum 5,
and current count 1, exactly as in the healthy JUnit. No new exact target
exception was observed. The elapsed time for the healthy run plus 80 current
trials was 5,071.41 seconds. Relative to the healthy run, cumulative JaCoCo
coverage added two production methods and nine branches; two stable I/O
sites appeared. Recomputing coverage from archived `.exec` files matched the
checkpoint. The final 16 trials added no production coverage or stable I/O
family, so the conditional 128/10 extension was not taken.

Source inspection explains the outcomes: `CreateNamespaceProcedure` retries
`IOException` in its update-ZooKeeper state. Namespace watcher read failures
can abort a master and prevent the target guard from executing; those runs
are the 17 target-lost cases, not target exception candidates. The original
JUnit intentionally asks for five new regions when one already exists under
a limit of five, so its caught `QuotaExceededException` is expected. The
campaign did not establish a new bug.

Instrumentation provenance: source commit
`d5f63f523c065f963992ea4e74db268d17816631`; original HBase server JAR
SHA256 `27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696`;
original test JAR SHA256
`b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5`;
case-local ByteBuddy agent source SHA256
`a79debd92f6acd61b373d31db5a837482917d3f777457909f83ecc0efa8377a0`;
agent JAR SHA256
`0bc1f64cd8d2c5f3f3a83492f2f8e93323819f501a041f8f5a026ab2df03b16a`.
The HBase server JAR contains no GraphChecker/GREYGRAPH/CrashFuzz classes.
The preserved checkpoint, original JUnit logs, fault logs, and JaCoCo files
are in `evidence/hbase22-coverage-io-80.tar.gz`, SHA256
`3a432c4b3ec80e38b2d39924b401a2029793e4b5abc929f2e04fe8ad9754f77b`.
