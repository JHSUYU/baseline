# SOLR-40 independent automatic branch-replay campaign on node2

Run the original `TimeRoutedAliasUpdateProcessorTest#test` on node2 using its
isolated Solr source and Mallory copy. The healthy target closure and
target-node timeline select single faults. A same-actor healthy target branch
may be retried at most eight times; actor rerouting may be retried at most
twice. The cap is 30 trials or 1200 seconds. No manually pinned sequence.

Output: `data/mallory/solr40_graph_auto_v10_node2/SOLR-40/` in the isolated
node2 checkout, subsequently copied to the shared baseline workspace.
