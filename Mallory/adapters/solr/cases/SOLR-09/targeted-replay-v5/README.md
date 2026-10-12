# SOLR-09 directed state-read timing diagnostic

On node1, run the original `DeleteReplicaTest.deleteReplicaAndVerifyDirectoryCleanup`
in an isolated Mallory checkout. Reuse the prior three-fault witness shape, but
inject the final same-Overseer `fetchCollectionState` exception at relative
state-read hit 3 after the watcher fault. The cap is 12 trials. This is a
prior-witness-seeded directed timing diagnostic, not automatic graph selection.

Output: `data/mallory/solr09_targeted_replay_v5_node1/SOLR-09/` in the isolated
node1 checkout, subsequently copied to the shared baseline workspace.
