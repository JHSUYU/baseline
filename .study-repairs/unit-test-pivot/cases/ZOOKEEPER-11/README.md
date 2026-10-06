# ZOOKEEPER-11: current epoch recovery check

Source: ZooKeeper 3.8.7 `QuorumPeer.loadDataBase()`. The selected line 1175 is the text of the `IOException`; the effective guards are `epochOfZxid > currentEpoch` at line 1165 and `currentTmp.exists()` at line 1169, with the throw at line 1174. The tested source is the unchanged Apache tag in `/tmp/zk387-zk11-20261006` (`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`).

## Original embedded cluster test

`CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile` starts three `QuorumPeerTestBase.MainThread` peers, writes data, restarts them twice, puts the previous value in `currentEpoch` and the current value in `currentEpoch.tmp`, restarts again, and requires the first server to come up. The original Maven JUnit run passed: 1 test, 0 failures/errors/skips, 17.595 s (`../../zk11-native-smoke.log`).

## GraphChecker target closure

The isolated GraphChecker checkout is `/tmp/graphchecker-zk11-20261006` at core `0889fb01f` plus case-local peer registration and file doors. No ZooKeeper source or test was edited. The target spec uses bytecode-resolved allocation line 1174 (`#u46`). The static slice (`../../zk11-slice-r3.log`, `../../zk11-graphchecker/static3/`) includes the target `loadDataBase` region and `readLongFromFile` / `writeLongToFile` IOException doors. The healthy recorded test (`../../zk11-graphchecker/record3/`) exits 0 in 21 s. Its target is `ACTIVATED` for 9 `loadDataBase` occurrences and has zero fatal occurrences. The runtime branch trace has eight true and one false outcomes at the outer guard `#u21`; one peer enters the `currentEpoch.tmp` branch `#u27` (false at the instrumented conditional). The selected fault's full occurrence address is **exactly equal** to an `EXACT/TARGET` `targetClosureEvidence.occurrence` in `targets/zk11/runtime/concolic_region_plan.jsonl`.

The case-local adapter registers each `loadDataBase` receiver as `zk{id}#epochN` for the three peers and three starts. The outer JUnit request still supplies a CLIENT prefix to region occurrence addresses; the file-door trace independently records the per-peer `sourceKey`, so the selector uses both the complete occurrence and `zk0#epoch2`.

## Fault trials and feedback

`trial-tmp-read.json` selects `FAULT:ZOOKEEPER_FILE:READ` at `QuorumPeer.readLongFromFile#u12`, source `zk0#epoch2`, second hit of its complete occurrence. This is the `currentEpoch.tmp` read after the target's temp-file guard. In `../../zk11-graphchecker/trial1/runtime/runtime_trace.jsonl`, `FAULT_MATCHED` is seq 181772 and `FAULT_APPLIED` is seq 181774. `readLongFromFile` then exits with `java.io.IOException` at seq 181801. `loadDataBase` exits with `java.lang.RuntimeException` at seq 181851. `FAULT_TRIAL_SUMMARY` reports requested=1, matched=1, applied=1, `targetAfterFault=false`. The unchanged test fails its server-up assertion after the injected peer cannot start; the selected target `new IOException` at line 1174 did not execute. Trial wall time was 83 s (`../../zk11-trial1.log`).

The five independently selected trials are recorded with exact selector and trace paths in `trials.json`. Every trial matched its complete occurrence address, site, `sourceKey`, and hit ordinal and applied exactly one IOException. The time includes each full GraphChecker recording and original test.

| Trial | Point | Time (s) | JUnit | Target guard after fault | New branch outcomes, global / closure |
| --- | --- | ---: | --- | --- | ---: |
| 1 | `zk0#epoch2` temporary epoch READ, hit 2 | 83 | assertion failure | no | 10 / 1 |
| 2 | `zk2#epoch0` initial epoch WRITE, hit 2 | 33 | startup failure | no | 5 / 0 |
| 3 | `zk2#epoch2` final restart READ, hit 2 | 48 | pass | yes | 7 / 1 |
| 4 | `zk2#epoch2` final restart READ, hit 1 | 50 | pass | yes | 9 / 1 |
| 5 | `zk2#epoch1` middle restart READ, hit 2 | 72 | wait timeout | no | 5 / 1 |

The union of new instrumented branch outcome pairs is 12 globally and 1 in the target skeleton's methods plus file read. This is trace-based branch feedback, not whole-program code coverage. All faulted plans retain the target region and contain zero `GAP` events. In trials 3 and 4, the target guard on `zk0#epoch2` executes after the fault; its ancestor occurrence remains `TARGET/EXACT` in the **faulted** GraphChecker plan. Trial 3 also retains the faulty peer's exact target occurrence; trial 4 drops that peer's occurrence after the early read error, as the dynamic graph should. The target peer's exact occurrence remains selected. No trial executes the selected target `new IOException` or finds a new bug.

## Exhausted observed closure classes

The healthy target region contains exactly 20 file I/O markers. `closure-partition.json` lists every sequence, source key, operation, hit ordinal, and exact target occurrence. Partitioning by phase and file gives all ten classes below; peers within a row execute the same `loadDataBase()` control flow on their own snapshot directories.

| Phase and operation | Markers | Trial | Why the selected `currentEpoch.tmp` absence branch cannot occur |
| --- | ---: | --- | --- |
| Initial `currentEpoch` WRITE | 3 | source | Before test creates tmp; a failed peer prevents `LaunchServers` from completing. |
| Initial `acceptedEpoch` WRITE | 3 | 2 | Same startup outcome, observed in trial 2. |
| Middle `currentEpoch` READ | 3 | source | IOException is not the caught `FileNotFoundException`; middle restart waits for every client and cannot reach final test phase. |
| Middle `acceptedEpoch` READ | 3 | 5 | Same middle restart outcome, observed in trial 5. |
| Final other-peer `currentEpoch` READ | 2 | 4 | Read is on zk1/zk2 and does not mutate zk0's tmp file; trial 4 retains the zk0 guard. |
| Final other-peer `acceptedEpoch` READ | 2 | 3 | Same peer-local effect; trial 3 retains the zk0 guard. |
| Final target-peer `currentEpoch` READ | 1 | source | IOException aborts zk0 before the selected guard. |
| Final target-peer `currentEpoch.tmp` READ | 1 | 1 | The `exists()` guard is already true; trial 1 then aborts zk0. |
| Final target-peer `currentEpoch` WRITE | 1 | source | After the selected guard, before the atomic writer constructor; no later restart. |
| Final target-peer `acceptedEpoch` READ | 1 | source | After the selected guard; no later restart. |

This follows the unchanged source precisely: `CurrentEpochWriteFailureTest.java:83-87` synchronously writes `currentEpoch` and `currentEpoch.tmp` for zk0, then restarts only once. In `QuorumPeer.loadDataBase()` lines 1152-1201, the target IOException at line 1174 requires `epochOfZxid > currentEpoch` **and** `currentTmp.exists() == false`; a plain IOException at a read is propagated to the outer catch as a RuntimeException. The READ door is immediately before `BufferedReader.readLine()` in `readLongFromFile()` (lines 2184-2195), so it cannot remove the file. The WRITE door is immediately before `new AtomicFileWritingIdiom(...)` in `writeLongToFile()` (lines 2213-2221), so it cannot start a rename or deletion; `setCurrentEpoch()` calls this writer only after the guard. The two final other-peer injections kept the zk0 target region `EXACT/TARGET` with its guard after the applied fault and no blocking graph gaps; neither executed the target throw.

The trace also has 24 markers outside the exact target region, admitted only as `CANDIDATE/SHARED_LOCATION_DEMAND_V1`: 18 epoch WRITEs during leader election (6 initial, 6 middle, 6 after the final selected guard) and 6 client-create KeeperException choices in the two `writeSomeData()` calls. Early election writes use the same pre-constructor door; if the test advances, its later explicit tmp write supersedes them. The six final-election writes occur after the selected guard. Each `writeSomeData()` propagates a client-create exception out of the test before tmp creation. These markers add no untested class that can remove zk0's tmp file while keeping the selected guard. The 44-marker accounting is in `closure-partition.json`.

Under this **observed closure, original JUnit workload, and IOException/KeeperException door model**, the queue is exhausted by operation/timing equivalence. Five strict trials represent the viable behavioral classes; two retain the selected target and neither fires its exception. The stopping reason is `closure_equivalence_exhausted`, not a claim about arbitrary filesystem failures, alternate workloads, or defects elsewhere. The three failing trials are expected consequences of injected errors and are **not** coordination bugs.

The case-local GraphChecker adapter and experiment declarations are archived in `adapter-source/` so the trial can be resumed without relying on `/tmp` worktree edits. The target spec continues to use line 1174, while the original selection manifest remains at line 1175.

## Trace storage

The 16 completed `runtime_trace.jsonl` and `schedule.jsonl` streams under
`../../zk11-graphchecker/{record1,record2,record3,trial1,...,trial5}/runtime/`
are stored as `.jsonl.gz`. Each archive was decompressed and verified against
its original SHA-256 before the uncompressed copy was removed. Sizes and both
hashes are in `trace-archive-manifest.json`. To reaggregate an archived run,
restore the required stream with `gzip -dk <file>.jsonl.gz`; the case results
and trial selectors have not changed.
