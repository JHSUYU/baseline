# HBASE-18: `TransitRegionStateProcedure.confirmOpened` immediate retry guard

## Original test and exact target

The mapped HBase 2.6.6 original `TestTransitRegionStateProcedure#testRecoveryAndDoubleExecutionUnassignAndAssign` passed in a MiniHBaseCluster, but its three selected-table `confirmOpened` calls saw `OPEN`. JaCoCo showed zero instructions on guard line 323 and throw line 325. It therefore cannot establish this check's behavior.

The unchanged original MiniHBaseCluster `TestExceptionInAssignRegion#testExceptionInAssignRegion` does execute the false side of the guard during a failed `preOpen` assignment. The counted healthy run passed, issued two selected-table OpenRegion RPCs, executed the direct immediate-retry-max marker once with maximum 3, covered line 323, and did not cover throw line 325. The baseline test deliberately throws once from its region coprocessor; that exception is distinct from the selected `confirmOpened` exception.

## Runtime method

This case uses its own ByteBuddy agent for the original JUnit test body, `RSProcedureDispatcher` OpenRegion RPC send, `confirmOpened` entry/exit, and `AssignmentManager.getAssignRetryImmediatelyMaxAttempts` guard marker. JaCoCo records production coverage in eight assignment and dispatch classes. The agent's RPC selector only matches table `test` during the original test body. It parses the original procedure log to map each OpenRegion child procedure to its parent `TransitRegionStateProcedure` and encoded region, then requires all applied faults to share the same parent, region, and region ID. Feedback counts a trial only when the direct guard marker occurs on that same parent and region after the final applied fault. Matching an exceptional method exit alone does not count as reaching the guard.

Each trial has a unique ordered selector plan, raw log, JaCoCo execution file, exit code, elapsed time, exact match/apply sequence, target calls, JUnit outcome, and coverage delta in `result.json`. Valid new production method or branch coverage or a new observed I/O family generates nearby plans. The initial seed queue was switched to this feedback policy after eight trials; a later refinement retained all issued plans and removed queued candidates justified only by observing the already known recovery exception. Two aborted, unfinished speculative prefetch runs are preserved separately and excluded from counted trials and feedback. Counted rounds 1 and 2 reuse earlier calibration raw files without rerunning them.

The campaign completed 80 unique plans under the eight-fault limit. All 80 achieved strict ordered injection, same parent/region identity, post-final-fault guard reachability, and a passing original JUnit. The union of selected production branches grew from 258 to 297 (+39). Twenty-three trials observed the selected recovery `HBaseIOException`; none observed another target exception or received a new-bug mark. Trials 73–80 added no new production method, branch, or observed I/O family, so the conditional 128-trial extension did not trigger. The per-trial elapsed times and selector sequences are in `result.json`.

The runtime is graph independent: it uses the unchanged original JUnit, local ByteBuddy and JaCoCo instrumentation, and observed OpenRegion RPC I/O. It does not use a GraphChecker JAR, prewoven classes, `region_skeletons`, `static_scope_map`, static aggregate, or closure data. Source files in `native/source/` are snapshots of HBase `rel/2.6.6` commit `97a51ab9e3cf9f9d21bf08c3b1e52c962579ef2b` for audit.

## Exception classification

HBase source lines 323–326 intentionally throw `HBaseIOException("Failed confirm OPEN...")` to back off and retry after more than the immediate retry maximum. Four ordered `DoNotRetryIOException` OpenRegion RPC faults independently reproduced that exact selected exception for the same parent procedure and region after the final fault; the original JUnit then passed. The independent replay `native/r002_replay.log` confirms the sequence. This recovery exception is recorded separately from unexpected target exceptions and is not marked as a new bug. The coprocessor's baseline `preOpen` exception is likewise not a new bug.

The machine-readable result and per-file SHA-256 archive manifest are `result.json` and `evidence/native-manifest.json`. The evidence archive contains the runner, agent source and binary, source snapshots, healthy and trial logs, JaCoCo files, exit codes, replay, and interrupted setup evidence.
