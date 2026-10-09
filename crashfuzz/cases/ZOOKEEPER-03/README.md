# ZOOKEEPER-03 actor-aware original-JUnit result

Current terminal status: **`quality_complete`**, bug mark `none`. The sections
below preserve each stage's separate denominator and its result at that time.

The unchanged `QuorumTest#testSessionMoved` runs an embedded five-peer cluster and exercises `SessionTrackerImpl.setOwner`. Fault selectors bind the actual moved client session, peer and leader owner. Only the same selected guard after the final fault counts.

The pre-I/O stage ended at 480 selected JUnits with 37 effective. The separate post-response stage ended at 186 selected JUnits with 27 effective, versus its 80/max8 budget. Together the stages consumed 2785.142 summed original-JUnit JVM seconds. The table reports 666 fault trials, 663 exact plans and 64 postfault target reaches across both stages. Their feedback queues and budget denominators remain separate.

Effective faulted runs added 3 instrumented production source-line IDs. No selected SessionExpiredException was observed. At this stage the result was **inconclusive_budget_unmet**, bug mark `none`.

The [pre-I/O audit](../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/terminal-audit.json), [post-response audit](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/terminal-audit.json), [per-trial times](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/trial-times.csv), and raw archives in the same evidence directories preserve all original JUnit receipts, actor joins, coverage, and applied plans. The older global-ordinal [result](result.pre-actor-v2.json) remains coarse history.

## Separate quorum-response pilot

An isolated extension recorded the leader's `REVALIDATE` reply after both serialization and successful `BufferedOutputStream.flush`. Two fresh unchanged JUnits each passed with eight actor-bound response chains, ten selected leader `setOwner` guards, and seven response selectors preceding a later same-session guard. Its independent pilot tried all seven selectors under a ten-trial cap: all seven IOException faults precisely applied, but each original test failed at `QuorumTest.java:210` `setData` with `ConnectionLossException` before another selected guard. It added zero effective trials and zero selected target throws. The earlier 666 runs and their 37/27 effective denominators were unchanged. Full source, build receipt, checkpoint, independent raw audit, and archive are in [the extension](../../zk-actor-v2/cases/ZOOKEEPER-03/quorum-response/README.md); at this point the check remained **inconclusive_budget_unmet**.

## Separate original MultiOp quorum JUnit

The unchanged five-peer `QuorumTest#testSessionMovedWithMultiOp` passed twice without faults. Both healthy runs reached the selected leader `setOwner` guard twice for the same raw session. The independent actor-bound IOException campaign tested every one of the 15 stable I/O selectors observed between those guards. It ended when its ordered mutation queue was empty: 36 selected between-guard faults yielded 22 post-final-fault same-session target reaches, below its 80-effective/max8 budget. Four additional exact pre-first-guard socket-read faults each failed the original JUnit at its first `multi` call before the selected guard. The 42 original JUnit launches consumed 234.012 measured JVM seconds; effective trials added three distinct instrumented source lines and no selected target exception occurred.

The [MultiOp method and raw audit](multiop-extension/README.md) keep this new workload seed, its 36-trial denominator, and its four pre-first target-lost trials separate from the earlier 666 trials. At this stage, there were 713 selected fault trials and 3055.906 summed JVM seconds. The result was **inconclusive_budget_unmet**, bug mark `none`; queue exhaustion under this observed-I/O fault model was not a bug-free verdict.

The legacy raw archives and audits linked above are restorable from commit `62e1a115c4c225c90605e1c4c540983591d0f903` at `crashfuzz/zk-actor-v2/cases/ZOOKEEPER-03/` if that historical directory is absent from the current tree. The MultiOp README gives the read-only `git archive` command and records the older stage denominators and archive hashes.

## Offline frontier audit

The [archive-backed audit](frontier_audit.py) independently checks both healthy traces, the atomically saved checkpoints and the selected leader/raw-session owner receipts in all three stages. The two ten-handoff seeds have 159 common actor-bound I/O selectors before their last target guard in the pre-I/O stage; all 159 were tried as single faults. The post-response seeds have 43 common eligible complete-I/O selectors, all tried as single faults, and its queue is empty. The MultiOp seeds have 15 common between-guard selectors, all tried as single faults; its four common pre-first selectors also all received exact faults and lost the target. Its ordered queue is empty.

At the time of this audit, the pre-I/O checkpoint contained **63 untried ordered plans** after its 480-attempt cap, across eight previously tested parents and depths 2–5. Their 32 distinct last I/O selectors were all tried in other sequences; the untested items were fault-history combinations. The 105 already tested children of those same parents yielded 12 effective runs. These observations did not prove the 63 would be ineffective, and the pre-I/O sequence queue was **not** empty in this historical snapshot.

The original healthy traces show 30 unbound epoch-file I/O events per seed before peer registration and no file I/O between peer registration and the last target. Later unbound socket operations lack the server connection or raw-session identity required by `ActorRegistry.serverIo`; their event receipts cannot safely select the moved session. A new socket-tuple binding would need fresh healthy calibration and was outside this archived fault campaign. The [machine-readable audit](evidence/frontier-audit.json) therefore reported no **new observed actor-bound selector** while retaining the unfinished sequence budget. No JUnit was launched for this offline audit.

## Completed pre-I/O supplement and original SessionUpgrade seed

The [fixed 63-plan supplement](preio-supplement/README.md) then ran every previously untried pre-I/O ordered plan on the original embedded five-peer `QuorumTest#testSessionMoved`. All 63 plans were selected once, 62 applied exactly, and eight retained the same raw-session/leader-owner target after the final fault. Its independently audited original-JUnit time was 2,571.393 seconds. It produced no selected `SessionExpiredException`. The old 480-trial denominator remains separate.

A different unchanged five-peer original test,
`SessionUpgradeTest#testUpgradeWithEphemeralOnFollower`, reached the **same**
`SessionTrackerImpl.setOwner` global-session guard. Its two no-fault calibrations
passed with one selected global target guard and two expected local-tracker
fallback guards each. The [actor-bound I/O campaign](session-upgrade-seed/README.md)
tested 10 single-fault, 13 two-fault, and 131 deeper sequences. Respectively,
3, 7, and 70 retained the same raw session, leader, global tracker, and owner
target after the final fault, meeting this seed's **80/80 effective** budget.
Of its 154 selected trials, 152 applied every fault in order. The three
faulted stages consumed 1,623.633 original-JUnit JVM seconds, discovered 18
new target-window I/O families across their own feedback stages, and produced
no selected target `SessionExpiredException`. The 131-run depth stage stopped
on its effective budget before its 256-trial cap, with raw independent audit
and archive hashes in the linked README.

Across all independently counted stages, **930** fault trials were selected,
**922** applied every ordered fault, and **174** reached their selected target
after the final fault. Summed original-JUnit JVM time was **7,250.932
seconds**; shared startup-lock waits and archival work are excluded. This
check is `quality_complete` under the defined 80-effective new-seed budget,
with bug mark `none`. The fault model covers observed actor-bound socket I/O
and the selected original cluster tests; it does not enumerate unbound startup
I/O or every distributed schedule.
