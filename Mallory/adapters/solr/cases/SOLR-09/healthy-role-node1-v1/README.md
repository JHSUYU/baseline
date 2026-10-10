# SOLR-09 node1 healthy role port

This is a separate, one-JUnit healthy port of `../healthy-role-v1` for node1.
The node2 package remains unchanged. The unchanged Solr 8.11.4
`DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup` creates four nodes,
then synchronously deletes the leader of a two-replica collection. The
selected check is `DeleteReplicaCmd.deleteCore@277:branch:7`; its line-278
throw requires both `waitForCoreNodeGone` calls at source lines 260 and 265
to return false. The exact typed door is
`OverseerCollectionMessageHandler.waitForCoreNodeGone@434:door:1` calling
`ZkStateReader.waitForState`; `TimeoutException` is caught at lines 443–444.

Node1 already has a clean source checkout at
`e27f44e3d78dfcec230c97e0a1240e3751daeff9` and the matching Solr
distribution at the **same absolute paths** used by the node2 package. The
selected JUnit source SHA-256 is
`70e79d52bbc9e312cfb739d727b57ee99f66956068ab0a2a65df46efb13bd970`.
The compiled target and door-owner class hashes are
`a76f7f732bd13437f37a44e4e0eaee13e053b0a6ae72b571bea1b3ec6b623c3b`
and `a13bdec21685f267f30ca01db19338b0cb84e94813ba3471847687189c6e779f`.
`manifest.json` pins those inputs and every one of the 171 JARs in the direct
JUnit runner's classpath, along with the v38 entry point, its underlying
runner, v20 inventory, `PilotJUnit.java`, case-local agent/core, adapter, and
this package's code. The classpath inventory digest is
`52ce1270fd871bbfa7e0a4faeaf4e5a91c801a637518fa02f1164e0509092644`.
The v38 wrapper also checks its generic agent JAR even in campaign mode; that
existing node1 JAR is pinned at SHA-256
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`.
The campaign core supplies the case-local role agent through
`JAVA_TOOL_OPTIONS` for the actual JUnit JVM.

The package uses `/tmp/mallory-lanes/solr-node1-v1.lock` plus the local
shared Solr source lock. Output is fresh at
`data/mallory/calibration_solr09_healthy_role_v1_node1/SOLR-09`. It is bounded
to one healthy trial, with `auto_promote_if_healthy=false`. The runner requires
a separate dispatch GO receipt that matches node1, the config, runner,
manifest, locks, and output. `admission-request.json` has `go=false`.

After an admitted run, `healthy-role-audit.json` must show a passed 1/1 JUnit,
no fault or selected throw, exact loaded class hashes, the line-277 check on
a registered physical actor, and the exact typed timeout door before it on
the same node, epoch, thread, context, and `deleteCore` occurrence. The door
must carry a unique `delete-replica-deletecore` role with matching node,
epoch, and source occurrence, and the `processMessage` parent must be
observed. The audit reports a nonempty graph path separately. A healthy role
match allows review of a later bounded pilot; it does not prove the line-278
throw or authorize a full campaign.

Run `PYTHONDONTWRITEBYTECODE=1 python3 run_healthy.py --preflight-only` to
verify all pins without starting a JVM. The runtime command after dispatch
approval is `python3 run_healthy.py --admission-receipt PATH`. It refuses an
existing output, a host other than node1, less than 7.125 GiB free disk, or
less than 8 GiB available RAM. The JUnit build itself remains a runtime step;
no Java compiler or JVM was run during staging.
