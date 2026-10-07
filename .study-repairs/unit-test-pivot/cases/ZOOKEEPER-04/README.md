# ZOOKEEPER-04: client zxid ahead

The selected check is `ZooKeeperServer.processConnectRequest` at `ZooKeeperServer.java:1431`:
`connReq.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid`. Its throw arm at line 1441 raises `CloseRequestException(CLIENT_ZXID_AHEAD)`. The unchanged ZooKeeper 3.8.7 `ConnectionMetricsTest#testRevalidateCount` starts a three-peer quorum, connects one client to follower1, then reconnects its existing session to follower2. Source and compiled test are from commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

## Actor-aware V2 result

**Quality complete: 80/80 effective trials, 0 selected target exceptions, 0 new bugs.** Two fresh original-JUnit healthy runs passed on node2 in 14.159 and 13.361 seconds. Each recorded an initial, unselected follower1 guard and one selected follower2 guard for the same raw client session. Actual `QuorumPeer` objects/SIDs, the original `ClientCnxn`, socket endpoints, `ServerCnxn` owner, and `ConnectRequest.sessionId` were joined at runtime. A wrong-peer or unbound I/O selector fails closed. The adapter, bytecode smoke, and calibration details are in [the V2 case README](../../zk-actor-v2/cases/ZOOKEEPER-04/README.md).

The node2 campaign applied 80 ordered I/O exception sequences, 456 individual faults, at depths 1–8. Every sequence matched its bound actor and reached the selected follower2 guard for the same session **after its final fault**. All 80 unchanged JUnits passed. The fault JVMs consumed 1,834.479 seconds in aggregate; adding the two healthy JVMs gives **1,861.999 seconds** measured case time. The 80 trial rows with individual elapsed times are in [trial-summary.csv](../../zk-actor-v2/cases/ZOOKEEPER-04/evidence/trial-summary.csv).

Case-local ASM feedback covered 162 source lines in the two healthy seeds and 171 in the union with effective trials, a gain of 9 instrumented production lines. The actor-bound I/O family count rose by 24 to 26. The final eight effective trials added no line, I/O family, or selected throw; the predefined 128-effective/10-fault extension therefore did not start. There were 105 queued plans at the budget boundary. The 80 selected faults were on actual client `SocketChannel` reads/writes; server and epoch-file I/O without a proven owner was excluded. This is a budget-complete result for that runtime-bound scope.

[Independent audit](../../zk-actor-v2/cases/ZOOKEEPER-04/evidence/campaign-audit.json) re-read all 80 raw event streams, fault plans, actor and target-owner receipts, JUnit exits, times, and target throw counts with no error. The [raw archive](../../zk-actor-v2/cases/ZOOKEEPER-04/evidence/zk04-v2-raw-80.tar.gz) includes both healthy traces, all 80 fault traces, coverage, logs, and the final checkpoint; SHA-256 `859ae74f925c02f11b37fa0452b84468a351c3851fafde1fd2879a5d046a5ed2`. `result.json` is the machine-readable summary.

## Legacy evidence

The earlier 80 fault trials used call-site/global-ordinal selectors without a stable peer, client, socket, or file owner. Legacy trial 015 shows the same static write ordinal on follower1 where the healthy run selected follower2. Those 80 trials count as **zero** actor-V2 effective trials. Their full result and narrative are preserved as `result.pre-actor-v2.json` and `README.pre-actor-v2.md`; the original raw archive remains under `evidence/`. The even earlier 29 GraphChecker/independent continuation trials remain in `legacy-graph-result.json` and its separate evidence. No old trial was rerun or added to the V2 denominator.
