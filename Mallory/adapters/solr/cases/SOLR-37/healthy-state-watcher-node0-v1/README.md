# SOLR-37 node0 watcher-state healthy observation

This is a separate one-trial healthy-only port of `healthy-state-watcher-v1`.
It uses the unchanged `ShardSplitTest#test` JUnit, the exact
`DistributedZkUpdateProcessor.doDefensiveChecks@994` check, and only the
source line 1641 typed `ZkStateReader.fetchCollectionState` getData door.
The existing clean Solr 8.11.4 source checkout is SHA-pinned; no new large
worktree is created. The node2 package remains immutable provenance.

The selected watcher call and target are on different request contexts.
The v46 diagnostics do not record the target reader ID or range operands, so
this is an observation probe. A positive door and target alone do not admit a
fault pilot or a full campaign; observed watcher-to-request causal evidence or
separately pinned target operand telemetry would be required.

Run `python3 run_campaign.py --mode healthy --preflight-only` without a JVM.
A case-local dispatch GO receipt is required for the sole healthy trial. The
runner checks node0, fresh output, 7,650,410,496 free bytes, 8,388,608 KiB
MemAvailable, no competing user JVM, and acquires the ZK node0, Solr node0,
and shared Solr source locks in that order. No full mode is available.
