# SOLR-37 request-order review

The selected existing `ShardSplitTest#test` reaches the exact
`DistributedZkUpdateProcessor#doDefensiveChecks` line-994 guard on named
`shard-2`. Source file SHA-256:
`f443baaebc22f93c5bf138cd48e4021bf1b88580881b6c36e2e50d5b7d898674`.

In `processAdd`, source line 239 calls `setupRequest` before line 245
delegates to the update pipeline. `setupRequest` invokes
`doDefensiveChecks` at line 655. The later forwarding work uses
`doDistribAdd` at lines 248–303, where `cmdDistrib.distribAdd` sends
updates to other replicas. The v29p pilot's first fault was an
`Http2SolrClient#request` call from that forwarding phase, after two
`doDefensiveChecks` region entries in the same request context.
Its applied fault is `SOLR-37-r0001:6937` on `shard-2`, context
ending `:1613`. The first later line-994 target check is
`SOLR-37-r0001:7006` in a different request context ending `:1626`.

This ordering explains why later target checks can coexist with a
strictly applied fault without proving the fault reaches them.
The pilot finished 8/8 fault trials: seven exact named faults were
applied and all seven trials reached the target afterward, with no
exact target exception. Frozen-core terminal result SHA-256 is
`9f2684f564ab4c3ad2167ede21341f35bc14101e81b40e3321b5e53f2049bd25`;
offline audit SHA-256 is
`c12dc7746f7c61005b217e533a99b33d89e46f58a47d4d8b06df0db137bca9ec`
and its report gate passes. A separate verifier bound to the trial
result, compressed trace, and decompressed raw trace SHA-256 found
zero time-respecting observed paths from applied faults to later exact
checks across all eight trials. Its sidecar SHA-256 is
`bffdfed6b5a5482fe125b00967a7b0a58324b8b0a2471071e2b519cbde634b71`.
Thus the target-retained count alone does not support a full campaign.
