# Serialized message replay pilot

This opt-in patch scopes the real `byte[] data` passed to
`OverseerTaskQueue.offer(byte[], long)`. The runtime hashes those bytes with
the transport and queue route. The trace records only the digest, never the
payload. The fault door also records a node-independent SHA-256 digest of
its causal context, region, and call index. No HTTP entity is read or replayed.

The automatic scheduler may select this key only when exactly one door has
the same `(siteId, messageReplayKey, messageParentId)` in the healthy trace.
The faulted trace must also have exactly one such door and one matching
`FAULT_APPLIED` row. A missing, changed, or repeated message therefore gives
no strict injected-fault credit. Existing plans without these fields retain
their exact actor and replay-occurrence matching.

`source-receipt.json` pins the patched Solr source file, patch bytes, and
unchanged original JUnit source. Apply the patch to an isolated copy of the
Mallory queuev8 Solr tree after verifying the base SHA. Rebuild the compiled
classes and automatic static scope because adding the hook changes Jimple
unit indices. The existing SOLR-40 v8/v9b JARs, scope, trials, and queue
remain immutable. A content digest can match only byte-identical serialized
requests; it does not normalize generated collection names or map a streaming
HTTP request to an operation. A source-provided stable operation ID is a
separate future option when the application exposes one.

The parent digest includes the causal root ordinal or producer anchor. Actor
migration alone can match, but a changed root ordinal or missing propagated
producer cause remains unmatched. This patch cannot repair the six already
sealed SOLR-40 trials: they recorded neither payload nor parent keys. A new
healthy seed must prove a unique key before any new keyed plan.
The existing r0006 audit also found zero faulted offer calls with the seed's
full static ancestry, so this exact-parent rule may still reject that pattern
even after fresh instrumentation. A stable producer cause carried through the
request and queue handoff is the remaining general identity gap.

`compile-receipt.json` is a source patch compilation smoke against an earlier
runtime JAR with the same `beginMessagePayload` API. Runtime and weaver tests
on the final source pin are separate; a full source-built Solr weave and
unchanged JUnit are still required before experimental use.
