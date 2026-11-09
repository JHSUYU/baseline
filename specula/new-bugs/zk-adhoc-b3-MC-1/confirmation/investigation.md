# MC-1 investigation record

Pinned tree: eab16599. Target: FinalRequestProcessor.java:674, handleGetDataRequest, NoNodeException, guard `n == null`.
This record was rebuilt in the resumed turn. An earlier attempt had left logs and an issue.json, but its repro script no longer existed, so all results below come from runs made in this turn.

## Code audit
- Scan: ContainerManager.getCandidates (ContainerManager.java:185-224) reads the applied DataTree and returns paths only.
- Post: checkContainers (ContainerManager.java:142-160) builds DeleteContainerRequest(path), posts it through postDeleteRequest (:164) with cnxn=null, and paces at 60000/maxPerMinute ms per candidate (default 6 ms). A scan's result ages by candidates x 6 ms.
- Entry: requestProcessor is firstProcessor in standalone (ZooKeeperServerMain.java:170) and prepRequestProcessor on a leader (LeaderZooKeeperServer.java:80). The manager never passes RequestThrottler.
- Admission: PrepRequestProcessor.java:326-351 rejects only a missing node, childCount > 0, or EphemeralType NORMAL. EphemeralType.get(0) is VOID (EphemeralType.java:188), so PERSISTENT passes. Neither cversion, node type nor node identity (czxid) is re-checked.
- Apply: DataTree.java:926-931 treats deleteContainer exactly like delete.
- Consumer: getData runs handleGetDataRequest; n == null throws at FinalRequestProcessor.java:674, and the client gets NONODE.
- Safeguards recorded: the childCount and NORMAL checks (each shown to fire by a control below, and neither applies to an empty PERSISTENT or CONTAINER replacement). No later mechanism restores the node: the delete is a logged txn.

## Trigger
Container P used and emptied -> manager scans (P candidate) -> client delete(P), create(P, PERSISTENT) -> manager's stale deleteContainer(P) enters PRP -> client getData(P) -> NoNode.
Counterexample steps: 21 MgrScan; 18-23 c4; 24-28 c5; 30 MgrPostEarly; 32 PrepdeleteContainer; 34 FinalApply; 35 TargetCheck(FIRED).
One ordering difference at Level 1: the scan happens before c4 is sent, while in the counterexample it falls between c4's Prep and its apply. Both scans read tree[P]=CONT(cv1,n0), so the scan's result is the same.

## Developer evidence (verbatim; recorded, not used to classify)
- ContainerManager.java:39-40 (javadoc): "The result of the delete is unimportant. If the proposal fails or the container node is not empty there's no harm." This covers failed and non-empty deletes. It does not mention a replaced node.
- getCandidates comment: "cversion > 0: keep newly created containers from being deleted before any children have been added." PRP does not re-check this, so level1-container defeats that stated intent.
- CreateContainerTest.testFalseEmpty asserts a stale candidate WITH a child survives: stale posts are anticipated, and the PRP re-check is relied on. No test covers a replaced node.
- ZOOKEEPER-2648 comment (race reasoning at scan time only): "The comments indicate this was done intentionally, to avoid a race condition whereby the Container was created right before a cleaning period".

## Reproduction (see repro/; decisive runs are on a pristine git-archive export of eab16599)
Throw frames come from JFR jdk.JavaExceptionThrow; no src/main edits.

| Scenario (repro/MC-1.pristine.log) | Result | Frames at :674 |
|---|---|---|
| workload (unmodified TestAdhocWorkloadB3) | passes, as target.yaml says | 0 |
| level0-standalone | 98/1000 lost, 1 immediate c6 | 197 = 1+98+98 |
| level0-control (replaced before the scan) | 0/200 lost | 0 |
| level0-quorum, run 1 | 45/1000 lost, 1 immediate c6 | 91 = 1+45+45 |
| level0-quorum, run 2 | 44/1000 lost, 1 immediate c6 | 89 = 1+44+44 |
| level0-quorum, run 3 | 114/1000 lost | 228 = 114+114 |
| level1-persistent | c6 NoNode; still gone after restart | 2 |
| level1-container (fresh CONTAINER replacement) | c6 NoNode | 1 |
| level1-control-post-before-create | c6 OK | 0 |
| level1-control-child | c6 OK; child intact | 0 |
| level1-control-ephemeral | c6 OK | 0 |

Txn log, every level 0 run: all lost nodes have a deleteContainer txn (session 0x0) with zxid above the client's create czxid; none has a later client delete.
Other runs of the same tests before the setup was batched (repro/MC-1.pristine-earlier-setup.log, and the passing scenarios in repro/MC-1.pristine-quorum-setup-crossed-scan.log): standalone lost 100, 90, 98; quorum lost 87 (1 immediate c6). Each frame count reconciled.
Worktree (trace instrumentation present but disabled, SpeculaTrace.ENABLED=false): level1-persistent 2 frames; level0-standalone 931/1000 lost, 1862 frames.

### A failed run, kept as evidence
repro/MC-1.pristine-quorum-setup-crossed-scan.log: level0-quorum FAILED with 0/1000 lost. Its setup took 71000 ms, past the manager's first scan at about 60 s, and cleaned=1000 shows every replacement came after its post. Inferred cause: the scan ran during setup, so no candidate went stale before the client reached it. That run's server output was not kept, so this is inferred rather than observed. Fix: setup batched with multi (about 1 s), a guard that fails as INCONCLUSIVE if setup crosses the scan, and surefire output now retained. Three of three later quorum runs passed.

### Limits
- Level 0 used 1000 candidates to stretch the manager's pass to about 6 s, and the client began replacing when it saw the first deletion. A single candidate with no hook was NOT reproduced at Level 0: its scan-to-post gap is very short.
- The lost fraction depends on client speed relative to pacing: replace loop 21.6 s -> about 10% lost; 0.6 s -> 93% lost. The two trees are on different filesystems (/tmp on /dev/sda3, worktree on NFS /bulk), which is the likely cause of the speed difference; this was not isolated.
- Immediate c6 hits (the workload's own read order) are occasional at Level 0: 3 of 4 pristine final-script runs, 1 of 4 earlier passing pristine runs, and 0 of 1 worktree runs. Later reads hit in every run where a node was lost. Level 1 makes the immediate hit deterministic.
- The controls show outcomes (c6 OK). They do not separately assert which exception PRP raised.

## Novelty search (run only after the reproduction verdict was settled; Shared Rule 2)
Queries:
- specula findings lookup: ContainerManager, deleteContainer, TargetSafe, handleGetDataRequest -> []. Run after reproduction rather than before it, to respect Shared Rule 2.
- git log (pinned tree only): ContainerManager.java; -i --grep=container; -S'case OpCode.deleteContainer' on PrepRequestProcessor.java.
- JIRA JQL (project=ZOOKEEPER): text~"deleteContainer" (10); text~"ContainerManager" (39); summary~"container" (24); text~"container" AND text~"recreated" (50); text~"container node" AND text~"race" (26); text~"CVE-2026-79993" (0); updated>=2026-06-01 AND (text~"deleteContainer" OR text~"container") (41, first 20 titles); text~"OpCode.deleteContainer" (2).
- JIRA description/comment grep for race|stale|re-creat|same path|replac on ZOOKEEPER-2163, 2591, 2648, 3546, 4915, 2705, 3001, 4993, 4238, 4239, 4430: only 2648 (scan-time reasoning, different aspect) and an unrelated 2591 phrase.
- GitHub search (apache/zookeeper, issues and PRs, open and closed, sorted by updated): deleteContainer (2); ContainerManager (10); container in:title is:pr (13); stale container delete (0); container race recreate (1, ZOOKEEPER-4689, ACL index, different); CVE-2026-79993 (0); deleteContainer ACL (0). PR #2430 / ZOOKEEPER-4993 changes logging only.
- Recent upstream commits on PrepRequestProcessor.java and ContainerManager.java, read through the API with nothing checked out: none concerns this mechanism. Upstream master's deleteContainer branch, read over HTTP, shows the same childCount and NORMAL checks.
- Web search: one query, no report of this mechanism.

Nearest report: CVE-2026-79993 (https://zookeeper.apache.org/security.html; https://security-tracker.debian.org/tracker/CVE-2026-79993), "Missing ACL check on deleteContainer opcode allows unauthorized deletion of any empty persistent/container znode", fixed in 3.9.6 / 3.8.7. It has the same PRP path but a different mechanism: a remote client sends raw opcode 20 to bypass the session and ACL checks. Its text mentions neither ContainerManager, staleness nor re-creation. MC-1 needs no unauthorized client or raw opcode; the server's own manager acts on a stale decision. Limits: the advisory's mailing-list thread did not render, and no fix commit could be identified, so whether that fix would incidentally affect MC-1 is unknown. The master gate as read still admits an empty PERSISTENT node, but MC-1 was not run on master or 3.9.6.
Outcome: NEW. No report of this mechanism was found. Long JIRA lists were judged by title, so this is a bounded negative.
