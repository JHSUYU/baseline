# HBASE-01: dead-server guard during meta lookup

In HBase 2.6.6, `ConnectionImplementation.locateRegionInMeta` reads a region server from `hbase:meta`. At source line 1104 it calls `isDeadServer(serverName)`; a `true` result throws `RegionServerStoppedException` at line 1105. The original selected line 1106 continues the exception message. The check compares meta's location with the connection's dead-server listener. A selected exception is an event to investigate, not by itself a correctness bug.

## Graph-independent original-JUnit campaign

The counted workload is the unchanged `org.apache.hadoop.hbase.client.TestConnectionImplementation#testMetaLookupThreadPoolCreated`, launched through JUnit Platform on its two-region-server `MiniHBaseCluster`. Its source sets five client retries, yielding six attempts at each observed I/O door. The healthy run passed in 44.00 seconds; for the selected test table, it observed one table-state Get RPC before the lookup and one reverse meta scan inside the lookup. The selected `isDeadServer` guard returned `false` once.

The case-local [ByteBuddy agent](native/src/HBase01Agent.java) probes the selected table's `ClientServiceCallable.doGet`, `ReversedClientScanner` response through `ClientScanner.next`, and the exact `isDeadServer` call inside `locateRegionInMeta`. The [runner](native/run.sh) registers JaCoCo before ByteBuddy so the coverage report analyzes original production class IDs. [campaign.py](native/campaign.py) chooses ordered IOException, SocketTimeoutException, EOFException, and ConnectException sequences from I/O observed in the healthy request. Every trial records elapsed time, selector order and match/application, same-thread guard after the final fault, exact selected-method exit exceptions, JUnit outcome, and JaCoCo production coverage. Only strict sequences retaining the guard contribute to coverage feedback.

| Evidence | Result |
| --- | ---: |
| Counted fault trials | 80 unique ordered sequences |
| Requested / matched / applied fault events | 220 / 220 / 220 |
| Strict sequences / post-final-fault target / original JUnit passed | 80 / 80 / 80 |
| Selected `RegionServerStoppedException` trials | 0 |
| JaCoCo branches in six production classes | 202 healthy → 243 union (+41) |
| Total counted JVM time, including healthy baseline | 3,952.83 seconds |

The production branch gain arose at r001 (Get `IOException`, +29), r004 (Get `ConnectException`, +1), and r005 (scan response `IOException`, +11). Later exception orderings and mixed Get/scan sequences, including four strict eight-fault trials with four Get and four scan faults, added no branches. Source line 1104 was covered on the safe branch; the selected throw at line 1105 was not covered. The last eight trials added no production method, branch, or stable I/O family, so the authorized conditional 128-trial/max-ten-fault extension was not opened. The default 80-trial/max-eight-fault budget was completed. These JaCoCo counts cover `ConnectionImplementation`, `ClientScanner`, `ClientServiceCallable`, `ClusterStatusListener`, `RpcRetryingCallerImpl`, and `MetaTableAccessor`; they are not whole-system coverage.

The observed I/O faults drive retries but do not themselves add the meta server to `ClusterStatusListener.deadServers`. The bounded result therefore supports no target-exception or correctness-bug claim for this fault family. The [case ledger](result.json) preserves per-trial selectors, exact exceptions, logs, and coverage. The [native evidence archive](evidence/hbase01-native-evidence.tar.gz) and [manifest](evidence/native-manifest.json) contain the counted logs, JaCoCo files, source probes, runner, and an uncounted exploratory healthy run. That exploratory run exposed an unrelated `hbase:namespace` scan during cluster startup; the final agent filters on the selected test table and the counted healthy run is `native/healthy_final.log`. A disjoint late block was precomputed in separate JVM data directories, then admitted in order with coverage feedback after earlier trials.

## Instrumentation provenance and earlier evidence

No counted run used a GraphChecker JAR, prewoven production classes, region skeletons, a static scope map, a static aggregate, or closure. The counted runtime uses only the unchanged HBase distribution, JUnit Platform, the case-local ByteBuddy probe, and JaCoCo. `native/run.sh` and the archived command logs make this auditable.

The earlier three GraphChecker trials remain preserved verbatim in [legacy-graphchecker-result.json](native/legacy-graphchecker-result.json), [legacy-graphchecker-README.md](native/legacy-graphchecker-README.md), [legacy-origin.json](native/legacy-origin.json), and `evidence/hbase01-evidence.tar.gz`. Their four fault events are excluded from all new-method counts and budget. Their woven branch-outcome metric has a different coverage scope and is not added to the JaCoCo counts above.
