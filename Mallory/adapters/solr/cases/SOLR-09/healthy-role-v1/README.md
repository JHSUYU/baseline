# SOLR-09 healthy command-role admission

This package stages exactly one healthy run of the unchanged Solr 8.11.4
`DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup` on node2 lane3. It
uses the case-local role-aware agent from `runtime-role-v1`, the v38 Solr
adapter, and the pinned campaign core. `run_healthy.py --preflight-only`
checks hashes and source control flow without starting a JVM. A run requires a
separate dispatch GO receipt bound to the config, runner, host, and fresh
output. `admission-request.json` has `go=false`; no fault is scheduled by this
package.

The JUnit creates a four-node cluster at `DeleteReplicaTest.java:78`, creates
a one-shard, two-replica collection at line 152, and synchronously deletes its
leader at lines 161–162. The exact selected check is
`DeleteReplicaCmd#deleteCore(...)@277:branch:7`, with the line-278
`SolrException` throw. The target class SHA-256 is
`a76f7f732bd13437f37a44e4e0eaee13e053b0a6ae72b571bea1b3ec6b623c3b`.
The live-replica path sends `UNLOAD` at line 251, consumes the response at
line 257, and waits at line 260. A false wait triggers a `DELETECORE` state
update at line 264 and a second wait at line 265. Two false waits return
`Boolean.FALSE` at line 266 and reach the selected guard. An escaping
exception takes the wrapper catch at lines 282–283, a distinct path.

The exact typed door is
`OverseerCollectionMessageHandler#waitForCoreNodeGone(...)@434:door:1` calling
`ZkStateReader.waitForState`. Its declared `TimeoutException` is caught at
lines 443–444 and returned as false. This is a wait over watched collection
state. Both source waits use the same door site, so the event ordinal and
`deleteCore` occurrence must be inspected before any later pilot. The door
owner class SHA-256 is
`a13bdec21685f267f30ca01db19338b0cb84e94813ba3471847687189c6e779f`.
The source checkout is pinned to
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`; `manifest.json` pins the
test, target, door owner, state reader, compiled classes, agent, adapter,
runner, selected sites, campaign core, and scripts by SHA-256.

Prior raw healthy evidence passed this JUnit and observed the exact door at
event 266 and target check at event 280 on node4, epoch 0, thread 217, in the
same `deleteCore` occurrence. It had a parent `processMessage` edge and an
ordered local door-to-target timeline, but no nonempty event-time graph edge
from that door to that check. A later fixed-node timeout plan missed when the
Overseer actor moved to node2. The role-aware agent resolves
`delete-replica-deletecore` only at this exact door while the exact `deleteCore`
region is active on a registered physical actor. That agent has unit proof
but no fresh cluster JUnit proof yet.

After an admitted run, `audit_healthy.py` writes `healthy-role-audit.json`.
The healthy admission gate is: one passed JUnit; no fault or selected throw;
correct loaded class hashes; a nonthrowing exact line-277 check on a registered
physical node; the exact typed TimeoutException door before it on the same
node, epoch, thread, context, and `deleteCore` occurrence; a unique bound role
whose node, epoch, and source occurrence match the door; and the observed
`processMessage` parent. The audit reports a nonempty door-to-target graph
path separately. A successful gate authorizes review of a separate bounded
role-qualified pilot; it does not establish the line-278 throw or authorize
the staged full campaign. A missing role, node registration, exact door, or
target leaves SOLR-09 at a healthy admission gap.

Offline verification: `PYTHONDONTWRITEBYTECODE=1 python3 run_healthy.py
--preflight-only`. The run command, after dispatch writes a matching GO
receipt, is `python3 run_healthy.py --admission-receipt PATH`. The runner holds
the node2 lane3 and shared Solr source locks and requires a fresh output,
7.125 GiB free disk, and 8 GiB available memory. No JVM was launched while
staging this package.
