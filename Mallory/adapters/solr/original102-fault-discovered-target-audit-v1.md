# Original-102 Solr checks whose exact guard is absent in the healthy seed

This is an offline source and archived-trace review. It does not count any Mallory
fault trial as complete. The three existing JUnit tests below start a Solr
cluster and pass without injected faults; their selected inner guards are absent
from the current Mallory healthy traces. That absence is a campaign bootstrap
limitation, not evidence that the tests are unsuitable.

| Case | Existing cluster JUnit | Healthy trace | Source route to selected check |
| --- | --- | --- | --- |
| SOLR-15 | `SplitShardTest#doTest` | JUnit 1/0/0; selected `@536:branch:40` absent | `SplitShardCmd.split` reads the leader live-node znode at line 523. If the later leader stat is null or has a changed session owner, the outer line-524 condition enters recovery-failed handling. The selected line-536 null test then decides whether to throw the “leader is not live” exception. |
| SOLR-16 | `SplitShardTest#doTest` | JUnit 1/0/0; selected changed-owner guard absent | The same line-523 read and line-524 outer condition lead to the line-539 changed-owner test when the stat is non-null with a different ephemeral owner. A plain I/O exception does not itself create that value transition. |
| SOLR-34 | `TestCoordinatorRole#testSimple` | JUnit 1/0/0; selected `@139:branch:6` absent | `CoordinatorHttpSolrCall.getCore` performs a coordinator request that may create a synthetic collection. Only when the subsequent cluster-state lookup remains null does the selected line-139 `createException` decision run. The line-140 rethrow and line-143 constructed exception are distinct outcomes. |

Evidence: `data/mallory/evidence_archives/calibration/SOLR-{15,16,34}.tar.gz`
contains each healthy JUnit receipt and runtime event trace. The Solr 8.11.4
source is pinned under `.graphchecker-sources/solr-8.11.4`; relevant methods
are `SplitShardCmd.split` lines 519–544,
`CoordinatorHttpSolrCall.getCore` lines 111–148, and the JUnit methods above.
The current Mallory calibration results are `healthy_seed_invalid` with zero
fault trials because the exact selected guard is missing, even though each
JUnit passes. The healthy traces expose surrounding branch events (`SplitShardCmd`
line 524 and `CoordinatorHttpSolrCall` lines 115, 117, 138), but the old adapter
does not emit `DOOR_OBSERVED` for these cases. Fresh role-aware I/O tracing is
required before any fault-discovery campaign.

The previous CrashFuzz dataset is useful only as prior evidence: its original
102 table records 163 fault trials for SOLR-15 and 128 for SOLR-34, with
post-fault selected-guard observations. It classified the SOLR-15 throw under
its chaos test as the intended abort after leader loss, and reported no new
SOLR-34 exception. Those records are **not** Mallory runs and do not establish
a new bug. SOLR-16's changed-owner outcome remains unproven by that dataset.

Next admission step: a generic opt-in bootstrap must accept a passing cluster
JUnit with no exact healthy target, enumerate only observed named I/O doors,
and report the graph closure as unavailable until a faulted run reaches the
selected target. Its runtime identity and exact throw oracle must remain
unchanged. After that, run fresh healthy traces with the current adapter and
case-specific bounded campaigns; record graph quality and target retention as
outcomes. Do not call the target method directly from a test fixture.
