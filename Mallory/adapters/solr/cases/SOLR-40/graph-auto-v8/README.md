# SOLR-40 automatic closure with bounded branch replay

Run the original `TimeRoutedAliasUpdateProcessorTest#test` in the embedded
four-node Solr cluster. The healthy target closure selects fault candidates.
For an effective one-fault trial that reaches the target on the same node but
keeps the healthy branch, the scheduler repeats the same plan at most eight
times. If the target moved to another node, it repeats at most twice. These
retries sample natural timing variation and never manufacture graph edges.
The cap is 30 trials or 1200 seconds. No fault sequence is pinned manually.

Output: `data/mallory/solr40_graph_auto_v8_node0/SOLR-40/`.
