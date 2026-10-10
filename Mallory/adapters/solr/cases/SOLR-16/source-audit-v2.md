# SOLR-16 cluster workload and target audit

Source revision: Solr 8.11.4 `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.

The selected check is `SplitShardCmd.split` at line 539, with the selected
`SolrException` throw at line 543. The command first reads the parent leader's
`/live_nodes/<node>` znode at line 164 and saves its `ephemeralOwner`. After
preparing the sub-shard replicas, it reads the same znode again at line 523.
The selected throw requires a non-null second `Stat` with a different
`ephemeralOwner`. If the znode is absent, line 536 takes the distinct
leader-not-live throw at line 538. Thus an injected `ConnectionLossException`
alone is not a target hit; the test must observe a leader session change
between the two successful reads and the exact line-543 throw.

`SplitShardTest#doTest` at lines 77–92 starts a cluster and makes a normal
successful split. The archived healthy run passed one JUnit but reached neither
the selected check nor an eligible observed door. It remains a valid negative
calibration, not a completed SOLR-16 campaign.

The unchanged `ShardSplitTest#testSplitWithChaosMonkey` is the better cluster
workload. At lines 416–520 it initiates a split, watches for two sub-shard
replicas, stops the parent shard leader, restarts it, and then checks the
documents and shard state. Its own source explicitly allows the split request
to fail during this planned disruption. A line-543 abort during that stop or
restart is therefore an expected protective behavior unless the source and
postconditions show otherwise.

The archived SOLR-15 healthy trace of this same JUnit provides a control for
instrumentation placement: in one `SplitShardCmd.split` occurrence on actor
`control`, the first caller door was sequence 1378 and the native `exists`
attempt was 1379; the second caller door was sequence 1883 and its native
`exists` attempt was 1884. Both caller doors used the same actor, epoch,
occurrence, thread, context, and region. The old agent did not record the
native resource path, so these events alone cannot establish that the attempts
read the same parent leader znode. The archive SHA-256 is
`eeaefd4715ca2d95b395e9329ad24104d3c58e0aabbdfe62b5bafb4fdf02fd11`.

The isolated `chaos-healthy-node2-v1` package already pins the resource-aware
agent `b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4`, the exact
caller and native sites, and this alternate JUnit. Its healthy gate requires
both native attempts to report the same `/live_nodes/<node>` path in one split
occurrence. Static preflight and all five offline gate tests pass. Its
`admission-request.json` remains `go=false`; no SOLR-16 chaos JUnit or fault
trial has been run under this package. A fault campaign still requires a
path-bound replay selector and a fresh healthy witness. The typed native
`ConnectionLossException` is a plausible timing perturbation because
`SolrZkClient.exists(..., true)` retries that native operation, but it does not
by itself cause the leader's session owner to change or prove target retention.

Source SHA-256: `SplitShardCmd.java`
`995355f882947b528cedf9b7b38032f334afec74b5226d217f3f7828f2fb34f3`;
`SplitShardTest.java`
`decc7968002ca73c787318012f3356a72b681f85c3e2873d5f2326465320daad`;
`ShardSplitTest.java`
`877be1fdba4d626214d647a8ca6b25957b0a87cc381821a125fff71dfe0dc352`.
