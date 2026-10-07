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

After trial 018 closed at 18 attempts/8 effective, the queue held 201
singletons, 43 pairs, 51 triples and 62 four-fault plans. The observed strict
retention was 4/5 for pairs and 4/13 for triples, so the controller reserved
two slots per five attempts for singletons, two for pairs and one for depth
three or greater. `full-state.json.scheduler_migration` records the complete
checkpoint, preserved queue depths and before/after controller SHA-256;
`scheduler_policy_sha256` is included in later ledger rows. This only changes
the order of untried plans.

At the trial 101 complete checkpoint, the previous 30 trials showed strict
retention of 5/12 for singletons, 6/12 for pairs, and 0/6 for triples; triples
also added no production method in that window. The controller therefore
reserved four of ten future attempts for singletons, five for pairs, and one
for depth three or greater. `scheduler_migration_v2` records the independent
trial 101 audit boundary, previous checkpoint/ledger SHA-256, exact pending
and seen queue SHA-256, yield by depth, and old/new controller and policy
hashes. No completed outcome, queued plan, seen ID, or fault budget changed.

At the trial 135 start gate, node0 free space fell below 3 GiB before any
trial 135 raw directory was created. The controller exited with a selected,
unstarted trial 135; attempts/effective remained 134/69. The node2 mirror
already contained trials 001–120. `offload_derived.py` independently compared
the SHA-256 of all 360 `covered_*.txt` files with the remote copies, performed
a remote-to-local read smoke, and removed only those node0 derived coverage
texts. `derived-offload-001-120.json` records every SHA-256 and the 228,872,192
allocated bytes released. Local traces, JaCoCo, run receipts, plans, console,
healthy controls and any candidate raw remain. `full_audit.py` verifies
offloaded files against node2 on every recount; its logical raw manifest SHA
was identical before and after offload. Trial 135 retains its original ID.

The full stage ended at 150 original JUnit attempts and 80 strict effective
trials, with no inflight run. Its last eight effective trials added no new
production method or stable relevant I/O family, so the conditional 128/10
extension was not taken. All 80 effective original JUnits passed, and all 86
selected equal-version JSON checks were true; the selected assertion did not
throw. Effective trials added 186 production probes, 10 methods and 186 lines
over healthy controls. The independent [full audit](full-audit.json) checked
1,240 logical raw files and every offloaded coverage SHA with zero issues.
Fifteen block receipts cover the node2 per-file SHA mirror through trial 150;
a final checksum dry run found no difference among files retained on node0.
The [terminal receipt](terminal-receipt.json) records the source and JUnit
hashes, actor/guard counts, coverage, elapsed time, and remaining 1,348
untried plans. An [independent TSV recount](independent-recount.json) uses a
separate event parser without importing the campaign oracle and independently
matches 150 attempts, 80 effective trials, 125 exact ordered injections, 86
selected guards, 86 true JSON equalities, and zero target throws. No new bug
was confirmed.
