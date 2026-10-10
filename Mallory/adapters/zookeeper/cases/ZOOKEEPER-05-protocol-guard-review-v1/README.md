# ZOOKEEPER-05: current protocol I/O fault gap

The selected throw is `Follower.followLeader`'s second check of
`newEpoch < self.getAcceptedEpoch()` at `Follower.java:99-104`.
`followLeader` first calls `registerWithLeader(FOLLOWERINFO)`. For the
current `LEADERINFO` protocol, `Learner.registerWithLeader` checks this
relation at `Learner.java:507-534` before returning: a higher proposed epoch
is persisted as `acceptedEpoch`, an equal epoch is accepted, and a lower
epoch throws a *different* `IOException` in `Learner`. A packet I/O exception
also exits `registerWithLeader` before the selected Follower check. Thus
the previous I/O injection points do not expose the selected throw in the
same follower attempt.

The existing `QuorumRestartTest#testRollingRestart` reaches the nonthrowing
check in healthy runs. Its six exact injected I/O faults had zero
same-occurrence postfault target checks under the strict actor audit.
`source-review.json` pins the source and evidence SHA-256 values. Run
`python3 verify_review.py` to check those values without starting a JVM.

This disposition is limited to the current three-peer JUnit and current
protocol under the supported I/O exception model. A new source-backed path
must change an operand while allowing `registerWithLeader` to return and
the same follower to reach the selected check. The legacy `NEWLEADER`
protocol branch is different, but this JUnit does not exercise it.
