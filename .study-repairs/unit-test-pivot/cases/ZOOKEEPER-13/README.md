# ZOOKEEPER-13 actor-aware original-JUnit result

The selected check is `org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer.validateSession(org.apache.zookeeper.server.ServerCnxn,long)` in `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java`. The original `ReadOnlyModeTest#testGlobalSessionInRO` starts an embedded quorum, binds the actual read-only peer 1, and reconnects the first raw global session. Its `CloseRequestException` is expected.

Two healthy runs and 131 fault JUnits took 8652.511 summed JVM seconds. 103 plans were exact; 80 retained the selected guard after the last fault. Budget: 80 effective, maximum 8 faults. New production line IDs: 1; normalized I/O families: 0. Result: **quality_complete**, bug mark `none`.

The [raw audit](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/terminal-audit.json), [per-trial time table](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/trial-times.csv), and [compressed original-JUnit receipts](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/raw-runs.tar.gz) preserve the selected actor, raw session, applied fault sequence, target check, coverage, and original JUnit outcome. The older global-ordinal [result](result.pre-actor-v2.json) remains historical coarse evidence.
