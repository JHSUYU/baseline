# SOLR-10 Overseer leader role binding, isolated v1

The v28p pilot planned the exact `OverseerTaskProcessor#run()V@246:door:1`
queue read on the healthy physical `node2`. All eight trials missed: the
Overseer leader executing that door moved to node1, node3, or node4. The
target is `MaintainRoutedAliasCmd.call` at line 116, reached four times by
`TimeRoutedAliasUpdateProcessorTest#test` in the v28a healthy run.

This overlay observes Solr 8.11.4's own `amILeader()` return. `YES` binds the
current `OverseerTaskProcessor` instance to its registered physical node,
epoch, and election ID. `NO` or `DONT_KNOW` revokes it. At the exact queue
door, the registry accepts only a unique live leader binding and assigns a
role ordinal. A plan names `{site, role: "overseer-leader", role_ordinal}`;
the agent resolves that role before applying a fault and records the actual
physical `node` and `epoch` in `FAULT_MATCHED` and `FAULT_APPLIED`. Unknown,
stale, conflicting, or missing decisions never match. Physical plans remain
unchanged.

The integration is isolated in `work/Mallory`; the live agent, adapter,
canonical checklist, and running releases were not changed. The two JARs in
`releases/v1` are immutable inputs. The package-level `RoleBindingRegistry`
and the top-level dependency-free prototype have the same decision logic.

## Pinned execution host and verification

- Intended host: node2, source worktree
  `/users/ZhenyuLi/.mallory-worktrees/solr-routed-alias-v23`, clean HEAD
  `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.
- `OverseerTaskProcessor.java` SHA-256:
  `cae75fa3ae928f085b69dd5d39c4bac978b7d1160692b936b934f8a59838c14b`.
- Solr core distribution JAR SHA-256:
  `e83db498c6af8f3eca14483ab42fd9fe30bbf795ceacab3b4d5eaa66f2461536`.
  Its `OverseerTaskProcessor.class` SHA-256 is
  `98f21c0235c5e9dc7937d67e0a44dfeccd3726582feb2696d7fbe4420ca8a6c0`.
- Target and JUnit source SHAs are checked in `run_pilot_role_v1.py`.
  `preflight-node2.json` is a read-only host receipt. The same checks run
  immediately before every role JUnit invocation.
- The wrapper is named `run_pilot.py` so the existing Mallory Solr JUnit
  receipt gate recognizes and checks the actual test result.

## Bounded path to one pilot

1. Dispatch admits the healthy-only
   `config-role-v1-healthy-node2.json` on node2. It runs one original cluster
   JUnit and captures a fresh role-aware trace. No fault is planned in this
   phase.
2. `prepare_pilot.py` reads that healthy trace and selects role ordinal 16
   only if there is exactly one uniquely bound exact queue door, a later
   exact `TARGET_CHECK`, and an observed causal path to that target. It writes
   a single-fault role plan using the
   `ConnectionLossException` declared by the pinned site catalog. If the
   condition is not met, selection stops for review.
3. Dispatch admits exactly one fault trial, with a receipt binding node2,
   config SHA, and plan SHA. `run_one_pilot.py` requires this receipt and
   executes one trial under the routed-alias lock via
   `run_one_pilot_node2.sh`. `audit_pilot.py` checks a single exact applied event,
   its physical node/epoch, unique election receipt, and target continuation.
   A lost target is recorded as `target_lost` and is not a bug finding.

The canonical `Mallory/core/audit.py` currently accepts physical plan points
only. This isolated role audit is for the bounded pilot. Full fuzzing requires
teaching the core audit the same strict role receipt or materializing a
physical receipt from the applied role event before normal campaign reporting.
The role registry observes uniqueness within the selected single-JVM Solr
MiniCluster test; a separate cross-JVM leader attestation is needed for a
multi-process deployment.

## Tests run

- Isolated agent `mvn -q test package`: 27 tests passed, including unique
  physical leader match and NO/DONT_KNOW/ambiguous rejection.
- Isolated Solr adapter `mvn -q test package`: 13 tests passed, including
  bytecode transformation of the exact `amILeader()` return descriptor.
- `python3 -m unittest -q test_role_plan.py`: 9 tests passed.
- Node2 source/JAR preflight passed without launching a JUnit or fault trial.

The admitted role-v1 healthy JUnit completed in 27.103 seconds: one test
passed, four exact target checks occurred, and all 18 exact queue doors had
unique role receipts on node4/epoch0. Door ordinal 16 has an observed
task-to-handler-to-target path to the fourth check. The separately admitted
one-fault pilot completed in 28.667 seconds. The exact role ordinal 16 fault
matched and applied once on physical node1/epoch0, while the healthy leader
was node4/epoch0. An exact target check followed the injection; the JUnit
passed and no target exception occurred. This is an effective injected trial,
not a bug finding. The v28p 0/8 unmatched result remains unchanged.

`audit_observed_pilot_path.py` independently replays the one-fault raw trace
through the event-time closure analyzer and checks the admission, plan,
healthy result and gzip trace, trial result and raw trace, and receipt hashes.
The applied event `:2941` was on Overseer leader node1/epoch0. The same
election ID remained affirmative at `:2946`, `:2951`, and `:3006`; there was
no intervening negative or different-leader decision. The same Overseer run
thread submitted task `:3002`, which was claimed at `:3003`, entered the
message handler at `:3004`, entered the target region at `:3005`, and reached
the exact target check at `:3007`. All three inter-region edges are observed
and time ordered on node1/epoch0. The SHA-bound result is
`data/mallory/pilot_solr10_role_v1_node2/SOLR-10/observed-path-audit.json`.
This establishes a retained path after the fault, not that the exception
caused the later check. Its classification remains no bug.

## Full campaign on node2

`config-role-v1-full-node2.json` stages 80 fault trials, 3600 cumulative
trial seconds, at most six faults per trial, and a 480-second trial timeout.
It requires the strict event-time and coarse-root gates. The isolated
`run_role_campaign.py` uses the pinned `work/Mallory/core` snapshot for
resumable scheduling and coverage feedback. It converts exact Overseer queue
doors in the target closure into role-stable plans and verifies each role
receipt against the physical node, epoch, and Solr election ID at injection.
The healthy run's physical target node is not fixed across subsequent fresh
MiniCluster runs. An observed `graph.event_path` from the last applied fault
to a later exact target check is required to expand a sequence or promote a
target-exception candidate. The source region's unmatched predecessor root
parent remains documented in the positive pilot audit; its fault-to-target
witness uses no such root link.

The node2 launcher `run_full_node2.sh` requires a separate
`admission-full-node2.json` pinned to the full config, runner, positive pilot
audit, and intended output. Dispatch issued this admission after an
independent node2 resource and lock check. The full campaign is running in
tmux `mallory-solr10-role-v1-full`; its checkpoint is under
`data/mallory/full_solr10_role_v1_node2/SOLR-10`. After terminal status,
the same persistent tmux wrapper invokes `collect_terminal_node2.sh`, which
exports trial plans, results, site catalogs, and event traces with SHA hashes
while excluding build classes and stdout/stderr scratch. The collector was
tested offline against a one-trial terminal fixture. Node2 `--preflight-only`
passed source, JAR, config, core snapshot, and positive pilot SHA checks
without running a JUnit.
