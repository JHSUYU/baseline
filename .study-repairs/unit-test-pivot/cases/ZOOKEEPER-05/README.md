# ZOOKEEPER-05: leader epoch check in rolling restart

The original ZooKeeper 3.8.7
`QuorumRestartTest.testRollingRestart` JUnit method runs an embedded
three-peer quorum. The selected target is `Follower.followLeader()` at
source line 103: it throws `IOException` when the leader's epoch is below
the follower's accepted epoch. The healthy test reached the check.

Eleven trials matched and applied their selected checked-I/O exceptions.
Seven executed the target guard after the last fault; four lost the target
before that point. None executed the selected fatal branch or explicit
throw, and no new bug was confirmed. Scoped instrumentation observed eight
new branch outcome pairs. The recorded elapsed time was 1710.754 seconds.

[trials-summary.json](trials-summary.json) records trial outcomes;
[coverage-summary.json](coverage-summary.json) records the scoped coverage
comparison; [result.json](result.json) records the target oracle and timing.
The historical eleven trials leave the current 48-trial budget and further
I/O diversity open. The four lost-target trials do not support conclusions
about the selected exception.
