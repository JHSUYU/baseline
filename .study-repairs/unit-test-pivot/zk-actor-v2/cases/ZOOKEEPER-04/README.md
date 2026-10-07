# ZOOKEEPER-04: actor-aware original-cluster baseline

The unchanged ZooKeeper 3.8.7 `ConnectionMetricsTest#testRevalidateCount`
starts a three-peer quorum, establishes one client session on follower1,
changes its server list, shuts down follower1, and reconnects the same client
to follower2. The selected check is
`ZooKeeperServer#processConnectRequest` at source line 1431. Its throw arm at
line 1441 raises `CloseRequestException(CLIENT_ZXID_AHEAD)` when the client's
last seen zxid exceeds the server's last processed zxid. The original source
and compiled test are from commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

The older 80 fault trials in `../../../cases/ZOOKEEPER-04` remain legacy
evidence and contribute **zero** V2 effective trials. Their selectors used a
static I/O call site and global ordinal. In legacy trial 015, the same write
ordinal selected follower1 whereas the healthy run selected follower2. The
old trace cannot prove a same-actor fault or target guard.

## Runtime identity contract

The case ASM adapter records the original test's three actual `QuorumPeer`
objects, SIDs, client ports, and snapshot directories. It labels the two
follower objects using the original test's local variables, then binds the
single `ZooKeeper` object's `ClientCnxn` and its nonzero raw session after
the first original `waitForConnected`. Each client `SocketChannel` I/O uses
the actual local ephemeral port and remote peer port. The target guard counts
only when its `ZooKeeperServer` receiver is exactly follower2's active server,
its `ServerCnxn` belongs to that receiver, its remote port joins the
registered client channel, and `ConnectRequest.sessionId` equals the raw
session of that original client. The first connection's guard is unselected.
Unbound I/O, unknown file owner, wrong peer, or another session cannot match
an injected selector or retain the selected target. `TARGET_THROW` is an
observation for source review, not an automatic new-bug verdict.

The agent is graph-free. It instruments client/server `SocketChannel`
read/write and `QuorumPeer` epoch-file I/O, plus production source-line
coverage and the exact guard/throw. `Probe` applies an ordered I/O exception
plan. The offline build checks rewritten bytecode with ASM and the JVM's
`-Xverify:all`; the wrong-actor smoke proves a follower1 or unregistered
client at the same static write site cannot match follower2's selector.
`ZooKeeperServer` is explicitly retransformed because ASM frame computation
of another class can load that superclass before its target transformer.

## Fresh calibration and budget

The two authoritative healthy runs are `healthy-final-a/b` on node2 in
`/users/ZhenyuLi/zk04-actor-v2-runs`. Both original JUnits passed in
14.159 s and 13.361 s. `node2-calibration-audit.json` proves, per run, three
peer bindings, follower1 SID 1, follower2 SID 2, the raw client session,
one unselected initial guard, one selected follower2 normal guard,
zero selected throws, and five stable target-related I/O families. Both
selected server remote ports joined the same client's local channel port.
The node2 build receipt and original test-class SHA-256 are preserved as
`node2-build-receipt.json` and in the JUnit receipts. The earlier node0
calibration remains in `node0-calibration-audit.json` and is excluded from
the node2 campaign denominator.

`campaign.py` keeps an atomic checkpoint and reconstructible JSONL ledger.
It retains only trials whose full ordered actor-aware exception plan is
matched and applied and whose same-session follower2 guard executes after
the final fault. The original JUnit result is recorded separately. It
mutates effective runs from observed I/O after the final fault and before
the selected guard; priority uses new production coverage and related I/O
families. The default budget is **80 effective trials, at most 8 faults per
sequence**. If any of the final eight effective trials contributes new
coverage, a new related I/O family, or a selected throw, the budget extends
to **128 effective / 10 faults**. The total attempt cap is 480 and every
trial checks for at least 2 GiB free disk before launching a cluster JVM.
`audit_trials.py` independently re-reads raw events, target owner receipts,
original JUnit exit and elapsed time, and all checkpoint rows.

The node2 pilot uses one JVM at a time in PortAssignment slot 15 of 16
(ports 30065–31410), separate from ZK11/12's slot 16 and Solr's scratch.
The `--max-new-attempts 5` option safely pauses after five complete trials;
rerunning without that option resumes the same checkpoint.

The five-trial coexistence pilot ran on node2 from 05:21:26 to 05:23:04 UTC
on 2026-10-07. All five ordered plans were applied to bound actors and the
selected follower2 guard ran after the last fault. The unchanged JUnit
passed all five in 14.113–17.777 s. Trial depths were 1 or 2; the first five
effective runs added nine production source lines and six related I/O
families, with zero selected throws. `pilot-raw-audit.json` and
`pilot-summary.csv` preserve the independent raw receipt audit and each
trial's time. The full campaign resumed from the same checkpoint; these
five count in its 80-effective budget.
