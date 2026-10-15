# Session value-port binding

The original GraphChecker Finalizer binds a declared OUT capture to the next
physical SEND and an IN capture to the most recent physical RECEIVE. That is
exact for one-frame messages. A multi-frame protocol can compute a value
before its first frame and consume it after a later frame of the same session.
The physical legs must remain distinct: this change records an additional
conservative session influence only when there is a unique static port match,
two independently paired wire deliveries, strict ordering, and identical
transport, correlation, half, source lifecycle and destination lifecycle.
Ambiguous, overlapping or unmatched deliveries retain the existing gap.

The Finalizer first looks for an exporter on the exact physical leg. If none
exists, it may admit the unique session influence producer with basis
`WIRE_SESSION_PRODUCER_V1`. This does not assert that a particular physical
frame carried the value. The recorded `exchangeLeg` and both wire receipts
remain unchanged.

An occurrence that also executes the target site can still be this verified
producer for a *different* selected target occurrence. The Finalizer keeps
the original exclusion for independent root and control admission but lets a
declared OUT port on a matched leg admit that occurrence as a wire producer.
It does not select that other target as an oracle root.

For HDFS 3.4.3 Balancer, the frozen healthy trace has the general pattern:
key-ID OUT capture at seq 299484; first REQUEST send/receive at 300005/300115;
second REQUEST send/receive at 300637/300683; key-ID IN capture at 300800;
target check at 300809. All frames have one correlation ID and the two
request attempts share source and destination lifecycle identities. The
unmodified Finalizer reports an `ADMISSION_GAP` at the key-ID IN port because
the OUT and IN captures bind to different physical attempts. The target static
region `REGION.53092d3e` is already folded into the selected DataXceiver
activation `REGION.61e62f41`; that ID difference is expected.

The frozen Balancer trace is archived at
`/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs11-balancer-node2-v1/evidence/pilot-v4-local-raw.tar.gz`
(SHA-256 `511315c307361aa452ae0c6778b5f061023e01c9c36f91e9cf781cada4767fa1`).
Its selected dn1 target capture is paired to the dn0 OUT capture above; both
record the primitive key ID `686986317`. On a read-only replay of its 239,915
trace rows, the exact dn0 producer activation with root call `295730` is
admitted as `WIRE_SESSION_PRODUCER_V1` to the selected dn1 target activation
with root call `299650`. The resulting original Finalizer plan contains 216
occurrences. The region graph summarizes 714 real paired exchanges and five
target-closure edge families, including the dn0-to-dn1 HDFS_SASL REQUEST
family. The prior summary had zero target-closure edge families. The one
remaining aggregate key-ID `ADMISSION_GAP` is produced by five other demanded
dn2 epoch0 occurrences without paired exports; the selected dn1 consumer is
paired. This diagnostic is retained.

`RuntimeRegionPlannerSessionPortTest` verifies exact-frame priority and
rejects different correlations, peers, ambiguous producers, overlapping
frames and unmatched wire receipts. `WireProducerExclusionTest` verifies that
a separately selected target occurrence may enter only through a matching
wire export, while an unmatched one stays out. This replay did not run a new
JUnit test or change any fault site.
