# ZOOKEEPER-06 selected target instance and Finalizer closure

This is a read-only re-audit of the frozen `formal-region-v2` campaign under
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-06-20261014-native-prep-v1/state`.
No JUnit or fault trial was rerun, and the formal results table is unchanged.
The per-trial, pinned receipt is
[`audits/ZOOKEEPER-06-selected-instance-20261014.json`](audits/ZOOKEEPER-06-selected-instance-20261014.json).

## Root cause of the apparent target gap

The earlier audit required **every** `native_target_occurrence_ids` entry to
belong to the original Finalizer plan. That field is a set of observed target
checks, not the one target activation selected by the original target resolver.
`region_state_graph._validate_target` joins `TARGET_CHECK` receipts using
target site, physical actor, epoch and ordinal. An ordinal of one is local to
each occurrence, so multiple target activations on the same actor may all
enter `targetCheckOccurrenceIds`. A check on a different actor may also appear
in the raw trace. The Finalizer's selected closure is anchored to the
resolver's single `selectedOccurrenceAddress`; unrelated observed checks need
not be members of that closure.

For frozen `r0001`, `selectedOccurrenceAddress` identifies a `zk-peer-3#epoch0`
activation of `REGION.42ddd4bc-c8ac-3379-9d7f-d502dc2fd63c`. Original
GraphChecker `OccurrenceAddress.id()` maps its exact Finalizer plan row to
`3605a1702239743a`. That ID has an actual `TARGET_CHECK` receipt and is in
the 167-ID closure. Another check ID, `37f0c5ae0e55d546`, is also in the
closure but belongs to another activation. The third summary ID,
`cc150d0dad7b4b3e`, belongs to an unselected activation and is outside the
closure. The raw trace has two further checks on `zk-peer-2#epoch1`, neither
of which changes which `zk-peer-3#epoch0` activation the resolver selected.
The target check's static region
`REGION.b3eb0be6-3e8d-3adf-81c3-07d7060c0e07` is folded into the selected
activation; this is not a target-region or ID-schema mismatch.

## General audit correction and results

`audit_region_closure.py` now joins the selected address through the original
GraphChecker ID function and requires exactly one matching Finalizer plan row,
the same ID in the reported target-check set, and an exact raw `TARGET_CHECK`
receipt on the selected physical actor and epoch. It verifies the frozen
engine, plan, fault-event and native-summary hashes. Other observed target
IDs are reported separately. The fault-membership calculation still tests
the last `FAULT_APPLIED` occurrence against that trial's original Finalizer
members.

| Frozen strict, target-retained trials | Selected target in exact closure | Last applied fault in closure | Other observed target IDs outside closure |
| ---: | ---: | ---: | ---: |
| 102 | 102 | 81 | 102 total (one per trial) |

All 81 recomputed fault-membership flags agree with the saved result flags;
there are zero mismatches. Thus the old 81 can be described as **faults within
the selected target's original Finalizer closure**. That is an overapproximated
membership result, not proof that each fault causally changed the target
check, triggered its exception, or revealed a bug. In `r0001` the target
exception was not triggered.

No new campaign is needed to correct this membership count: the frozen plan,
raw receipts and pinned engine suffice. A new campaign would be needed if the
runtime hooks, target selection, static region plan, or injected fault
sequence changed, or if a stronger fault-to-target path claim required
causal observations absent from these frozen traces. Such a campaign must
start with a fresh healthy seed under its own source and engine pins.

The targeted fixture tests cover duplicate same-actor ordinal-one checks,
a check on another actor, a missing selected plan row, and a missing exact
selected runtime check. They pass with:

```text
python3 -m unittest Mallory.native_graphchecker_feedback.test_audit_region_closure
```
