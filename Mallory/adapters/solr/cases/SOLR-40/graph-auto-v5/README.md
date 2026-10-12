# SOLR-40 graph guidance with exploration

This independent campaign uses the same pinned original test, target probe,
and jars as `graph-auto-v4`. It retains target-closure doors at higher priority
and allows lower-priority exploration outside the observed closure. The v4
strict-closure campaign exhausted seven doors without a target exception:
the two first-watch faults were applied on a different node from the later
target check. V5 tests whether exploration covers another possible target
actor without supplying a prior witness plan.

Run `run.sh` on node0. It holds both Solr locks and resumes a checkpoint. The
budget is 48 one-fault trials or 1,500 seconds. Evidence goes to a separate
directory, so strict-closure and exploration results remain distinguishable.
