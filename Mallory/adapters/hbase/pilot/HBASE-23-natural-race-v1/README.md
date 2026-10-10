# HBASE-23 natural-race admission, node1

This package keeps the unmodified `TestProcedureManager#testSimpleProcedureManager` MiniCluster
JUnit as the workload. Both pinned configurations are case-local copies of the fa5f release
configurations. No HBase source, compiled class, site definition, or frozen core is changed.

## Why the exact check is intermittent

`ZKProcedureCoordinator.sendGlobalBarrierReached` creates the reached barrier and then, for each
member, calls `watchAndCheckExists` before reading data and checking PB magic at line 127. The
line-127 check is reached only if the member completion child already exists at that synchronous
scan. If the child appears afterward, `nodeCreated` handles its payload at the distinct callback
guard near line 211. `TestProcedureManager` waits for the overall `execProcedureWithReturn` result;
it does not order RS completion before the synchronous scan. The v13 seed hit the named,
nonthrowing exact check once. The v21, v22, and v23 fa5f seeds each entered and exited the named
method but had no `TARGET_CHECK`, despite passing JUnit and validating the target class hash.
This is an input timing race, not evidence of a missing instrumented site or missing actor name.

## Admission and campaign

`run.py preflight` checks the frozen release, both config hashes, all runtime artifact hashes,
source equivalence, selected JUnit source hash, target, and budgets without starting a JVM.
`run.py run` requires node1 dispatch capacity (`MALLORY_NODE1_CAPACITY_GRANTED=1`) and holds the
lane9 lock. It allows up to 12 fresh healthy runs. Each run has its own output, audit, receipt,
and tar archive. Admission requires passing JUnit, a valid site catalog, a named `zk-coordinator`
exact @127 hit, a nonthrowing target, and at least one injectable door. The strict offline audit
is retained as a separate causal result, not silently counted as passing.

After admission, the worker tries up to 12 fresh full starts because a full campaign's own
healthy r0000 can miss this race. It retries only after `healthy_seed_invalid` with zero fault
trials. Every start has a separate output and audit. Only one accepted campaign can spend the
pinned budget of 80 fault trials, 3600 seconds, and at most 3 faults per trial. The worker stops
when that campaign reaches its natural `budget_exhausted` or `queue_exhausted` terminal status,
or when the bounded fresh-start attempts are exhausted. A missed healthy check yields
`admission_inconclusive` or `full_startup_inconclusive`; it is not a no-cluster-test finding or a
completed full campaign. Receipts preserve each attempted seed and cumulative wall time. The
script never changes the shared checklist.

For a full campaign, natural terminal status alone marks completion. Its r0000 target, JUnit,
door, and actor annotations remain in the admission receipt, alongside the offline audit status;
an absent causal path or failed offline audit does not reclassify a naturally completed full run.

Dispatch owns the node1 host capacity gate. Do not launch `run.py run` while another node1 JVM
is active. The worker checks for an active JVM before each new attempt and refuses to start then.

## Separate candidate for source review

A new MiniZK JUnit could create a valid PB-prefixed reached/member child before calling
`sendGlobalBarrierReached`, making @127 deterministic. That establishes the code path directly,
but it changes the workload ordering from the original MiniCluster test and may bypass the
RPC-to-procedure causality under study. Treat it as a separately reviewed candidate; it is not
part of this package's admission or full campaign.
