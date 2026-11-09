# HBASE-15039 (Token authentication fails): detected

Case `hbase-adhoc-k1`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java:147`, `AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenIdentifier)`, throws `org.apache.hadoop.security.token.SecretManager.InvalidToken` when `masterKey == null   (masterKey = allKeys.get(identifier.getKeyId()))`
- Starting test: `org.apache.hadoop.hbase.security.token.TestTokenAuthentication#testTokenAuthentication`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** After a key-master failover, the new leader (rs-B) rolls key 2 and signs a fresh token with it. A follower RPC server (rs-C), whose ZooKeeper tokenauth notifications are delayed, rejects that valid token over real SASL DIGEST-MD5 with InvalidToken 'Unknown master key for token (id=2)'.

**Same root cause as HBASE-15039?** The failing execution goes through RpcServer -> HBaseSaslRpcServer$SaslDigestCallbackHandler.getPassword -> AuthenticationTokenSecretManager.retrievePassword. The test's LoggingSecretManager wrapper only passes the call through. At AuthenticationTokenSecretManager.java:145-148 the buggy code reads allKeys.get(keyId) and throws as soon as the key is missing, because rs-C has not yet applied the ZK key-update event for key 2. It never re-reads /hbase/tokenauth/keys from ZooKeeper. The fix hunk (@@ -143,6 +143,27) adds exactly this missing step: if masterKey == null it restarts a dead leaderElector, calls the new ZKSecretWatcher.refreshKeys(), and looks the key up again. That is the defect in the CRITERIA row (key id not known yet because the ZK key-update event has not been applied).

**Realistic?** Yes. It uses a mini ZK cluster, real AuthenticationTokenSecretManager instances with production key-roll and token-lifetime defaults, real leader election, and a clean stop of the key master as in a rolling restart. The new leader rolling a key right away is the system's own behaviour. The only intervention is a listener registered first on rs-C's ZooKeeperWatcher that blocks the ZK event thread on a latch for tokenauth events. That is a delay forcing an interleaving the real system can produce: a busy or slow single event thread, or notifications arriving late. It fabricates no state and does not call retrievePassword directly. The token comes from generateToken on the real leader, and the client authenticates over a real RPC.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. With the fix's production changes the check's exception is not hit in either of the 2 attempts (NOT_REPRODUCED). The test fails only at its own assertion 'client authentication should have failed' (line 551). So rs-C refreshed the keys from ZK and accepted the token while its notifications were still delayed, and the authentication failure goes away.

**Reason:** The agent's validated reproduction reaches the exact defect HBASE-15039 fixes: retrievePassword rejects a token whose key is already in ZooKeeper but not yet in the server's local key cache, and never re-syncs. The trigger is a realistic delay of ZK notifications combined with key-master failover. The consequence is the JIRA's: a client with a valid token fails authentication. The fixed version removes that failure.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The token is unexpired and correctly signed by the cluster's current key master, so a correct key coordination should not reject it. The protocol starts signing tokens with a new master key the moment the leader writes it to ZooKeeper. Followers learn about the key only asynchronously through watch notifications, and retrievePassword never falls back to reading /hbase/tokenauth/keys/<id> when it misses a key. So there is always a window, made larger by key-master failover (every new leader rolls a key immediately), by the periodic key roll, and by any delay in a follower's ZK notifications (slow event thread, connection loss within the 90s session timeout), in which some region servers reject valid delegation tokens. In a real deployment, MapReduce/Spark tasks or other token-authenticated clients that got a token right after a roll or a key-master move (for example during a rolling restart) fail SASL authentication to some region servers with 'Unknown master key'. The tasks or jobs fail even though their credentials are valid.

**Execution (agent):** Three region servers share one mini ZK; each runs an AuthenticationTokenSecretManager (production defaults: 24h key roll, 7d token lifetime). (1) rs-A starts first, wins the /hbase/tokenauth/keymaster election and rolls master key 1 into /hbase/tokenauth/keys/1. (2) rs-B (a standby) and rs-C (a secure RpcServer with TokenProvider, i.e. the TestTokenAuthentication TokenServer) start as followers and load key 1 from ZK; a token signed with key 1 authenticates successfully to rs-C (sanity). (3) rs-C's ZooKeeper watch notifications for the tokenauth znodes are delivered late (a listener registered first on rs-C's ZooKeeperWatcher holds the single ZK event thread on a latch; this models a follower whose ZK client is briefly disconnected / whose event thread is busy, while its RPC server keeps serving). (4) rs-A is shut down (rolling restart): it steps down and deletes the keymaster znode. (5) rs-B wins the election; because a new leader starts with lastKeyUpdate=0 its LeaderElector immediately calls rollCurrentKey(), creating key 2 in ZK and making it the signing key at once. (6) A client gets a fresh token from rs-B (generateToken signs it with key 2) and connects to rs-C with SASL DIGEST-MD5. rs-C's RpcServer -> SaslDigestCallbackHandler -> AuthenticationTokenSecretManager.retrievePassword finds allKeys.get(2)==null and throws InvalidToken('Unknown master key for token (id=2)') at AuthenticationTokenSecretManager.java:147/148; the client's connection fails with RemoteException(InvalidToken). (7) When rs-C's pending ZK notifications are delivered it adds key 2, and the very same token now authenticates successfully, showing that the token was valid all along.

**Stack frame (agent):** at org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenSecretManager.java:148)  [the throw statement of the `if (masterKey == null)` check on line 147; javac attributes the `new InvalidToken(...)` to line 148]

## Reproduction

- Test: `org.apache.hadoop.hbase.security.token.TestTokenAuthenticationKeyLeaderFailover#testTokenRejectedByFollowerAfterKeyMasterFailover`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.security.token.TestTokenAuthenticationKeyLeaderFailover#testTokenRejectedByFollowerAfterKeyMasterFailover' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/TestTokenAuthenticationKeyLeaderFailover.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.security.token.SecretManager$InvalidToken: Unknown master key for token (id=2)`, frame `at org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenSecretManager.java:148)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 1,180,212 | 44 | 25,937 | 65,120 | 1,089,111 | $1.26 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
