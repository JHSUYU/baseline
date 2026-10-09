# SOLR-34 actor-V2 case

The unchanged Solr 8.11.4 `TestCoordinatorRole.testSimple` JUnit passed in all
128 selected fault runs. There were
128 effective ordered same-client native ZooKeeper
fault trials (128/max10 extension), 128 strict postfault
guard reaches, and zero exact SOLR-34 target exceptions. No new bug is claimed.

The adapter binds the target to the live coordinator
`solrCall.cores.getZkController().getZkClient()` and records the actual
`SolrZkClient` receiver at every native I/O hook. Eight exact preguard
selectors were stable in both node0 and node2 healthy seeds. A wrong-client
fixture rejects another receiver. Node0 trials 1–15 and node2 trials 16 onward
are labeled in the [trial ledger](campaign/trial-ledger-v2.json); the original
node0 trial-16 raw run was archived but never counted because its runner
receipt was interrupted. HBASE-32 s101 overlapped the node0 phase, as recorded
in the [node0 audit](node0-phase-audit.json).

The case used 5081.499 seconds of selected fault-trial
runtime. Original release-JAR JaCoCo comparison adds
25 production methods and
86 branch outcomes over healthy
seeds; actor-relative I/O families add 0.
The final 20 effective trials added
6 production probes or
actor-relative I/O families. At the 80-trial boundary the final 20 had added
6 such probes or families;
that observation determined whether the 128-trial extension ran. The
[source review](SOURCE_REVIEW.md) distinguishes
the newly constructed exception at line 143 from the earlier exception rethrow
at line 140. Raw traces, JUnit logs, JaCoCo data, plans, and receipts are in
the [archive](raw-evidence-v2.tar.zst) (SHA-256 `d332ac8c05fb4bf856aca7d441b978278f4627f9534c8937a1ce6830e294cd1b`).

The result covers this original embedded-cluster test and the instrumented
SolrZkClient retry-internal I/O sites.
