# HBASE-17 legacy fault-run actor identity audit

This independent, read-only audit covers the completed legacy checkpoint `r001`–`r039` for the unchanged HBase 2.6.6 `TestReportRegionStateTransitionFromDeadServer.test`. Interrupted `r040` is excluded. The checkpoint and per-trial audit are preserved under `cases/HBASE-17/independent/legacy_actor_phase/`; the raw seed and trial logs remain on node1 under `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17/independent/logs/`.

The original JUnit source at `/users/ZhenyuLi/hbase/hbase-server/src/test/java/org/apache/hadoop/hbase/master/assignment/TestReportRegionStateTransitionFromDeadServer.java:165–178` defines `rs0` as the source and aborted RegionServer, `rs1` as the move destination, and `rs2` as the third RegionServer. In each run, the `ABORTING region server ... For testing!` log identifies `rs0`, and `Adding ... move to ... record at close` identifies `rs1`. The remaining RegionServer RPC peer is `rs2`; `RegionServerStatusService` addresses the master and `META_PUT` is local. This maps changing host:port values to stable logical actors.

For every planned fault, I matched the selector in its parent prefix run (the healthy seed for step 1) to the child run's `HBASE17 IO` peer and same-sequence `HBASE17 FAULT_APPLIED` event. A trial counts as **identity-proven effective** only if the existing checkpoint marks all planned faults strictly applied, B5 occurs after the final fault, and every planned fault reaches the same logical actor as in its parent run. The legacy selector contains operation, callsite, thread role, and ordinal; its `OTHER` field does not encode the RegionServer actor. The old controller's strict match alone therefore cannot establish this last condition.

| Measure | Completed legacy runs |
| --- | ---: |
| Attempts (`r001`–`r039`) | 39 |
| Strictly applied fault plans | 34 |
| Strict plans with post-fault B5, old effective denominator | 23 |
| All fault steps retain logical actor, high-quality effective | 10 |
| Post-fault B5 but at least one changed actor | 13 |
| Changed-actor fault steps across those 13 runs | 22 |

- **Identity-proven (10):** `r001`, `r002`, `r003`, `r004`, `r007`, `r011`, `r017`, `r023`, `r032`, `r034`.
- **Changed actor (13):** `r006`, `r008`, `r010`, `r014`, `r019`, `r024`, `r026`, `r027`, `r029`, `r030`, `r033`, `r035`, `r036`. These are observations, but they cannot count toward the identity-matched effective budget.

Two examples make the mismatch directly reproducible from the node1 logs:

1. The seed's source and destination are established at `logs/seed.log:1536,1538`. At `logs/seed.log:1508`, `ClientService.Mutate#CALL` occurrence 8 has peer `ms1105.utah.cloudlab.us:43127`, the third RS. In `logs/r033.log:1538,1540`, the move destination and aborted source are `:37307` and `:45089`; at `logs/r033.log:1504–1506`, the **same selector** is injected at peer `:45089`, the source RS.
2. `logs/r002.log:1554,1556` identifies destination `:43653` and source `:32959`. At `logs/r002.log:1728`, `ExecuteProcedures#PROCEDURE` occurrence 1 goes to `:33647`, the third RS. `logs/r006.log:1554,1556` identifies destination `:39099` and source `:32879`; at `logs/r006.log:1717–1719`, the same selector's third fault is applied to `:39099`, the move destination.

The source checkpoint records 23 strict post-fault B5 runs, but the independently verified identity-matched numerator is 10. This audit does not assess any subsequent V2 run with an endpoint-role selector.
