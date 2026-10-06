# ZOOKEEPER-07: learner epoch check in rolling restart

The unchanged ZooKeeper 3.8.7
`QuorumRestartTest.testRollingRestart` JUnit method restarted three
in-JVM peers. The selected `Learner.registerWithLeader(int)` guard begins
at source line 515 and its `IOException` throw begins at line 522. The
fatal condition is a leader epoch below the follower's accepted epoch.
The healthy test reached the guard twice, both on its nonfatal outcome.

The earlier campaign ran three trials. All three selected exceptions
matched and applied at the observed
`FAULT:ZK_QUORUM:RESPONSE` site
`Learner.readPacket(QuorumPacket)#u6`. Only trial-03 met the historical
strict selector criterion. Its read exception propagated through
`registerWithLeader`, was handled by follower retry, and later target
guard executions stayed nonfatal. The original JUnit test passed. The
exact trial selector is [trial-03/plan.json](trial-03/plan.json), with
machine-readable observations in [evidence.json](evidence.json).

No trial reached the selected fatal outcome or added scoped production
coverage. Measured successful steps took 63.221 seconds; earlier
exploratory and failed port-conflict runs are excluded. The historical
three-trial campaign leaves the current 48-trial budget and further I/O
fault families open. No new bug was confirmed. [result.json](result.json)
records the fault counts and timing.
