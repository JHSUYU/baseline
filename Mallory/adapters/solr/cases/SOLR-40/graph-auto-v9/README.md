# SOLR-40 independent automatic branch-replay campaign on node1

Run the original `TimeRoutedAliasUpdateProcessorTest#test` on node1 using its
isolated Solr source and Mallory copy. This campaign selects one-fault plans
from the healthy target closure and target-node timeline, then retries at most
twice for target actor movement and at most eight times when the same target
actor reaches the normal branch. The cap is 30 trials or 1200 seconds.
No manually pinned sequence is used.

Output: `data/mallory/solr40_graph_auto_v9_node1/SOLR-40/` in the isolated
node1 checkout, subsequently copied to the shared baseline workspace.
