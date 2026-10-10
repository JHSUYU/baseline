# ZOOKEEPER-06 node0 ACKEPOCH campaign

This package runs `QuorumRestartTest#testRollingRestart` on the isolated node0
source tree. Its 15 changed source files and 21 compiled classes have the same
SHA-256 digests as the node1 overlay. The compiled trees were copied from
node1 after verifying all 21 pinned class digests there, then reverified on
node0. The target is the exact `Leader.waitForEpochAck` guard at `@1475:branch:3`
and throw at `@1479:throw:1`.

`healthy.json` is one JUnit calibration run. `full.json` is generated only
after the local healthy result passes its runtime and exact packet-path audit.
The full campaign budget is 80 fault trials, 3600 seconds, and at most three
faults per trial. A terminal `budget_exhausted` or `queue_exhausted` result
means the campaign completed; it does not, by itself, establish that the
selected throw executed or that a new bug exists.
