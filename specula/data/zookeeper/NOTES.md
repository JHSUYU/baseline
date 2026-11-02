# ZooKeeper run notes (operator)

- 2026-11-02 19:26-19:39 UTC: first ZooKeeper runs started (node2: 01 02 03; node0: 04 06 07; node1/3/4: 10 11 12 13 b1 b2 b3 b4 b5).
- 2026-11-02 19:40 UTC: Claude Code auto-memory found on (see hdfs/NOTES.md). The six runs on node2/node0 had started with the nodes' accumulated notes, so they were stopped minutes into Phase 1 and restarted as new runs with CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 (old logs kept in logs/superseded/*.memory-tainted.log; case trees unchanged). The node1/3/4 runs had no notes (empty memory dirs) and continue.
- zk-adhoc-b2: its case tree carries one neutral commit 1312ae0187 (test-scope junit-platform-runner in zookeeper-recipes/pom.xml) so its upstream workload runs at all; target base_commit is that commit.
- test_command is `mvn -o test` (surefire:test skips the jmockit agent setup); m2-zookeeper got the surefire JUnit-platform provider (surefire-junit-platform 2.22.1, platform launcher 1.3.1) on 2026-11-02, also copied into the cases' deps.
