# ZooKeeper leader REQUEST receive context (v1)

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
from the separate connect-path overlay. The source delta is
`zookeeper-3.8.7-requestrecv-v1.delta.patch` (SHA-256
`ca67dc0c8258a0a905f1ce065a3b948ee7880f5a00de7da61b43a04fea54540e`)
and dry-runs against the connect-path overlay. The compiled overlay receipt
is `zookeeper-3.8.7-requestrecv-v1-overlay.json` (SHA-256
`affa3c18cce25535e5a4334db1a79d3312c5f9930582c466e73548eb9e74c16a`).
The changed `LearnerHandler.class` SHA-256 is
`bf7acfdf0c8fce34b590562f253fc224acb9bfa59f4771d24b9df5d31b3a7cec`.
Both fresh healthy runs used the immutable scoped-root agent
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`
and event-time core release
`fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f`.
The existing three-peer `QuorumTest#testMultiToFollower` passed in each run;
both exact targets were nonthrowing on named `zk2`, epoch 1, with loaded
`SessionTrackerImpl.class` SHA-256
`79699a785a100abcd9e127c2258a94696676123eff5e9117a23f9052e65b96db`.

ZOOKEEPER-02 healthy evidence is at
`data/mallory/calibration_fa5f_lane2/ZOOKEEPER-02-requestrecv-v1`: 8 observed
edges and two event-time pretarget doors. Its client request read on `zk1`
at event 200 preceded packet SEND 206, physical token-scoped RECV 207 on
`zk2`, leader request region 208, and target check 215. Offline audit passed.
ZOOKEEPER-03 healthy evidence is at the analogous
`ZOOKEEPER-03-requestrecv-v1` path: 6 observed edges and two pretarget doors.
Client connect read on `zk1` at event 172 preceded packet SEND 178, physical
RECV 179 on `zk2`, leader request region 180, and target check 188. Offline
audit passed. The independent SHA-bound packet attestation receipts are under
`data/mallory/admissions/ZOOKEEPER-0{2,3}-fa5f-requestrecv-v1-healthy.json`.

The six-fault ZOOKEEPER-02 pilot is preserved at
`data/mallory/pilot_fa5f_lane2/ZOOKEEPER-02-requestrecv-v1`: 6 exact applied
fault trials, three generic target-retained trials, and zero selected throws.
Its offline healthy/trace audit passed, but the separate postfault actor/path
audit found zero faults with an exact same-occurrence or time-respecting
observed path to a later target check. Thus the pilot does not qualify for a
full campaign. The result, offline audit, and postfault audit SHA-256 values
are respectively `ef8695c1972db38f4588e3165f19ce9694d374991570e15f88527242936fdef7`,
`7dc9d547c9962394682be1ce72a5c8b310fdd048775596e48445647858a9aea6`,
and `e2ef165369bb03f4f5c19626c7f0c69b52040c796f296a44f7890db6a55e9712`.

The six-fault ZOOKEEPER-03 pilot is preserved at
`data/mallory/pilot_fa5f_lane2/ZOOKEEPER-03-requestrecv-v1`: five strict
injections, five generic target-retained trials, and zero selected throws.
Its offline healthy/trace audit passed. The postfault actor/path audit found
zero of the six applied faults with a same-occurrence or time-respecting
observed path to a later target check, so it also does not qualify for a full
campaign. The result, offline audit, and postfault audit SHA-256 values are
respectively `842393e0aa46cd699e0ecc26c4ea6b433ded8029376d468093d3f39ec25eac85`,
`d8a3342388ea56ca28b6ba7417eb8d78df11b1595d9534df738d6d492d5a834d`,
and `a132bf13818ee91ed00740152fc183e923d6fa1c1632e638effd93f68c74ee30`.

An updated read-only postfault audit additionally uses the immutable core's
exact event-time path algorithm and accepts only thread-scoped roots (the
initial sidecars conservatively rejected every `unscoped:` prefix). It still
finds zero qualifying fault-to-target paths in either pilot. Its separate v2
receipts are `postfault-actor-audit-v2.json` in each pilot directory, SHA-256
`05f35c47a72722ba7aa9351edbaf26f5b263cb288706329716c6c812eea45a45`
for ZOOKEEPER-02 and
`b0d73b0cc3225fd9716c710d564982390c58f33464b66d13edc873b527467a1d`
for ZOOKEEPER-03. Original raw trials and v1 sidecars remain unchanged.

Fault-campaign admission additionally requires the injected fault's actor or
an observed causal successor to reach the target after injection. A healthy
path alone does not meet that condition.

The healthy traces place the leader REQUEST physical RECV immediately before
`LearnerHandler` creates a `Request` and calls `submitLearnerRequest`. In the
patched source, `ia.readRecord(qp)` precedes that switch, and an IOException
from it exits through `LearnerHandler.run`'s outer catch, which closes the
socket (`LearnerHandler.java:697-722`; source SHA-256
`e6dfb01c16e8cfe3f9c46e3b44de13ec88958bb823019161bbb78e8881df44d9`).
An injected exception at the exact receive therefore does not submit that
request to the target's processor. Likewise, `PrepRequestProcessor.run`
claims the request immediately before `pRequest`, and its outer catch exits
the processing loop on an exception (`PrepRequestProcessor.java:140-163`;
source SHA-256
`f419aa4ee5a5f43c8f15a511e112ee05a35cb83b1aedb213bdfca6fa089f43fe`).
There is no source-backed request-scoped IOException door at these two
boundaries that both throws and lets the *same* request reach the selected
guard. This explains why a new receive/claim hook would create another
target-losing trial; none was added.

ZOOKEEPER-02's relevant client door is `zookeeper.client.request.read`;
ZOOKEEPER-03's guard occurs before the first such read, so its relevant door
is `zookeeper.client.connect.read`.
