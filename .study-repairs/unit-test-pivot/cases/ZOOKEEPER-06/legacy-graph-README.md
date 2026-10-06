# ZOOKEEPER-06: leader acknowledgment epoch check

The unchanged ZooKeeper 3.8.7
`QuorumRestartTest.testRollingRestart` JUnit method runs an embedded
three-peer quorum. The target is `Leader.waitForEpochAck` at source line
1471, with the selected `IOException` on lines 1472–1475 when a follower's
state summary is ahead of the leader's.

The earlier campaign ran 32 fault trials. It selected 35 fault events and
applied 32; 29 sequences matched every requested fault and three did not.
Seven trials executed the selected check after injection. None executed its
selected exception. The I/O families included quorum responses and
`ACKEPOCH` processing; the exact selectors and outcomes are in
[trial-ledger.jsonl](trial-ledger.jsonl). Scoped coverage feedback within
successive builds found 3, 5, and 7 new branch or method signatures,
respectively; their IDs cannot be unioned across builds.

Measured JUnit fault execution and trace processing took 321.413 seconds.
The full historical investigation spanned 2704.312 seconds including setup
and review. [result.json](result.json) records both time scopes and family
counts. The current 48-trial budget and further relevant I/O variants
remain open. No new bug was confirmed.
