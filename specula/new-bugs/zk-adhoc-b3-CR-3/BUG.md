# zk-adhoc-b3 CR-3 (tier B): after a live restore the manager scans the old tree forever and deletes restored nodes

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-b3`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **tier:** B
- **case/finding:** zk-adhoc-b3/CR-3
- **defect:** `ContainerManager.zkDb` is final (L45), set once at `ZooKeeperServerMain`:170, and is not rebound after a live restore
- **consequence:** the manager keeps scanning the old tree and deletes restored nodes
- **trigger:** needs an admin restore without a restart

**Specula's finding CR-3:** After admin restore, ContainerManager keeps scanning the old ZKDatabase and its stale deleteContainer posts delete restored persistent nodes

- **Cause:** ContainerManager holds the ZKDatabase it was built with in a final field and ZooKeeperServer.restoreFromSnapshot swaps the server's database without rebinding it, so candidates come from the frozen old tree while PrepRequestProcessor validates the path-only deleteContainer against the new tree and does not check that the node is a container.
- **Trigger:** A path is PERSISTENT in a snapshot and later becomes an empty or never-used container on the running server (or an expired TTL node, by code reading); an operator restores the snapshot through POST /commands/restore on that live server.
- **Consequence:** At the next container check the restored childless persistent node is deleted, a client getData on it fails with NoNodeException thrown at FinalRequestProcessor.handleGetDataRequest:674, and the path is deleted again after every re-create for as long as the manager runs (observed over 3 cycles; recovery by restart is argued from the code, not run).
- **Premises:** The admin restore command is enabled (default) and the operator has ALL on /. Restore runs on a live server whose old tree holds an empty or never-used container (or expired TTL node, not run) at a path that is childless and non-ephemeral in the restored data. Standalone ZooKeeperServerMain was exercised; LeaderZooKeeperServer has the same binding but was not run. Restore is outside the modeling brief's fault model and was never model-checked; it is a supported operator command, not a fault.

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-b3` (all phases) | 2h49m | 100.6M | $74.96 |
| of which: confirming this finding | | 2.3M | $2.72 |

Time is active time; quota sleeps are excluded.
