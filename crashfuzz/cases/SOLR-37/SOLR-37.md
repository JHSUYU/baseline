# SOLR-37: child hash range must be within parent range

Solr 8.11.4 revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`,
`DistributedZkUpdateProcessor.doDefensiveChecks`, line 994 checks the child
range against the parent shard range for a parent-forwarded update; line 995
throws a `SERVICE_UNAVAILABLE` `SolrException` if it is not a subset. The
unchanged Nightly embedded SolrCloud `ShardSplitTest#test` is used for this
check. It shares a fault sequence and JUnit execution with SOLR-36 while
retaining a separate exact guard/throw oracle.

Two passing original JUnit healthy records hit this exact guard 92 and 100
times on child replicas, with `subset=true` every time and no exact throw.
The child ranges `80000000-bfffffff` and `c0000000-ffffffff` were both within
the parent `80000000-ffffffff` range. Logical replica identity is kept apart
from physical Jetty address. See the common
[healthy audit](../SOLR-36/independent/seed-audit.json) and
[campaign protocol](../SOLR-36/SOLR-36.md). A target exception must be
replayed and checked against the source's protective validation contract
before any bug claim.
