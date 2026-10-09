# ZOOKEEPER-03: independent original MultiOp quorum JUnit extension

Target: unchanged ZooKeeper 3.8.7 `SessionTrackerImpl.setOwner` guard at
`zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java:329`
and its `SessionExpiredException` at line 330. The original source revision is
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

## Why this extension exists

The earlier original `QuorumTest#testSessionMoved` pre-I/O stage stopped at its
480-attempt cap with 37/80 effective trials and 63 unselected plans left in
its archived checkpoint. Those 63 plans have depths 2–5 (`40/8/8/7`), all
begin with the already explored client socket-read family, and use only five
already seen Java I/O call sites. Among the 105 tested children of the same
eight parent plans, 12 retained the selected target after the final fault.
The 63 remaining plans could mathematically add 16 effective trials, but the
measured yield and lack of a new I/O family do not support assuming they will.
The separate post-response stage exhausted its queue after 186 attempts and
27/80 effective trials. Neither old stage is relabelled or replayed here.

The earlier stage denominators remain in the parent `result.json`: 666 selected
fault trials, 64 post-fault target reaches, and 2785.142 measured seconds.
Their original raw archives and audits were committed in
`62e1a115c4c225c90605e1c4c540983591d0f903` under
`crashfuzz/zk-actor-v2/cases/ZOOKEEPER-03/`.
If that legacy directory is removed from the current tree, restore a copy in
an isolated directory with
`mkdir -p /tmp/zk03-legacy-restore` followed by
`git archive 62e1a115c4c225c90605e1c4c540983591d0f903 crashfuzz/zk-actor-v2/cases/ZOOKEEPER-03 | tar -x -C /tmp/zk03-legacy-restore`.
The legacy archive hashes and denominators are also retained in
`evidence/old-campaign-audit.json`; the new MultiOp trials never backfill
the old 666-trial denominator.

Source review found the enabled original five-peer
`QuorumTest#testSessionMovedWithMultiOp` (lines 256–285). It opens a session
on peer 1 and moves the same raw session to peer 2. The selected leader
`SessionTrackerImpl.setOwner` check executes for both connections. A disabled
`QuorumTest#testSessionMove` is not an executable original workload; the
`SessionTest#testSessionMove` test starts one standalone server rather than a
quorum. `SessionUpgradeTest#testUpgradeWithEphemeralOnFollower`,
`ObserverMasterTest#testRevalidation`, and
`FollowerResyncConcurrencyTest#testFollowerWatcherResync` have one explicit
session reconnect/revalidation and remain possible future original tests, but
the MultiOp test provides a directly measured same-session window between
two selected checks.

## Healthy and fault evidence

Two unchanged JUnit runs each exited 0 with five bound peers, one leader
(peer 5), one raw session registered to both handles, and two selected
`setOwner` guards with `present-open` state. The two checks enclose a completed
leader REVALIDATE response flush, socket reads/writes, and completed server
responses. The first and second healthy runs have distinct raw session IDs;
within each run the two handles and both selected guards share that ID.

The separate bounded pilot selected ten stable, observed I/O points between
the selected guards. All ten faults matched and applied at the exact actor,
resource, ordinal and moved-session identity. Four trials retained a later
selected guard and same raw-session owner after the final fault. Six lost the
target and are **not** effective. One effective trial added three distinct
source-line coverage records; no selected target throw occurred. The complete
pilot took 64.523 seconds including the two healthy runs. Independent raw
audit: `python3 audit_multiop.py`; its output is
`evidence/pilot-independent-audit.json`, with raw files in
`evidence/raw-pilot.tar.gz`.

The agent instruments original compiled classes at runtime. It registers the
five actual `QuorumBase` peers and the two concrete client objects, then joins
their raw session ID with the leader's owner and selected `setOwner` guard.
`FAULT_MATCHED` and `FAULT_APPLIED` are emitted only for the exact observed
I/O selector. Target retention requires an owner receipt and matching leader,
session and target check after the final applied fault. Code coverage records
original production source lines reached during the run. The JUnit test and
production source remain unchanged; Docker and GraphChecker are not used.

## Formal budget and terminal result

The formal stage ran in node1 `tmux:zk03_multiop_campaign`, with
checkpoint at `/users/ZhenyuLi/zk03-multiop-runs/campaign/checkpoint.json`.
The four strictly effective pilot trials count toward this **new** stage's
80-effective target; the ten pilot attempts count toward its 480-attempt cap.
Fault sequences may grow to eight faults. If any of the final eight effective
trials at 80 adds coverage or an I/O family, the stage conditionally extends to
128 effective and ten faults. `campaign_multiop.py` persists one raw JUnit run,
coverage file, event log, receipt and elapsed time per selected plan, with a
checkpoint and append-only ledger. It never counts a fault that loses the
selected target.

Each JUnit starts under the shared node1 `jvm-start.lock` only when Java
process count is below five and free disk is at least 10 GiB. The reserved
ZooKeeper port slot is 14/16 (28719–30064). Across all 42 original JUnit
launches, the smallest recorded free disk was 15.107 GiB and at most four Java
processes were present before startup.

The between-guards mutation queue exhausted after 26 formal trials: 18
effective, with no new source-line coverage and no selected target throw.
Counting the four strict effective pilot trials, this new stage reached
**22/80 effective in 36 selected fault trials**. The deepest tested sequence
contained four faults. All 15 stable same-session one-fault I/O selectors
between the two healthy selected guards were tested, and the queue of
post-final-fault mutations is empty.

We also audited the four stable same-session client read selectors before the
first selected guard. A separate four-run bounded pilot injected all four
exactly. Each original JUnit failed at `QuorumTest.java:262` with
`ConnectionLossException` during the first `multi` call; none reached the
selected target after the fault. This exhausts the stable target-related I/O
classes observed in the two healthy runs of this original MultiOp test under
the current fault model. It does **not** meet the 80-effective budget and does
not prove the selected check is bug-free across other workloads or faults.

The independent terminal raw audit is `python3 audit_campaign.py`, producing
`evidence/campaign-independent-audit.json` from
`evidence/raw-campaign.tar.gz` and the earlier pilot archive. The 42 original
JUnit launches took 234.012 measured JVM seconds in total: two healthy runs,
ten pilot faults, 26 formal faults and four pre-first faults. The pilot's three
new coverage lines are `NIOServerCnxn#doIO:390–392`; formal trials added none.
No selected `SessionExpiredException` was observed, so the bug mark is none.

Any future selected `SessionExpiredException` is marked only as a source-review
candidate. It requires independent original JUnit replay and examination of
the concrete session/owner path before a bug verdict.
