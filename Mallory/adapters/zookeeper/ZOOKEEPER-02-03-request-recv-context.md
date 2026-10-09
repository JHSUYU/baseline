# ZooKeeper leader REQUEST receive context (source-only v1)

The archived ZOOKEEPER-02 and ZOOKEEPER-03 healthy traces already contain a
physical quorum REQUEST packet SEND/RECV pair, followed by the leader's
request region and session-tracker check. The leader RECV was emitted in its
actor-wide root. Its `correlation` is the exact socket direction, packet
ordinal, packet type, and zxid from the observed `QuorumPacket`; the `port`
also carries the request payload digest. `LAST_RECEIVED` stores that packet
object and correlation until `quorumRequestScope` checks object identity.

The isolated source patch `install_request_receive_context.py` wraps only a
leader-side REQUEST `Probe.receive` in `Probe.withCausalContext(correlation)`.
The scope closes immediately after that RECV. The existing
`quorumRequestScope` then uses the correlation from the same packet object
while entering `zookeeper.leader.request`; no new SEND/RECV event or inferred
edge is created. Non-REQUEST packets keep the existing instrumentation.

The patch is staged only in
`/users/ZhenyuLi/.mallory-worktrees/zookeeper-requestrecv-v1-lane2`, copied
from the separate connect-path overlay. It has not been compiled or run as a
MiniCluster. The source delta is
`zookeeper-3.8.7-requestrecv-v1.delta.patch` (SHA-256
`ca67dc0c8258a0a905f1ce065a3b948ee7880f5a00de7da61b43a04fea54540e`)
and dry-runs against the connect-path overlay. Admission requires a versioned
compiled overlay receipt, the
future agent's bounded thread-scoped root format, a fresh existing-test
healthy seed for each check, and an observed chronological client-door →
follower task → quorum packet → leader request task → target check path.
ZOOKEEPER-02's relevant client door is `zookeeper.client.request.read`;
ZOOKEEPER-03's guard occurs before the first such read, so its relevant door
is `zookeeper.client.connect.read`.
