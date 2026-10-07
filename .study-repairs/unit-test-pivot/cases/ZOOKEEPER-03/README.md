# ZOOKEEPER-03 actor-aware original-JUnit result

The unchanged `QuorumTest#testSessionMoved` runs an embedded five-peer cluster and exercises `SessionTrackerImpl.setOwner`. Fault selectors bind the actual moved client session, peer and leader owner. Only the same selected guard after the final fault counts.

The pre-I/O stage ended at 480 selected JUnits with 37 effective. The separate post-response stage ended at 186 selected JUnits with 27 effective, versus its 80/max8 budget. Together the stages consumed 2785.142 summed original-JUnit JVM seconds. The table reports 666 fault trials, 663 exact plans and 64 postfault target reaches across both stages. Their feedback queues and budget denominators remain separate.

Effective faulted runs added 3 instrumented production source-line IDs. No selected SessionExpiredException was observed. Result: **inconclusive_budget_unmet**, bug mark `none`.

The [pre-I/O audit](../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/terminal-audit.json), [post-response audit](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/terminal-audit.json), [per-trial times](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/trial-times.csv), and raw archives in the same evidence directories preserve all original JUnit receipts, actor joins, coverage, and applied plans. The older global-ordinal [result](result.pre-actor-v2.json) remains coarse history.
