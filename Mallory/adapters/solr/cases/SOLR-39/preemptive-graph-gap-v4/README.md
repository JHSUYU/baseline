# SOLR-39 sealed healthy graph gap and fault continuation stage

`audit_graph_gap.py` replays the already sealed, unchanged four-server
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` healthy trace. It
starts no JVM and changes neither Solr nor the shared Mallory graph. The
healthy JUnit passed (1 test, 0 failures/errors); the exact `@246` check ran
11 times. All 1,250 supplemental Java reference markers pair to core field
events without owner collisions. The raw archive SHA-256 is
`ac92251f6c58567f17019a4f69a0a87068a824a627e4fd9e7e01f806f2d10566`.

## Missing relation and offline repair

The pinned `OccurrenceGraph` already links a watcher door to its nested
`AliasesManager.setIfNewer` write through balanced same-thread program order.
It also generates a *candidate* state edge from that write to a later
`getAliases` read because the core field version is sampled. The graph has no
edge from the nested getter's `REGION_EXIT` back to the caller's next event,
so its event-time search stops before the exact target check. The graph's
original five candidate paths all have **zero** door-to-target event-time
witnesses, even with candidate state edges enabled.

The case-local overlay accepts two additional observed relations:

1. The `aliases` volatile write and read have the same named actor, epoch,
   `AliasesManager` receiver and **exact Java `Aliases` object reference**,
   with no intervening publication. The pinned bytecode transformer records
   the actual value consumed by `PUTFIELD` and produced by `GETFIELD`; the
   supplemental reference IDs are not sampled field-version guesses.
2. The getter is directly nested under the target method on one JVM thread.
   Its `REGION_EXIT` is balanced; the first subsequent event on that thread
   resumes the exact caller occurrence before `TARGET_CHECK`. The overlay
   adds only this verified child-return-to-caller continuation edge.

For example, node2 watcher door **32156** reaches `setIfNewer` write **32193**;
the same `Aliases` reference is read in `getAliases` at **32960**; getter exit
**32961** resumes the target method at **32962**; exact check **32963** follows.
The resulting observed witness consists of `program_order`,
`state_exact_ref`, and `program_return`. The same proof holds for all five
source-backed reference paths. Three are later than an earlier target check
on the same manager with a different alias reference/version:

| Healthy door | Actor / ordinal | Exact check |
| ---: | --- | ---: |
| 23175 | node2 / 12 | 24824 |
| 25649 | node3 / 13 | 28461 |
| 32156 | node2 / 15 | 32963 |

The source supports these edges: `ZkStateReader.AliasesManager.process`
reads the fixed `ALIASES` path (`/aliases.json`) at line 2312 and calls
`setIfNewer`; `setIfNewer` writes the volatile `aliases` reference at line
2342; `getAliases` returns that volatile reference at line 2223;
`RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections` immediately
uses the returned reference at lines 244–246. Source and instrumentation
SHA-256 pins are enforced by `validate_seal`.

Run the offline proof and negative controls:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-graph-gap-v4/audit_graph_gap.py
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/preemptive-graph-gap-v4 -p 'test_*.py' -v
```

`offline-proof.json` records the five event-time witnesses.
`fault-stage-request.json` is **GO=false** and lists the three qualified
healthy watcher doors with a ceiling of 12 fault trials, 2,400 seconds, and
three faults per trial. The run-local manager/resource selector and
checkpoint-safe fault campaign runner remain to be implemented and checked;
the healthy actor's object/reference IDs are evidence, not IDs that can be
reused in another JVM. No fault run is authorized by this stage.

The typed `ConnectionLossException` at the watcher `getData` call is caught
by `process` and skips that `setIfNewer` call. A successful injection can
therefore remove the healthy door-to-*new*-write path. A fault trial should
instead require exact selected watcher, `/aliases.json`, actor, epoch,
run-local manager, occurrence and thread match at injection; then a later
`@246` check on the **same manager** fed by its prior exact `Aliases`
publication/read path. It must verify that this faulted watcher occurrence
did not publish a new reference. This is a counterfactual deletion effect;
event order alone cannot create a positive fault-door-to-target graph edge.
An exact target throw is only a candidate pending source review. Invalid
injections or lost target paths contribute zero novelty and no mutations.
