# SOLR-14 retry JUnit full campaign, node1

This package runs the unchanged Solr 8.11.4 cluster test
`ShardSplitTest#testSplitAfterFailedSplit`. The test deliberately fails its
first split, cleans up, then retries the same shard. Its healthy node1 run
passed one JUnit and observed two `SplitShardCmd.split` invocations on the
named `control` actor. In each, typed `ZkStateReader.forceUpdateCollection`
and `SolrZkClient.exists` calls preceded the exact line-165 check. The
earlier healthy result, trace, config, and dispatch receipt are pinned in
`healthy-proof.json`.

The target is `SplitShardCmd.split@165:branch:5`, followed by the selected
`SolrException` throw at line 167. The only injectable sites are the two
typed ZooKeeper calls at lines 130 and 164. Their injected exception exits
that split invocation. A later check is useful only if the test's retry
reaches it **after** the fault, on the same physical actor. A check before
the fault is not target retention.

The bounded campaign uses 80 fault trials, 3600 seconds, at most 3 faults
per trial, and a 480-second trial timeout. A case-local admission hook checks
the fresh r0000 trace for two ordered same-actor typed door/check paths
before the frozen controller may schedule r0001. Each fault-trial result
records a strict postfault retry gate. The hook prevents a pre-fault target
hit from contributing target-retaining feedback or a target-exception
candidate. Source review is still required to classify any candidate bug.

Offline checks: `python3 static_preflight.py` and
`python3 -m unittest discover -s . -p 'test_*.py'`. On node1,
`python3 run_campaign.py --mode full --verify-seed-only` verifies the sealed
healthy evidence without starting Java. Dispatch must provide a matching
case-local `admission-full-node1.json` GO receipt before `run_node1.sh`
starts the campaign. No GO receipt or full result is included here.
