# MC-3 investigation record

Target: `ZKDatabase.addCommittedProposal` throwing `IllegalStateException` at `ZKDatabase.java:341` (tree pinned at eab16599).
Line numbers below are from the pristine commit, read with `git show HEAD:<file>` or from an export of it.

## Step 1: code audit

Call chain and facts:

- `Follower.processPacket` COMMIT queues the commit for asynchronous apply (`fzk.commit`, `Follower.java:201`), then calls `om.proposalCommitted` (`Follower.java:204`). F's ObserverMaster therefore forwards a commit before F has applied it.
- `ObserverMaster.proposalCommitted` calls `cacheCommittedPacket` and then `sendPacket` (`ObserverMaster.java:413`).
- `cacheCommittedPacket` (`ObserverMaster.java:377-398`) adds the packet (`:378`), then polls from the head: up to 5 while over 0.8 * limit (`:381`), then without bound while over the limit (`:390`). Neither loop protects the packet just added, so one packet over 0.8 * limit with at most 4 older entries, or any packet over the limit, leaves the queue empty.
- `LearnerHandler.syncFollower` works from F's applied state. A peer ahead of `maxCommittedLog` gets `TRUNC(maxCommittedLog)` (`LearnerHandler.java:858-864`). A peer within range gets a DIFF up to `maxCommittedLog` (`:870`). `startForwarding` then runs from that position (`:925`).
- `ObserverMaster.startForwarding` (`:293-332`) fills the gap from `committedPkts`. Its "too far behind" check only runs if the queue has a head. An empty queue skips the check and activates the handler (`:330`), even though commits above `lastSeenZxid` were already sent and evicted.
- Observer side: after TRUNC, `lastQueued` is 0 (`Learner.java:639`), so the first INFORM passes `enforceContinuousProposal` (`:543`) and is applied synchronously (`:724`). After UPTODATE, `Observer.processPacket` has no continuity check (`Observer.java:208`).
- `ZooKeeperServer.processTxn` applies to the tree (`:1863`) BEFORE `addCommittedProposal` (`:1888`), so a failed check still leaves the out-of-order txn in memory.
- `ZooKeeperServer.shutdown(false)` calls `fastForwardDataBase` (`:936`), which replays through `addCommittedProposal`. `Observer.shutdown` at `QuorumPeer.java:1600` runs in a `finally`, so an ISE thrown there leaves `QuorumPeer.run`.
- When that thread ends, `quorumPeer.join()` returns and `QuorumPeerMain.main` reaches `requestSystemExit` (`QuorumPeerMain.java:118-119`). This last step is read from code: the test JVM only shows the run thread ending.

Reachability premise: the queue can only empty with a packet over 0.8 * limit. The default limit is 32 MiB (`ObserverMaster.java:86`) and default `jute.maxbuffer` is 1 MiB, so it cannot happen at default settings. Two supported settings open it:

- `zookeeper.observerMaster.sizeLimit` (system property), or `FollowerMXBean.setObserverMasterPacketSizeLimit` (JMX, no validation). Neither is in `zookeeperAdmin.md`.
- `jute.maxbuffer` above about 26.8 MB. `zookeeperAdmin.md:1952-1968` documents this property and says raising it is "not recommended"; it does not call it invalid.

Safeguards recorded:

| Safeguard | Effect |
|---|---|
| `startForwarding` "too far behind" | Disconnects when the head is past the gap, but is skipped when the queue is empty |
| `enforceContinuousProposal` | Catches the gap only when `lastQueued != 0`. Observed firing in the unthrottled Level 0 run (24 times) |
| Target check itself | Fires, but after the tree write, and does not stop later damage |
| Resync | Does not repair: the observer reports the same zxid as F and receives an empty DIFF |

## Step 2: developer knowledge (run only after the reproduction verdict was settled, per Shared Rule 2)

Git history, pinned tree:

- `git log -- ObserverMaster.java`: the eviction loops date from `b2513c11` (ZOOKEEPER-3140, 2018). No later commit changes eviction.
- `git log -S'Committed proposal cached out of order' -- ZKDatabase.java` and `git log -S'enforceContinuousProposal' -- Learner.java`: both introduced by `e5dd60bf` (ZOOKEEPER-4925, 2025).
- `git log -S'pktsSizeLimit' -- ObserverMaster.java`: `b2513c11`.

Comments: the retained queue exists "so that observers can sync up with us when we connect" (`ObserverMaster.java:82-85`). No comment accepts losing a packet that is still needed.

Tests: `grep` for `setObserverMasterPacketSizeLimit`, `observerMaster.sizeLimit` and `PktsSizeLimit` in `src/test` finds nothing but this repro, so eviction has no test coverage.

## Step 3: known status

All queries, in order.

JIRA REST `project=ZOOKEEPER AND ...`:

| JQL clause | Result |
|---|---|
| `text ~ "observerMaster" AND text ~ "sizeLimit"` | ZOOKEEPER-3140 only |
| `text ~ "cacheCommittedPacket"` | ZOOKEEPER-3140 only |
| `text ~ "Committed proposal cached out of order"` | 5088, 5094, 4991, 4925 |
| `text ~ "ObserverMaster" AND text ~ "committedPkts"` | ZOOKEEPER-3140 only |
| `text ~ "ObserverMaster" AND text ~ "TRUNC"` | 2789, 3509 |
| `summary ~ "observer" AND text ~ "retained commit queue"` | ZOOKEEPER-3140 only |
| `text ~ "addCommittedProposal" AND text ~ "out of order"` | 5088, 5094, 4925 |
| `text ~ "DIFF sync got proposal"` | 11 hits, the top 8 listed; none is about eviction |

GitHub search API on apache/zookeeper (states not filtered, so merged and closed are included; `gh` is not installed, so this used curl):

| Query | Result |
|---|---|
| `cacheCommittedPacket is:pr` | 0 |
| `committedPkts is:pr` | 0 |
| `ObserverMaster is:pr created:>=2025-01-01` | #2454 (open), #2382 (open, unrelated) |
| `ObserverMaster INFORM is:pr` | #2454 |
| `ZOOKEEPER-5088` | rate-limited, no result |
| `ZOOKEEPER-5094` | rate-limited, no result |

GitHub commits API, `path=.../ObserverMaster.java`: the newest commit is `629518b5` (2023), so no later change to this file has landed upstream.

Comparison with the near matches:

- **ZOOKEEPER-5088** (open, PR #2454 open): same symptom, different cause. Proposals received during F's own sync never enter `proposedPkts`, so no INFORM is sent. It requires an F restart. In MC-3 F is never restarted, and the INFORM is sent and then evicted from `committedPkts`. Going by its title, #2454 seeds `proposedPkts`; I did not read its diff, and that change would not touch `cacheCommittedPacket`.
- **ZOOKEEPER-5094** (open): covers a follower keeping memory ahead of its log after an interrupted TRUNC. It overlaps MC-3's aftermath on the `ceOrder` route, but does not report the cause of the gap.
- **ZOOKEEPER-4925** (fixed): added the target check; a different cause of a discontinuous committedLog.

Outcome: nothing reports this mechanism (eviction emptying `committedPkts` while the commit is unapplied at F). Novelty is NEW. The search did not change the verdict.

MC-sourced with a real counterexample, so the code-review pre-filter does not apply.

## Persistent lookup

`specula findings lookup --query cacheCommittedPacket --query TargetSafe --query 'Committed proposal cached out of order'` returned no records.

## Reproduction notes

Two false leads, recorded so nobody reuses them:

1. An early "observer cannot restart" result was a `BindException`, not disk state. `MainThread.shutdown` joins for only 500 ms, a run thread ending late nulls `currentThread`, and a dead QuorumPeer leaves its listener bound in the shared JVM. `stopObserver` now handles both, and the restart result is valid.
2. The unthrottled Level 0 abort (writer lost its connection near 51k txns) was not caused by the target: 0 target firings, 24 continuity-check failures, no `OutOfMemoryError` in the log. Why the writer's connection dropped was not determined. The log is kept as `MC-3_level0Stress_unthrottled.*`.
