# SOLR-14 next campaign source review

The existing `SplitShardTest#doTest` is a valid SolrCloud JUnit. In the v30
healthy run it passed one test, reached the exact
`SplitShardCmd.split@165:branch:5` check three times on named node1, and
observed the exact `SolrZkClient.exists` call at line 164 immediately before
each check in the same split occurrence. The test creates a two-shard
collection and successfully splits shard1 into five subshards before testing
an invalid split request. The exact target throws at line 167 when the
leader live-node znode does not exist.

The line-164 door permits `KeeperException.ConnectionLossException`, but
`split` has no catch around that call before the line-165 guard. Injecting
that exception exits the invocation before the selected target check. This is
a source-level outcome limit, not a graph-path admission gate. A terminal
full campaign would still count as run under the current completion rule;
the direct door alone cannot establish a postfault line-165 target in that
same invocation. The earlier v30 review and offline audit retain the exact
event sequence and source hashes.

For a future case-local full run, bind the physical actor at the active
`SplitShardCmd.split` region through the Overseer/CoreContainer lifecycle,
then require the exact region, named node/epoch, and callsite before assigning
an ordinal. The v41 healthy config stages that binding but has not produced
a fresh role receipt. A separate observed upstream door that can recover and
return to this same split invocation would be more informative than the
uncaught line-164 door; none is proven by the current trace. SOLR-09 is the
first staged full case because its typed wait exception is caught and can
reach its selected guard after the fault.
