# zk-adhoc-b3 MC-1 (tier A): silent, durable delete of a client's PERSISTENT znode; default config

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-b3`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as b3/CR-2.

## Explanation (verified)

- **tier:** A (tier medium confidence)
- **case/finding:** zk-adhoc-b3/MC-1
- **defect:** `ContainerManager.checkContainers` (L140-160) posts a path-only `deleteContainer`; `PrepRequestProcessor` (L326-338) checks only `childCount` and `EphemeralType == NORMAL`, not that the node is still a container
- **consequence:** a client's PERSISTENT znode re-created at the path is silently and durably deleted; `getData` throws at the target (`FinalRequestProcessor`:674)
- **trigger:** default configuration, no fault; a container replaced by a persistent node between scan and post. Reported losses are from a stress test; production frequency unknown

**Specula's finding MC-1:** Stale ContainerManager deleteContainer removes a PERSISTENT node re-created at the path; getData throws NoNode at FinalRequestProcessor:674

- **Cause:** ContainerManager posts a path-only deleteContainer chosen from an earlier scan, and PrepRequestProcessor re-checks only existence, childCount and that the type is not NORMAL, so neither the node's type nor its identity is validated against the scanned container.
- **Trigger:** A client deletes an empty used container and re-creates the path empty, after the manager's scan and before the manager posts that path. Production pacing of 6 ms per candidate widens this window when many candidates exist; a Level 0 run used 1000.
- **Consequence:** The client's PERSISTENT (or fresh CONTAINER) node is durably deleted with no client delete and no error to the client; a later getData throws NoNodeException at FinalRequestProcessor.java:674, and the node stays missing after restart.
- **Premises:** The manager's scan and post are separated in time; candidates are paced at 60000/maxPerMinute ms each. Standalone and leader wiring both post directly into PrepRequestProcessor; both were executed at Level 0 with default settings. No fault injection is needed. The replacement must still be empty and non-ephemeral when the stale request reaches PrepRequestProcessor; controls show a child or an EPHEMERAL replacement survives. A single candidate with no hook was not reproduced at Level 0; Level 0 used 1000 candidates and Level 1 uses the postDeleteRequest test hook.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_stale_container_delete.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-b3` (all phases) | 2h49m | 100.6M | $74.96 |
| of which: confirming this finding | | 2.4M | $3.07 |

Time is active time; quota sleeps are excluded.
