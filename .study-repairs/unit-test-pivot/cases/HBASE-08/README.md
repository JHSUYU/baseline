# HBASE-08: namespace descriptor lookup

The selected check is `ClusterSchemaServiceImpl.getNamespace(String)` at
`hbase-server/src/main/java/org/apache/hadoop/hbase/master/ClusterSchemaServiceImpl.java:116`.
It reads `TableNamespaceManager.get(name)` and throws
`NamespaceNotFoundException` when the returned descriptor is null.

The unchanged original `TestNamespaceAuditor#testTableOperations` runs in a
two-master MiniHBaseCluster. It creates a named namespace and tables, exercises
namespace quota limits, and then cleans them up. The current instrumented
healthy run passed in 48.67 seconds. It reached the selected method 12 times,
with no selected exception, and observed 16 namespace-related ZooKeeper I/O
events. The exact runtime selectors are `I/O family + znode path + production
call site + hit ordinal`; the probe logs global order, matches each requested
fault in order, and throws the corresponding ZooKeeper I/O failure. These
events come from `ZKUtil.createWithParents`, `updateExistingNodeData`, and
`getChildDataAndWatchForNewChildren` when called by `ZKNamespaceManager`.
Faults in the namespace creation path can therefore change cache update and
watcher behavior before subsequent lookups.

`work/src/HBase08Agent.java` is a case-local ByteBuddy agent; `work/run.sh`
launches the original JUnit in a fresh data directory, with JaCoCo enabled for
four related production classes. `work/campaign.py` uses observed I/O from
each run and method/branch coverage changes to prioritize another ordered
fault sequence. Only fully matched/applied trials that reach the selected
method after the final fault contribute feedback. A selected exception is
merely a candidate until reproduced and checked against source behavior.
The campaign atomically updates `work/checkpoint.json` and `result.json`
after every trial. The tmux session is `hbase08_fuzz`.

Five earlier fault trials remain in `result.json` and
`evidence/legacy-trials/`. Four were strictly applied and retained the target.
Their scoped coverage measurements use different builds and are reported
separately from this homogeneous JaCoCo campaign. The current campaign's
default is 64 new trials with up to six faults, with a possible same-checkpoint
extension to 128/eight if late rounds still expose new production coverage or
I/O identities. `result.current_campaign` separates its trial and coverage
counts from the five historical trials.

## Instrumentation provenance

The runtime classpath in `work/run.sh` uses the Apache HBase 2.6.6 binary
distribution under `/users/ZhenyuLi/.baseline-deps/hbase-2.6.6`, including
the original `hbase-server-2.6.6-tests.jar`. The production server JAR is
SHA-256 `27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696`;
the test JAR is
`b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5`;
the ZooKeeper integration JAR is
`6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957`.
The corresponding read-only source checkout is revision
`d5f63f523c065f963992ea4e74db268d17816631` (`rel/2.6.6`).

The only instrumentation supplied to the JVM is the case-local ByteBuddy
`agent.jar` built from `work/src/HBase08Agent.java` (SHA-256
`5d30e7bf93db0d7bdeb9f3b1da7ef2f2db2a1fe76cd5bf65082ea910eb8c78af`)
and JaCoCo 0.8.15. The I/O identities are recorded at runtime by that agent;
the case uses no GraphChecker prewoven JAR, region skeleton, static map,
closure, or graph feedback. The source checkout is used only for inspecting
the selected check and its original JUnit.
