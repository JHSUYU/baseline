# ZOOKEEPER-03 actor-aware original-JUnit result

The unchanged `QuorumTest#testSessionMoved` runs an embedded five-peer cluster and exercises `SessionTrackerImpl.setOwner`. Fault selectors bind the actual moved client session, peer and leader owner. Only the same selected guard after the final fault counts.

The pre-I/O stage ended at 480 selected JUnits with 37 effective. The separate post-response stage ended at 186 selected JUnits with 27 effective, versus its 80/max8 budget. Together the stages consumed 2785.142 summed original-JUnit JVM seconds. The table reports 666 fault trials, 663 exact plans and 64 postfault target reaches across both stages. Their feedback queues and budget denominators remain separate.

Effective faulted runs added 3 instrumented production source-line IDs. No selected SessionExpiredException was observed. Result: **inconclusive_budget_unmet**, bug mark `none`.

The [pre-I/O audit](../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/terminal-audit.json), [post-response audit](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/terminal-audit.json), [per-trial times](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/trial-times.csv), and raw archives in the same evidence directories preserve all original JUnit receipts, actor joins, coverage, and applied plans. The older global-ordinal [result](result.pre-actor-v2.json) remains coarse history.

## Separate quorum-response pilot

An isolated extension recorded the leader's `REVALIDATE` reply after both serialization and successful `BufferedOutputStream.flush`. Two fresh unchanged JUnits each passed with eight actor-bound response chains, ten selected leader `setOwner` guards, and seven response selectors preceding a later same-session guard. Its independent pilot tried all seven selectors under a ten-trial cap: all seven IOException faults precisely applied, but each original test failed at `QuorumTest.java:210` `setData` with `ConnectionLossException` before another selected guard. It added zero effective trials and zero selected target throws. The earlier 666 runs and their 37/27 effective denominators are unchanged. Full source, build receipt, checkpoint, independent raw audit, and archive are in [the extension](../../zk-actor-v2/cases/ZOOKEEPER-03/quorum-response/README.md); this check remains **inconclusive_budget_unmet**.

## Separate original MultiOp quorum JUnit

The unchanged five-peer `QuorumTest#testSessionMovedWithMultiOp` passed twice without faults. Both healthy runs reached the selected leader `setOwner` guard twice for the same raw session. The independent actor-bound IOException campaign tested every one of the 15 stable I/O selectors observed between those guards. It ended when its ordered mutation queue was empty: 36 selected between-guard faults yielded 22 post-final-fault same-session target reaches, below its 80-effective/max8 budget. Four additional exact pre-first-guard socket-read faults each failed the original JUnit at its first `multi` call before the selected guard. The 42 original JUnit launches consumed 234.012 measured JVM seconds; effective trials added three distinct instrumented source lines and no selected target exception occurred.

The [MultiOp method and raw audit](multiop-extension/README.md) keep this new workload seed, its 36-trial denominator, and its four pre-first target-lost trials separate from the earlier 666 trials. Across every stage there were 713 selected fault trials and 3055.906 summed JVM seconds. The result remains **inconclusive_budget_unmet**, bug mark `none`; queue exhaustion under this observed-I/O fault model is not a bug-free verdict.

The legacy raw archives and audits linked above are restorable from commit `62e1a115c4c225c90605e1c4c540983591d0f903` at `.study-repairs/unit-test-pivot/zk-actor-v2/cases/ZOOKEEPER-03/` if that historical directory is absent from the current tree. The MultiOp README gives the read-only `git archive` command and records the older stage denominators and archive hashes.
