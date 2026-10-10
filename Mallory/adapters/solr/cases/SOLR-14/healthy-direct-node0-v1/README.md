# SOLR-14 node0 healthy-only split observation

This package runs the unchanged Solr 8.11.4
`SplitShardTest#doTest` on its one-node `MiniSolrCloudCluster`. The selected
check is `SplitShardCmd.split@165:branch:5`, where a null live-node znode
stat leads to the line-167 `SolrException`. The exact target source and JUnit
source are pinned by SHA-256 in the config. The compiled target class, Solr
distribution, Mallory agent, Solr adapter, and campaign core are also pinned.

The I/O catalog has only two exact, typed calls in the selected split method:
`ZkStateReader.forceUpdateCollection` at line 130 and
`SolrZkClient.exists` at line 164. Both are ZooKeeper calls with
`KeeperException.ConnectionLossException` as the modeled fault. Automatic
I/O doors are disabled; the line and method constraints prevent the later
line-523 `exists` call from entering this catalog. The no-fault run records
the target and these I/O points on named physical actors, plus branch and
method coverage. It performs no fault injection and cannot promote a full
campaign.

The prior SHA-bound v30 healthy run passed one JUnit and observed the exact
target three times on named `node1`. It paired the direct line-164 door with
the check in the same split occurrence (`1683→1685`, `9531→9533`,
`9984→9986`). This establishes a local healthy order only. At source line
164, `ConnectionLossException` exits `split` before the line-165 check;
line 130 likewise has no local recovery before the check. A positive healthy
result cannot authorize faults at these two doors for a target-retaining
campaign. An upstream or background I/O point requires separate observed
causal and postfault target-retention evidence.

Run `python3 run_campaign.py --mode healthy --preflight-only` or
`python3 static_preflight.py` for an offline, no-JVM check. Dispatch must
create a matching case-local `admission-healthy-node0.json` GO receipt
before any runtime run. The runner requires node0, a fresh output, the
shared node0 locks, sufficient disk and RAM, and no competing user JVM.
The package was staged without running the JUnit or a fault campaign.
