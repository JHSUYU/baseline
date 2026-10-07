# SOLR-31 actor-bound V2

This isolated case runs the unchanged Solr 8.11.4
`ForceLeaderTest.testReplicasInLowerTerms` embedded-cluster JUnit. The exact
target is the active-leader rejection in
`CollectionsHandler.forceLeaderElection` at line 1477. The old 80-trial
campaign remains in `../campaign` and is non-credit `legacy_coarse_actor`
evidence.

At method entry, the V2 agent obtains the actual
`handler.getCoreContainer().getZkController().getZkClient()` receiver and
`ZkController.getNodeName()`. It records both on the target entry, leader,
guard, and exception events. Each `SolrZkClient` retry-I/O event records its
actual receiver identity, physical node, and stable role
`forceleader-request-jetty`. A fault can apply only while the target method
is on the current stack, on that same client object, and on one of the
selected collection paths: the collection root, its `state.json`, its
`terms` directory, or `terms/shard1`. The exact collection and shard come
from the current target request. The selected I/O site, role, path, and
ordinal must match the fault plan. A wrong client or path is rejected.

`node2-preflight-v2.json` pins the original source revision, test source and class,
runner source and class, release Solr core JAR, V2 agent, `-ea`, and absence of
GraphChecker from the classpath. `node2-offline-smoke-v2.json` checks wrong client,
collection, and shard rejection plus bytecode hooks under both `-ea` and
`-da`. `calibration-v2.json` audits two healthy original JUnit seeds. Their
raw traces and JaCoCo files are in `healthy-01` and `healthy-02`.

Run `python3 campaign_v2.py --max-trials 80 --max-faults 8` on node2 after
calibration. It writes only under `actor-v2/campaign`, checkpoints each
selected sequence and attempt atomically, and counts an effective trial only
when every planned fault applies to the bound actor and the same target guard
executes after the last fault. The selected-sequence cap defaults to 320.
At the 80-effective checkpoint, extend to 128/max10 only if one of the last
eight effective trials adds production coverage or a stable actor-bound I/O
family. A target exception is only a candidate until clean-fixture replay
and source/JUnit review establish its meaning.

The node2 agent JAR in this directory is the binary used for the healthy
seeds. Rebuilding a JAR changes its hash and requires a new calibration
before resuming a checkpoint.

## Completed actor-bound campaign

The 80-effective checkpoint had one new original-release production probe in
its final eight effective trials, so the same checkpoint continued to the
128-effective/max10 cap. The terminal node2 run selected 129 sequences and
made 129 original JUnit attempts. All 129 selected sequences applied their
entire fault plans on the bound client. One sequence (trial 113) lost the
target before the guard and was excluded from the effective count. The other
128 reached the exact guard after the last fault. The original JUnit passed
125 attempts; effective trials 110, 118, and 127 failed on later HTTP response
timeouts. None threw the exact active-leader exception. The largest trial
took 99.653 seconds, below twice the mean 59.243-second healthy runtime.

An independent event-trace recount is in `campaign/audit-v2.json`. Original
release-JAR JaCoCo union over the two healthy seeds and 128 valid trials adds
91 production methods and 205 branch outcomes; the two runtime-woven classes
are excluded. The final eight effective trials added no new probe or stable
actor-bound I/O family. `campaign/production-coverage-audit-v2.json` contains
the release-JAR counts. `campaign/raw-trials-v2.tar.zst` contains all 1,032
trial evidence files, excluding only regenerable embedded-cluster scratch;
its SHA-256 is
`4b912e6ab70a1d334858fb8f3ce847cc9f0b2670f3e562d4a24afa7205d8e7f1`.
The manifest and receipt verify every archive member. The full raw trial
directories remain on node2.
