# SOLR-06 multi-fault prefix stability gate (proposed v1)

This is a **future, separate campaign design**, not a result or a change to either active campaign. It applies to the exact SOLR-06 target and pinned source/artifacts in `config-v15a-lane3-promoted-final.json`. The v15a six-fault and v15b one-fault campaigns remain immutable and their trial counts must not be combined for the checklist.

## Measured reason for the gate

At **2026-10-09 18:06:47 UTC**, the nonterminal v15a campaign on node2 had 17 completed fault trials (`r0001`–`r0017`). Exactly 2/17 had all faults applied in order and retained the exact target (`r0001`, `r0003`); 15/17 were `fault_unmatched`. The separate v15b single-fault campaign had 13/13 effective, target-retained trials and no unmatched fault. Neither snapshot contained a qualified target exception. The raw `result.json` files are under `data/mallory/campaign_v15a_lane3/SOLR-06/trials/` and `data/mallory/campaign_v15b_lane1_single/SOLR-06/trials/` on node2; terminal watchers archive and SHA-verify them on node0.

| Trial | Planned point(s) after the first fault | Actual result | `result.json` SHA-256 |
| --- | --- | --- | --- |
| v15a `r0001` | One fault, `pathExists` on node1, ordinal 14 | Applied; target retained | `5c5803da0e677ddfbc67533543adcb3b0afd5d4fc33f30cd7c17766dafc88d81` |
| v15a `r0002` | Add `getLeaderProps` on node2, ordinal 96 | Only first fault matched/applied; `fault_unmatched` | `fff1f61a4a62c9a4b9d824d7d6b53b7fe2e05a43b86ca5e5dfdcf7e12594ef8d` |
| v15a `r0003` | Add `getLeaderProps` on node2, ordinal 207 | Both faults applied; target retained | `442f53af51ac81056120c8abeb23108f3d167510fdd8f1ae3f6f9a71b57dacbd` |
| v15a `r0004` | After `r0003` prefix, add `register` on node1, ordinal 7 | First and third faults applied, second fault missed; `fault_unmatched` | `3dfbb15bc6bf8de4f906c55d91c1df5b1cd852a5bb413e9438cc150bf48b0e92` |
| v15b `r0001` | One fault | Applied; target retained | `d4304e75af4fd9872627336ed5d3462e04937b1a4d5aceccd5e6601e4f0a4fac` |
| v15b `r0002` | One fault | Applied; target retained | `7db77c1cdcd493c04f980d13273ca7a03efd533ee676e5899266cc107fb610af` |

The point ID includes `{site, node, epoch, door_ordinal}`. These data show that a door seen after one fault in a parent run is not necessarily replayable with the same ordinal and ordering in a fresh MiniSolrCloudCluster. They do **not** show a target bug. `workload_failed_other` after an applied fault is likewise separate from the exact target-exception oracle.

## Versioned follow-up algorithm

1. Take only a parent sequence whose independent feedback confirms every planned fault applied, in order, on a named actor, with an exact target check after the last fault. Preserve the parent trial and plan hashes.
2. Replay that **unchanged prefix twice** in two fresh MiniSolrCloudCluster trials. Require both replays to meet the same exact application, identity, ordering, and post-fault target conditions. An unmatched prefix is pruned; an unrelated JUnit failure is recorded separately.
3. For each valid replay, enumerate named, in-closure I/O doors observed **after the final prefix fault and before the target check**. Form candidate IDs from `{site, node, epoch, door_ordinal}` and the typed exception. Mutate only the intersection of the two replay sets; record both supporting event IDs and trace hashes. This is a stability filter, not proof that the next run will match.
4. Favor lower observed ordinals and untried site/actor pairs; retain a bounded one-fault breadth share so a volatile deep prefix cannot monopolize the queue. Add at most one fault to a stable prefix, as in CrashFuzz-style sequence mutation.
5. For every resulting trial, require actual `FAULT_MATCHED` and `FAULT_APPLIED` receipts for **all** planned IDs in order, a named exact target after the final fault, and the final-release offline causal audit. An unmatched sequence contributes zero effective trials and cannot seed a deeper sequence. A target exception is a candidate only after exact throw-site evidence and independent replay/source review.

Run this as a new, pinned release with its own output, lock, budget, and terminal SHA-bound audit when a node2 lane and host capacity are available. Do not modify the 5820 core or either live SOLR-06 configuration. Select one canonical audited campaign for the checklist; any cross-campaign analysis must explicitly validate both raw phases and never sum their trial counts silently.
