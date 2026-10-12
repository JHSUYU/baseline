# SOLR-40 automatic target exception, source audit

System: Solr 8.11.4. Workload: the original four-node embedded-cluster
`TimeRoutedAliasUpdateProcessorTest#test`. The test creates the time-routed
`myalias` and then indexes through it. The automatic scheduler started from a
healthy run; no fault sequence was manually pinned in this campaign.

## First automatic hit: r0003

The scheduler selected one fault with `selection_reason=dynamic_closure`:
`KeeperException.ConnectionLossException` at
`ZkStateReader$AliasesManager.process@2312:door:1`, node2, ordinal 1.
The trace records `FAULT_APPLIED` at sequence 5021. On that same node,
`AliasesManager` object `o78` reads its alias reference `o169` at sequences
5128 and 5139, with no intervening write to that object's alias field after
the fault. Other Solr nodes update their alias references at sequences 4992
(node4), 5034 (node3), and 5050 (node1); node2's last alias-field write was
at sequence 646. The exact target `getAliasProps@132:branch:1` takes the exceptional
path at sequence 5141; the `@133:callthrow:7` probe records its
`SolrException` at sequence 5142. The elapsed time from fault to target throw
is about 196.5 ms. The JUnit workload fails with "Routed alias myalias
appears to have been removed during request processing."

The feedback records `all_faults_effective`, `fault_identity_valid`,
`target_identity_complete`, `target_region_present`, `target_check_reached`,
`target_threw`, and `target_exception_candidate` as true. The archived
ZooKeeper transaction log contains `myalias`, `router.name=time`, and the
corresponding alias metadata. The workload source creates this alias before
issuing the document add that hits the target.

## Automatic replay: r0004

The scheduler immediately queued `selection_reason=candidate_replay` with
the same fault ID `f503277436912b036e038` and same node2 ordinal-1 door.
This second run records `FAULT_APPLIED` at sequence 4975, target branch at
5098, and exact target throw at 5099. The JUnit workload again fails with the
same target exception. The campaign checkpoint records
`reproduced_candidates=[{"first_trial":3,"replay_trial":4}]`.

## Second actor instance: r0024

A separate node3 ordinal-1 watcher fault (`faf4a8bbda9e0a074d995`) first
missed its target actor. The bounded `actor_miss_replay` later tested the same
plan in r0024. It records `FAULT_APPLIED` on node3 at sequence 4954, the
exceptional target branch on node3 at 5065, and the exact target throw at
5066; JUnit fails with the target exception. Its event-trace SHA-256 is
`ea1e668e97d503fd2c9b343e022c9daf6956a74af2d438a9532668b9b0ea0703`.
This is a second actor instance of the same SOLR-40 failure path, not a
separate bug. It demonstrates that bounded actor rerouting retries can expose
an outcome the first automatic trial of that plan missed.

Evidence: `data/mallory/solr40_graph_auto_v9_node1/SOLR-40/trials/r0003/`,
`r0004/`, and `r0024/` contain the plan, compressed event trace, feedback,
JUnit receipt, and compressed JUnit log. The generated cluster scratch trees
are retained locally but are not included in the repository. The event-trace SHA-256 hashes are
`c1d4c1e0227759ea76e86dead7f175d6d5da0302d46cce60077344c7a72b104f`
and `4f62cc68faa433e2d5631986a9af0c1befdc07fb1ee37f2c06d9bceaa474a934`.

## Interpretation and limit

`AliasesManager.process` catches the read's `ConnectionLossException` and
only logs it; `getAliasProps` checks the local alias properties and throws
when they are empty. This exact source path is described in
`targeted-replay-v3/UPSTREAM-REVIEW.md`. The result is a reproducible,
automatically discovered fault-induced target exception. The injection models
one failed ZooKeeper read, not a full disconnect and recovery. It is not yet
established as a previously unreported upstream bug.

The first hit's selection reason is `dynamic_closure`. The new bounded
`target_branch_replays` option was enabled in this campaign, but r0003 was
selected as a fresh closure candidate, so this hit cannot be attributed to
that retry option. The graph is used to select the fault; the source and trace
show the later local-state observation. We do not claim that every graph edge
is a fully proven read-from relation.
