# SOLR-22 onInit window follow-up

The previous independent 80-trial `TestPullReplica#testAddDocs` campaign
observed the exact `IndexDeletionPolicyWrapper.getAndSaveCommitPoint` check,
but no same-writer Directory I/O in the `onCommit` interval between
`updateLatestCommit` and `updateKnownCommitPoints`. This follow-up adds only
case-local ASM observation of the analogous original `onInit` interval. It
does not inject a fault and does not count toward the 80-trial budget.
The [95-line agent overlay](oninit-agent.patch) applies to the existing
independent SOLR-22 recorder at build time; the original agent and test source
remain unchanged.

The exact, unchanged original embedded-cluster JUnit methods were
`TestPullReplica#testKillPullReplica` and `#testAddDocs`, both at Solr 8.11.4
revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`. Both passed with
JUnit `ran=1, ignored=0, failures=0`. The runtime classpath excluded
GraphChecker. The isolated agent records direct Lucene Directory calls,
policy object ID, logical core source and writer thread; its `onInit` window
events bracket the original calls immediately after `updateLatestCommit`
and immediately before `updateKnownCommitPoints`.

| Original test | Target checks | Exact throws | Directory I/O overall | Complete onInit windows | Same-writer Directory I/O in onInit window | Same-policy target checks in window |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `testKillPullReplica` | 72 | 0 | 1,906 | 9 | 0 | 0 |
| `testAddDocs` | 170 | 0 | 5,931 | 25 | 0 | 0 |

The raw traces and per-run JUnit logs remain in the corresponding isolated
node2 directories. The compact [kill-replica result](testKillPullReplica/run.json)
and [add-documents result](testAddDocs/run.json) record source and agent
digests. Three of the nine `testKillPullReplica` windows and six of the 25
`testAddDocs` windows have an unresolved policy-to-core source at early
initialization; the zero same-writer Directory I/O count does not require
that source mapping, while the target-read join uses the policy object ID.

Source review confirms that `onInit` has the same latest/delegate/known
sequence as `onCommit`. The default delegate `SolrDeletionPolicy.onInit`
calls `updateCommits`, whose normal path reads commit metadata and marks
deletions; its optional debug `getFileNames()` lookup catches IOException.
These two healthy JUnits do not supply a directly injectable Directory I/O
inside the proposed state interval. No fault sequence was generated for
that interval. This is an observed coverage gap, not evidence that the
coordination check is safe under every workload or custom deletion policy.
