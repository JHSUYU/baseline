# SOLR-40 automatic graph campaign with bounded actor rerouting retries

Run the original `TimeRoutedAliasUpdateProcessorTest#test` on node2 in an
isolated checkout. The scheduler keeps dynamic target closure and target-node
timeline fault candidates. When an effective one-fault trial reaches the
target on another node, it repeats that exact plan at most twice. The test
budget is 30 trials or 900 seconds. This campaign has no manually pinned
fault sequence.

Output: `data/mallory/solr40_graph_auto_v7_node2/SOLR-40/` under the isolated
node2 checkout. The pinned Java agent and Solr adapter jars are copied from
`graph-auto-v4/releases/` and verified against `runtime_artifacts` hashes.
