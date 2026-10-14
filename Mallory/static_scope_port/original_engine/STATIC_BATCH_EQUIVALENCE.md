# Same-Scene static batching experiment (2026-10-13)

**Decision:** do not batch targets in one Soot `Scene` yet. The second target's original GraphChecker artifacts changed, although two fresh JVM runs of that target were byte-identical. No production engine or campaign pin was changed by this experiment.

The source pin was `c041bccc6cc7e23eae4d8d6afe370b384b586112`; the source-built original-engine JAR had SHA-256 `96a65cc64b388f6ce349cecd05d2c27a5498e15978d5d34019236ab1a158b100`. Both targets used the same ZooKeeper 3.8.7 compiled class tree and ordered dependency classpath. Target 1 was `Learner.registerWithLeader` branch at line 515 (`ZOOKEEPER-07`); target 2 was `Follower.followLeader` branch at line 98 (`ZOOKEEPER-05`, resolved fatal exception construction at line 103). The original loop bound was 3.

`ScopePlanner.run()` resets Soot, loads classes, runs packs, and indexes methods for each target; the original seed bridge then constructs a fresh `SeedBackwardStaticAnalyzer` on that Scene. A probe ran target 1 through `ScopePlanner.run()` and then target 2 directly through `MalloryOriginalSeedBridge.analyze()` without resetting Soot. A second probe restored all 5,563 captured Jimple method bodies before target 2. The target 1 run took 77.4 s; the second target took 55.4 s without body restoration and 53.9 s with it. These are feasibility timings, not a validated speedup.

The comparison hashed **decompressed bytes** for `.gz` artifacts and raw bytes for other artifacts. Two independent fresh-JVM target 2 runs matched on all nine original artifacts. The reused-Scene second target differed as follows:

| Artifact | Fresh target 2 SHA-256 | Reused Scene SHA-256 | Reused Scene after body restore SHA-256 |
| --- | --- | --- | --- |
| `static_scope_map.jsonl` | `f75e4882ce2a16ec677a2707aefe861b7ce6b7482fdb18dd709c59502af84a46` | `2cb5261caaddf66ec11967d0cdc83a14cb2b758a772c995318afe31784f6495a` | same as reused |
| `scope_frontier.jsonl` | `ac7aa1b99a1da4094946e6a38163eeb27c3678933c571fbda5aa0f1d72ae72e2` | `f4a790edd0f3a4797097e80a388ea06c40e77bca47d11605640ea9743713a703` | same as reused |
| `candidate_dataflow_edges.jsonl.gz` | `2ccf3dd74bdfa0b52c88ee37f121d402e2d98d8b767d0f4ea351d69865fc1888` | `c1a25b0b32afee4ea36f323da60caea3618203be280b3d8dc6dbc962452216f8` | `e87cbcc5e8b478c83ea7ffcb986be13428dc28eff9cc62ce206b90c05df45e09` |

The candidate edge row count was 88,547 fresh versus 88,549 in either reused run. Without restoration, the other six artifacts matched. With restoration, `original_target_jimple.txt` also differed, while the remaining five artifacts matched. Thus restoring bodies alone did not recover equivalence. Output differences include Soot local names and downstream edge/site identities; the experiment does not isolate the exact mutable state responsible.

The read-only evidence is under `/dev/shm/mallory-returnonly-cache-20261013/scope-two-target-{zk05-alone-v2,zk05-alone-v3,runner}` while that temporary workspace exists. A batching implementation needs an immutable per-system index plus target-isolated mutable state, and must pass byte-for-byte comparison of **all** original artifacts for at least two targets in both target orders before use in the 102-case campaign.
