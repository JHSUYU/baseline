# hbase-adhoc-34: A follower that is late to see a key roll issues delegation tokens that outlive their signing key; once the leader expires the key, those tokens are rejected as 'Unknown master key' before their stated expiration.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java:160`, `AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenIdentifier)`, throws `org.apache.hadoop.security.token.SecretManager.InvalidToken` when `masterKey == null   (masterKey = allKeys.get(identifier.getKeyId()))`
- Starting test: `org.apache.hadoop.hbase.security.token.TestAdhocWorkload34#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** The delivery of the key-roll ZK notification to the follower AuthenticationTokenSecretManager is delayed (its ZK event thread is held, standing in for a slow event thread or a short ZK disconnect). Meanwhile the follower issues a token signed with the replaced key, and the leader later expires and deletes that key while the token is still unexpired.

**Why (root cause in the source):** When the leader rolls a key it sets the old key's expiration to rollTime + tokenMaxLifetime (AuthenticationTokenSecretManager.java:262-266). A follower signs tokens with whatever currentKey it last heard about over ZK, and gives them expiration = issueTime + tokenMaxLifetime (AuthenticationTokenSecretManager.java:121-128). Nothing limits a token's expiration to its key's expiration. A token issued by a stale follower after the roll therefore outlives its key. removeExpiredKeys deletes the key (AuthenticationTokenSecretManager.java:228-236), and retrievePassword rejects an authentic, unexpired token with 'Unknown master key', even after refreshKeys (AuthenticationTokenSecretManager.java:153-160). The trigger is a plain notification delay. The token is rejected for good, but only during the last part of its life, a period about as long as the propagation delay (seconds against a 7-day default lifetime), so the impact is small.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The token is authentic: a cluster member issued it with a key the leader had distributed, and it is inside its declared lifetime. The cluster should accept it. The coordination assumes that every token signed with a key expires no later than that key's expiration (rollTime + maxLifetime). That holds only for tokens the leader issues. Followers sign with whatever current key they last heard about over ZK, and nothing ties the token's expiration to the key's expiration or makes a follower stop using a replaced key. So any delay in watch delivery (a busy event thread, a ZK disconnect shorter than the session timeout, GC pauses) lets followers issue tokens that outlive their key, and clock skew between servers has the same effect. In production the RegionServer hosting the TokenProvider endpoint (usually a follower) hands MapReduce/Spark jobs and other delegated clients tokens that stop working before their stated expiration. Long jobs then fail authentication with 'Unknown master key' near the end of the token lifetime, even though the token was never expired or revoked.

**Execution (agent):** Setup as TestAdhocWorkload34 (master + 1 RS, each RpcServer runs an AuthenticationTokenSecretManager), with hbase.auth.key.update.interval=2s and hbase.auth.token.max.lifetime=20s (the leader loop runs every 5s). 1) One manager wins the ZK leader election (the key master) and the other is a follower. Both share current key K2. 2) Delivery of the next ZooKeeper key notification to the follower is delayed. A test ZKListener registered first on the follower's ZKWatcher holds the single zk-event-processor thread on the NodeChildrenChanged event for /hbase/tokenauth/keys. This stands in for a slow event thread, or a follower briefly disconnected from ZK within its session timeout. The server is neither aborted nor fenced. 3) The leader rolls its key on its normal schedule. It writes K3 to ZK and sets K2.expiration = rollTime + 20s (K2 expiring at ...194857). 4) The follower has not processed the event yet, so its currentKey is still K2. Ten seconds later it serves a token request (generateToken, as TokenProvider does), and createPassword signs the token with K2, giving expiration = issueTime + 20s = ...204863, 10s after K2's own expiration. 5) The follower's events are released and it catches up. 6) At rollTime+20s the leader's removeExpiredKeys deletes K2 from its map and from ZK (at ...194900), and the follower removes K2 when it gets nodeDeleted. 7) The token is still unexpired. Validating it (retrievePassword on the follower, which is also what the leader would do) finds no K2. refreshKeys re-reads ZK and still finds no K2, so InvalidToken 'Unknown master key for token (id=2)' is thrown at AuthenticationTokenSecretManager.java:160.

**Stack frame (agent):** at org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenSecretManager.java:160)

## Reproduction

- Test: `org.apache.hadoop.hbase.security.token.TestAdhocWorkload34StaleKey#run`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.security.token.TestAdhocWorkload34StaleKey#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/TestAdhocWorkload34StaleKey.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.security.token.SecretManager$InvalidToken: Unknown master key for token (id=2)`, frame `at org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenSecretManager.java:160)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h06m | 1 | 491,006 | 20 | 25,079 | 53,622 | 412,285 | $1.01 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
