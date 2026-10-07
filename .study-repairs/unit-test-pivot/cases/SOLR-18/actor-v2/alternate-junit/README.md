# SOLR-18 alternate original JUnit feasibility

The first actor V2 campaign is frozen at 845 selected trials and 68 strict
effective trials. Its `campaign-state.json` SHA-256 is
`5df381a7965fffadb09b5b3b132e7ba0e4777150d3aadf46245bbc018a595113`.
This calibration has its own raw directory and checkpoint. It cannot add to the
first campaign's denominator.

Bounded candidates, in order:

1. Original `AliasIntegrationTest#testDeleteAliasWithExistingCollectionName`.
2. Original `AliasIntegrationTest#testErrorChecks`.

Each candidate gets one clean JUnit and, only if it passes, two no-fault
instrumented JUnits. The original test class must retain SHA-256
`7674e0e501483b11108f72129a2a68ff54ae5c6d35c4862d6546a132f439f402`.
The alternate probe changes only the origin label: an alias mutation invoked
through original `CreateAliasCmd.callCreatePlainAlias` is tagged
`CREATE_ALIAS_CMD`. The selected guard must follow the first such mutation
after `TEST_STARTED`, precede the next mutation on that manager and
`TEST_FINISHED`, have versions 1/1 and comparison 0, and belong to the same
live `SolrZkClient` actor as the mutation. All potential fault roots must be
observed before that guard on that actor. This is a new oracle; it does not
reinterpret historical trials.

The two instrumented runs must both pass the unchanged original JUnit and
show the selected guard. Only a stable same-actor selector absent from the
first campaign's 21 roots, and still novel after collection names are
normalized to `/collections/{collection}/state.json`, may seed a separate
fault campaign. Calibration injects no faults. If neither candidate qualifies,
record bounded plan exhaustion and keep `quality_complete=false`.

`calibrate.py --one` runs one pending healthy JUnit under the shared
`unit-test-pivot/jvm-start.lock`, holding that lock from the resource check
through Java exit. It requires at least 10.25 GiB free at launch and at most
four other live business JVMs. At trial boundaries it also requires at least
10 GiB before continuing. Raw evidence remains on node2. Do not start this
calibration while another owner reserves the node2 JUnit slot.

The first candidate passed one clean JUnit and two no-fault instrumented
JUnits. `calibration-state.json` and `healthy-audit.json` freeze their source,
raw SHA-256, same-live-client target window, and 183 stable novel selectors.
Five distinct singleton plans are recorded in the healthy audit.
`pilot.py --one` runs one plan under the same shared lock and keeps a separate
`pilot-state.json` checkpoint. Every trial preserves the unchanged original
JUnit result, ordered injection events, selected guard identity, JaCoCo data,
and production coverage feedback. No pilot result enters the first campaign.

The five-trial pilot closed at 3 strict effective trials. `pilot-audit.json`
independently recounts every raw receipt and SHA-256. The raw/derived pilot
directories were mirrored from node2 to node0 with `rsync -acn` reporting no
differences; `migration-receipt.json` records the dependency, capacity and
mirror checks. The full stage starts a fresh denominator at zero and excludes
all five pilot plans and the old campaign's known plans. Its controller is
`full_campaign.py --continuous`, with atomic `full-state.json` and
`full-ledger.jsonl`; every full trial keeps its original JUnit, ordered fault,
target identity, raw SHA-256 and coverage receipts under the node0 raw root.
Node0 requires at least 3 GiB free and at most four other JVMs at each trial
start. The initial budget is 80 strict effective trials, at most eight ordered
faults and 320 attempts. The bounded 128/10/512 extension requires new
production coverage or a newly stable relevant I/O family in the last eight
effective trials. Exhaustion below the effective budget remains inconclusive.

At the two-trial complete checkpoint, feedback was upgraded to include new
same-client pretarget I/O selectors observed in at least two distinct
effective full trials. It retains at most 24 normalized families, adds at most
16 ordered child plans per effective trial, and excludes previously tested
plans. The policy SHA-256 and migration receipt live in `full-state.json`;
subsequent ledger rows include the policy and controller hashes. This feedback
never changes prior trial outcomes or either earlier denominator.
