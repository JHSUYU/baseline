# HBASE-17 V2 source and failure review

## Selected guard and original workload

The released HBase 2.6.6 source checkout is `badd7a2818`. The exact target is
`TransitRegionStateProcedure.confirmClosed`, line 379:
`assert regionNode.isInState(State.ABNORMALLY_CLOSED)`. A `CLOSED` region
returns earlier, and a `CLOSING` region throws `HBaseIOException` for retry.
An `AssertionError` would be a target failure only if the original JUnit
reaches this assertion with a different state after the injected fault.

The unchanged original `TestReportRegionStateTransitionFromDeadServer.test`
at lines 165–195 moves one region from `rs0` to `rs1`, aborts `rs0` in the
test itself, and waits for the region transition procedures to finish. The
test's own abort is part of the healthy workload, not a campaign injection.
`RegionPlan` supplies source and destination, while `rs2` is the third
RegionServer. The V2 healthy receipt validates these roles and exact B5
evaluation across two passing runs. A campaign trial is marked strict only
when every planned fault matches the specified logical role and target-region
resource within that trial; the raw event audit independently checks this.

## Direct master-abort outcomes

`RegionStateStore.updateRegionLocation` lines 158–203 writes the target
region's state to `hbase:meta`. Its nested write path at lines 231–248
catches an `IOException`, calls `master.abort`, and rethrows. Consequently,
an injected `META_PUT` `IOException` at this point can make the original
test's master unavailable before the procedure reaches B5. That is a direct
fault effect, not an independently established coordination bug.

| Trial | Raw log chronology | Original JUnit / target |
| --- | --- | --- |
| r001 | fault line 1713; `FAILED persisting` line 1714; HMaster abort line 1730 | JUnit 0/1; B5 absent; `Waiter` sees `NullPointerException` after master abort |
| r013 | response timeout line 1531, then `META_PUT` fault line 1965; persisting failure line 1966; abort line 1983 | JUnit 0/1; B5 absent; same test wait failure |
| r049 | fault line 1500; persisting failure line 1501; abort line 1517 | B5 absent; target-lost run bounded and stopped after 208.96 s; original JUnit did not finish |
| r057 | fault line 1467; persisting failure line 1468; abort line 1487 | B5 absent; target-lost run bounded and stopped after 113.25 s; original JUnit did not finish |
| r085 | fault line 1525; persisting failure at `CLOSING` line 1526; abort line 1545 | B5 absent; target-lost run bounded and stopped after 140.00 s; original JUnit did not finish |

The r049/r057/r085 explicit stop receipts are in
`evidence/v2-early-stop/`. The r049 first termination hit the timing wrapper,
then its exact remaining timeout and Java child were terminated and verified
absent. Its checkpoint elapsed field must be repaired from the 208.96-second
receipt after the controller exits. The r057 wrapper printed its measured
113.25-second elapsed time. The r085 wrapper printed 140.00 seconds after
the exact Java child was stopped. All three remain attempts and contribute zero
effective post-fault B5 reaches.

## Ordering boundary

In r066 the first three matched faults precede exact B5 (raw lines 1531,
1559, 1574). B5 evaluates true at line 2023. The fourth matched response
fault follows at line 2031, and the original JUnit passes. This trial is
strictly matched, but B5 is **before the final fault**. It cannot enter the
post-final-fault target-retaining effective count.

The same ordering boundary occurs in r079: the first fault is at line 1496,
B5 evaluates true at line 2019, and the second fault is at line 2028. Its
original JUnit also passes. It is a strict attempt but not an effective
post-final-fault target trial.

r101 has the same ordering: first fault line 1500, B5 true at line 1995,
second fault line 2003, and passing JUnit. It too remains outside the
effective count.

## Final V2 result

The bounded V2 campaign stopped naturally at its 80 post-final-fault B5
trial budget. It used 115 attempts and 6,573.01 seconds of measured trial
time. The 86 controller-strict trials comprise 80 target-retaining trials
and the six target-lost or ordering cases documented above; 29 planned
sequences did not match every requested I/O event. The independent raw
peer/RegionPlan audit proves the actor identity of all 86 strict trials and
all 80 effective trials, with zero mismatches. Effective trials injected
200 ordered fault events, to a maximum sequence depth of six.

Of the 115 unchanged-original JUnit runs, 110 passed. r001/r013 failed only
after their injected META write caused the direct master abort before B5.
r049/r057/r085 were bounded target-lost runs whose original JUnit did not
finish. The raw trace records **zero** false outcomes at the selected B5
assertion, **zero** `confirmClosed` target exceptions, and **zero** JUnit
failures after the final fault followed by B5. The candidate list is empty;
this campaign found no confirmed new HBASE-17 bug.

The fixed V2 production JaCoCo scope grows from 228 to 229 covered methods,
334 to 361 covered branches, and 1,115 to 1,187 covered lines relative to
the two-seed healthy union. Stable I/O sites grow from 11 to 17 when site
identity excludes occurrence ordinal. The last 20 trials add neither
production coverage nor a stable I/O site, so the conditional extension to
128 effective trials is not invoked. The earlier coarse-identity rounds
remain separate historical evidence and are excluded from these V2 counts.

Exact per-trial plans, elapsed time, matched/applied events, target timing,
JUnit outcome, and coverage deltas are in `trial_ledger_v2.json`; the
controller state is `checkpoint_v2.json`. The final actor audit and complete
raw-log/JaCoCo archive are linked from `result.json`.
