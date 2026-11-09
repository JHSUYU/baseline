# MC-1 investigation (Phase 1: evidence only)

Target (target.yaml): `AuthenticationTokenSecretManager.retrievePassword` throws
`SecretManager.InvalidToken` at ATSM:147 when `allKeys.get(identifier.getKeyId()) == null`.
Pinned tree: base_commit 92aa67fd15. All line numbers are from `git show HEAD:<file>` (the
worktree and source tree carried Specula trace instrumentation, which was reverted in the
worktree before reproduction; backup in `instrumentation-backup/`).

Persistent-findings lookup (`specula findings lookup --query retrievePassword --query TargetSafe
--query rollCurrentKey --query "Unknown master key"`): `[]`, no prior record.

## Step 1: code audit

Cited code (pristine):
- ATSM:243-265 `rollCurrentKey()` (synchronized, keymaster only): `allKeys.put(newKey)` (254),
  `currentKey = newKey` (255), and only then `zkWatcher.addKeyToZK(newKey)` (256).
- ATSM:127-136 `createPassword()`: reads `currentKey` (129) with no lock and no check that the
  key was published; signs the token with it.
- ATSM:139-153 `retrievePassword()`: expiry check (142-144), then `allKeys.get(keyId)` (145);
  null -> `throw new InvalidToken("Unknown master key for token (id=...)")` (146-148). There is
  no read-through to ZK on a miss.
- ZKSW:57-67 `start()`: the follower reads the children of `/hbase/tokenauth/keys` once, with a
  child watch. ZKSW:120-132 `nodeChildrenChanged()`: re-reads children and calls
  `refreshNodes` -> ATSM:171-192 `addKey`. These run on the follower's single ZooKeeperWatcher
  event thread (ZooKeeperWatcher.process, listeners called in order).
- ATSM:310-334 leader loop: rolls when `lastKeyUpdate + keyUpdateInterval < now`, sleeps 5 s.

Call chain to the target (real consumer):
client `RpcClientImpl` SASL DIGEST-MD5 with an HBase auth token -> server `RpcServer`
`Connection.saslReadAndProcess` -> `saslServer.evaluateResponse` (RpcServer:1453) ->
`HBaseSaslRpcServer.SaslDigestCallbackHandler.handle` (:110) -> `getPassword` (:84) ->
`ATSM.retrievePassword` -> ATSM:147. On `InvalidToken`, RpcServer:1454-1470 replies
`SaslStatus.ERROR` with the InvalidToken class/message, counts `authenticationFailure`, writes
the AUDITLOG "Auth failed", and closes the connection. The client (`RpcClientImpl`
handleSaslConnectionFailure :638-688, setupIOstreams :770-790) does not retry token auth
(retry/relogin is Kerberos-only, `shouldAuthenticateOverKrb`), adds the server to
`failedServers`, and fails the call.

Token issuance: `TokenProvider.getAuthenticationToken` (TokenProvider:100-134) ->
`ATSM.generateToken` -> `createPassword`. Any region server hosting the TokenProvider
coprocessor issues tokens, from its own `currentKey`; the keymaster's currentKey is the newest.

Reachability: normal operation. The keymaster rolls every `hbase.auth.key.update.interval`
(default 24 h). A token issued by the keymaster right after a roll, then used at another
server whose ZK event thread has not yet processed the keys NodeChildrenChanged event (or that
is starting up and read the children before the key was written, as in the TLC trace), hits
ATSM:147. No fault is needed.

Safeguards noted (Phase 2 must test): (a) propagation lag is normally milliseconds; (b) the
follower is later repaired by the NodeChildrenChanged event, so the *missing-key state* is
transient; (c) higher-level HBase clients (RpcRetryingCaller) may retry a failed call after
`failedServers` expiry (2 s default), which could mask the failure for retrying callers.
The raw blocking stub used by the workload test does not retry.

Trigger scenario (from MC_hunt_S3 counterexample, 20 states, no faults): n1 claims keymaster
(state 8-9), loop decides to roll (10-11), a token issue reads the clock (12), n1 installs key 1
in allKeys/currentKey (14, ATSM:254-255, not yet in ZK), the token is signed with key 1 (15),
n2 runs ZKSecretWatcher.start and reads an empty children list (16-19), n2 validates the token:
`allKeys[n2]` has no key 1 -> targetFired (20).

## Step 2: developer knowledge

Recorded only after the reproduction verdict (Shared Rule 2); see "Novelty search" below.
Comments at the site: ATSM:44-56 class javadoc says keys "are then distributed to followers
via ZooKeeper"; ZKSW:231 `// TODO: is there any point in retrying beyond what ZK client does?`
(about ZK write retry, not lag). Existing tests: `TestZKSecretWatcher` waits for followers
to receive keys before asserting (it polls), i.e. the tests themselves acknowledge asynchronous
propagation but no test asserts a token from a fresh key validates at a follower immediately.

## Step 3: known-status

See "Novelty search" (filled after Phase 2).

## Phase 2 summary (see final verdict in the worker response)

- Repro: `repro/test_bugMC-1_fresh_key_propagation.sh` (pristine main sources, reactor build of
  hbase-client + hbase-server, no install) running `repro/test_bugMC-1_SpeculaAdhocMC1Test.java`
  (two-server variant of TestTokenAuthentication; TokenServer copied verbatim).
- Level 0: 4/4 trials, follower `retrievePassword` threw `InvalidToken: Unknown master key for
  token (id=N)` at ATSM.retrievePassword(AuthenticationTokenSecretManager.java:148) — the throw
  statement spanning 147-148 (javap LineNumberTable: line 147 = bci 49-65, line 148 = bci
  66-83, athrow at bci 83). The real SASL RPC to the follower won the race 0/4 (ZK propagation
  2-3 ms beat the handshake).
- Level 1: listener registered first on B's ZooKeeperWatcher sleeps 3 s on the keys
  NodeChildrenChanged event. whoAmI at B with the fresh token FAILED with
  RemoteException(InvalidToken: Unknown master key for token (id=2)); the same token is accepted
  by issuer A; B applied key after ~2975 ms and a retry succeeded. -XX:+TraceExceptions shows the
  throw on the RpcServer reader thread (not the test thread): retrievePassword bci 83 ->
  HBaseSaslRpcServer getPassword/handle -> DigestMD5Server.validateClientResponse
  (`repro/MC-1.server-throw.trace.txt`).

## Novelty search (run only after the reproduction verdict was settled)

Queries:
1. WebSearch: `HBase AuthenticationTokenSecretManager retrievePassword "Unknown master key for token" refreshKeys zookeeper JIRA` -> only source/javadoc pages; the current source calls zkWatcher.refreshKeys() on a miss.
2. WebSearch: `HBASE jira "Sync token keys from zookeeper" AuthenticationTokenSecretManager` -> same.
3. GitHub API: commit search `repo:apache/hbase refreshKeys` -> 0 results.
4. GitHub API: commit history of AuthenticationTokenSecretManager.java -> `1c7e9ec124 2015-12-25 HBASE-15039 HMaster and RegionServers should try to refresh token keys from zk when facing InvalidToken (Yong Zhang)`.
5. JIRA REST HBASE-15039: Resolved/Fixed, fixVersions 1.2.0, 1.3.0, 0.98.17, 2.0.0. Description: key slaves "may lost new token, client which use token authentication will get InvalidToken exception"; cause stated as slave/ZK disconnection. Fix adds read-through (refreshKeys) on a miss at this exact site.
6. Upstream master (raw.githubusercontent): retrievePassword now refreshes on a miss (line 153), but rollCurrentKey still does `allKeys.put(newKey)`, `currentKey = newKey` before `addKeyToZK(newKey)` (lines 257-259), so the sign-before-publish sub-window of the TLC trace (token validated at a follower before the key is in ZK) is not closed by that fix.

Result: Novelty = KNOWN (cite: HBASE-15039; fix-status: fixed) for the follower-lag / no-read-through mechanism at ATSM:145-148; note the unfixed residual sign-before-publish window. Novelty does not change the verdict.
