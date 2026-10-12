# SOLR-40 graph-guided automatic replay

This campaign tests whether Mallory's scheduler independently picks a fault
door from the healthy target closure that exposes the SOLR-40 exception. It
uses the original four-node `TimeRoutedAliasUpdateProcessorTest#test` and the
validated caller-side `@133:callthrow:7` target probe. The Solr adapter and
instrumentation jars are pinned under `releases/`.

`run.sh` acquires the node0 Solr and shared source locks and resumes its
checkpoint. The budget is 48 one-fault trials or 1,800 seconds, whichever
comes first. Selection is restricted to the target closure and static
frontier; the script does not pass the prior witness plan to the scheduler.
The earlier v3b directed replay is separate evidence and must not be counted
as an automatic discovery.
