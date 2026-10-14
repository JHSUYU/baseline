# SOLR-07 multi-fault scheduling audit

The running SOLR-07 campaign is pinned to its original version-2 scheduler.
This audit did not edit its configuration, checkpoint, fault receipts, or
process. The source-backed case root is
`/proj/silentfailure-PG0/mallory/solr07-native-prep-v1`; its campaign config
SHA-256 is `90f133d841bc4ba81a17a72f27a37f5931716a5687d3e9721bfebb8e1575c86e`.

The first six injected trials produced one checked strict trial and five
unmatched multi-fault trials. In each unmatched trial, the first fault was
actually applied to `node2` at `LeaderElector.checkIfIamLeader#u11`; the
second fault was never applied. For example:

| Trial | First applied sidecar row | Planned second door | Observed second door |
| --- | ---: | --- | --- |
| r0002 | 724 | `node3`, `joinElection#u81`, ordinal 1 | row 487, before first fault |
| r0003 | 727 | `node3`, `checkIfIamLeader#u97`, ordinal 1 | absent |
| r0004 | 489 | `node3`, `getLeaderProps#u13`, ordinal 1 | absent |
| r0005 | 708 | `node3`, `ZkShardTerms.refreshTerms#u5`, ordinal 1 | rows 478, 482, 664, 702; all before first fault |
| r0006 | 486 | `node3`, `ZkCmdExecutor.ensureExists#u6`, ordinal 1 | absent on `node3` |

The exact actor occurrence also varied across JUnit runs, as expected for
concurrent cluster execution. The injector intentionally matches site, actor,
epoch, and ordinal rather than a prior JVM's occurrence ID. The observed
unmatched results are therefore genuine sequence-order misses, not a failure
to inject the first fault or a false target exception.

At the frozen read-only checkpoint after these trials, the queue contained
1,137 one-fault and 141 two-fault plans. Applying the old version-2 picker
to copies of that queue at completed counts 1–8 selected depths
`2,2,2,2,2,1,2,2`; applying the proposed version-4 picker selected
`1,2,1,1,1,2,1,1`. The new rule reserves one in four positions for deeper
plans and preserves an outside-closure position every eight trials. Version-2
and version-3 checkpoint selection remain byte-for-byte unchanged in code.

Evidence is in each trial's `iteration-native/fault-plan.json`,
`iteration-native/fault-events.jsonl`, and `result.json` under
`/proj/silentfailure-PG0/mallory/solr07-native-prep-v1/campaign-prep/campaign/trials`.
