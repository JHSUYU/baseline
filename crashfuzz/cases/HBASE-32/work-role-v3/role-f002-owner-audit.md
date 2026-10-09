# HBASE-32 V3 role-f002: bounded same-selector replay

`role-f002` is the first of at most two fresh-fixture semantic replays of
V3 `role-f001`, using the unchanged original
`TestRegionReplicaFailover#testLotsOfRegionReplicas`, frozen plan SHA
`e3e52e9a77b03c047a25fca1d26b405985a9f7c5f931923981a2fbc07f97e1d0`,
and unchanged agent/JAR hashes. Different fixture values are expected:
`role-f001` selected replica 8 on meta RS39265, whereas `role-f002` selected
replica **9** on meta RS42665. Within each run, F1/F2/B7 match one exact raw
primary+secondary region and replica. This is a distinct V3 diagnostic, not
an s272 byte-identical replay or a fuzz-effective trial.

The pre-fault successful meta OPEN is RS42665 (`role-f002.log:1267`); F1 on
its replica-9 `MASTER_OPENED_RPC` is at `:5428`; F2 on the same raw actor's
first `FlushRegionCallable.call:81` is at `:7652`; B7 rethrows once at
`:7685`. `role-f002.receipt.json` has `identity_valid=true`, strict two
faults, original JUnit incomplete, exit 124 at the 600 s cap, and 643.45 s
including shutdown. Only the selected meta RS aborted before shutdown
(`:7745`); 74/600 table2 child assignments completed before shutdown.

The lock hook records the tracker WRITE attempt on `ServerStateNode`
identity `51150292`/full RS42665 at `:9066`, event 326. Two transition RPC
READ acquisitions on **that same node** remained active at that event:
handler 318 event 306 and handler 317 event 325 (`role-f002.lock-audit.json`).
At 130, 200, 300, 500, and 607 s, `Thread.print -l` retains tracker RW
wait `<0x00000007bdd02028>`, handler 317's region-lock wait
`<0x00000007bdcc04f0>`, and PEWorker-5's ownership of that region lock
while in `RegionRemoteProcedureBase.execute → persistToMeta → HTable.put`.
No selected-node WRITE acquisition or SCP schedule occurs before the first
shutdown hook at `:32415` (13:55:47.990 UTC). The two READ locks release at
`:34258` and `:34388`, the tracker acquires WRITE at `:34389`, and only then
the first carrying-meta SCP is scheduled at `:34394` (13:55:52.344 UTC).
The lock audit reports zero malformed release events. The source-level chain
is the same as in `role-f001-owner-audit.md` and the independent s272 audit.

This second strict positive supports a repeatable role-conditioned recovery
wait over at least 600 s, with physical replica/placement drift. It does not
prove permanent deadlock: the blocked meta RPC's retry count was only 36/46
near the cap. The direct B7 DNR is expected; novelty against HBASE-21508,
HBASE-24526, and related reports remains unconfirmed. Keep `new_bug=false`
until final bounded replay and independent source/issue review.

Raw log SHA-256 `9188edf71f1aa153900e51bed096b01cc096e7a94df8e416b88b158df76889d9`;
JaCoCo SHA-256 `7092d935d944414ea9777ab6ee1d65489945baa3d3b962c4e82580d809d9f881`.
The node1 18-file archive has archive SHA-256
`87be006806e170160ffa5f98c2ec606e81e69fcfa696b119d3b86aab1952baad`
and manifest SHA-256
`23775d22f4f0435c8db296d6b282d9bd5fe42adb371e92bdca041b866745214b`;
every archived member was rehashed on node1.
