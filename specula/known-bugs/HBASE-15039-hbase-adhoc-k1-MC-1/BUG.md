# HBASE-15039: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hbase-adhoc-k1`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

One server (HMaster or a RegionServer) is the token key master (elected through `ZKLeaderManager`); it writes authentication keys under the keys znode. The others (key slaves) learn keys only through `ZKSecretWatcher` watch events (`nodeCreated`/`nodeChildrenChanged`/`nodeDataChanged`) and put them into `allKeys`. If a slave misses an update (ZooKeeper disconnection / lost watch event / validation racing ahead of the event), its `allKeys` lacks the token's key id. A client presenting a token issued with that key gets `InvalidToken("Unknown master key for token ...")` from `retrievePassword`, and the server never re-reads ZooKeeper, so authentication keeps failing. Fix: on a miss, `retrievePassword` calls a new `ZKSecretWatcher.refreshKeys()` (re-read all children of the keys znode) and restarts a dead leader elector, then looks again.

## What counted as detecting it (written before the run)

A Specula finding counts as this bug if it reaches the throw at line 147 on a server that is **not** the key master (or a server whose key view is stale) for a token whose key the key master did write to ZooKeeper, because the server's `allKeys` was not updated (missed/lost watch notification, ZK session disconnect/expiry, or validation before the key event is processed), and nothing in `retrievePassword` re-syncs from ZooKeeper. Root cause: no fallback read of ZooKeeper on a key miss. Expired tokens (line 143) or keys legitimately removed after expiry do not count.

## What Specula found

**Specula's finding MC-1:** Token signed with a freshly rolled key is rejected (InvalidToken, ATSM:147) by a server that has not yet applied the key from ZooKeeper

- **Cause:** rollCurrentKey installs the new key in allKeys/currentKey (ATSM:254-255) before writing it to ZK (ATSM:256); createPassword signs with currentKey at once (ATSM:129); followers learn keys only asynchronously via ZK watch events (ZKSW:120-131) and retrievePassword has no read-through on a miss (ATSM:145-148).
- **Trigger:** A client obtains a token from the keymaster right after a key roll and authenticates (SASL DIGEST) to another server before that server's ZK event thread applied the keys NodeChildrenChanged event (or while it starts up and read the children before the key was written).
- **Consequence:** The follower's RpcServer SASL handler gets InvalidToken('Unknown master key for token') from retrievePassword at ATSM:147; the client's RPC fails with RemoteException(InvalidToken) for a valid, unexpired token the issuer accepts. The follower repairs itself once the event is processed.
- **Premises:** No fault needed; normal key roll every hbase.auth.key.update.interval. Token is presented to a non-keymaster server inside its key propagation window (ms normally; widened by a busy follower ZK event thread). Pinned tree 92aa67fd15 predates HBASE-15039 (refresh keys from ZK on InvalidToken). The raw RPC client does not retry token SASL failures (RpcClientImpl handleSaslConnectionFailure retries only Kerberos); higher-level retrying callers were not evaluated.

**Operator's judgement:** yes. follower validates before applying ZK key event; no read-through on miss (transient window, root cause = fix)

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S3.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 2h11m | 63.1M | $44.88 |

Time is active time; quota sleeps are excluded.
