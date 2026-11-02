# hbase-adhoc-34: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hbase.security.token.TestCausynthTokenKeys#anotherServerValidatesTheKeyMastersToken`, in the fork tree `/bulk/wt/hbase-checks` (JHSUYU/hbase `graphchecker/hbase-checks`, on top of upstream `1790942bb2`), `hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/TestCausynthTokenKeys.java` (fork commits `c0f65a942c`, `5e7f0688a5`). It relies on a fork change to production code: `RpcServer#CAUSYNTH_TOKEN_SECRETS` (`causynth.hbase.token.secrets`), which makes `RpcServer#createSecretManager` build the token secret manager when security is off (owner 2026-10-19: no MiniKdc, no Kerberos).
- **Port**: `org.apache.hadoop.hbase.security.token.TestAdhocWorkload34#run`, in `tree/hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/TestAdhocWorkload34.java`. Untracked file of the case tree; no tracked file changes.

## Kept (same scenario)

- Topology: one master, one region server, `HBaseTestingUtil.startMiniCluster(1)`, simple authentication.
- Every server's RPC server runs an `AuthenticationTokenSecretManager` built exactly as upstream `RpcServer#createSecretManager` builds it on a secure cluster (`hbase.auth.key.update.interval` default 24 h, `hbase.auth.token.max.lifetime` default 7 d, the server's own `ZKWatcher` and server name), started and installed by `NettyRpcServer#start` (as in the fork).
- The operations in the same order: take the master's and the region server's secret managers from their RPC servers; wait (up to 60 s) until one is the key master; wait (up to 60 s) for its current key; it generates a token; the other manager `removeKey`s the token's key id; `retrievePassword(identifier)` on the other manager must equal the token's password (`assertArrayEquals`).
- JUnit 5, `@Tag(SecurityTests.TAG)` and `@Tag(MediumTests.TAG)`, as the original and upstream `TestZKSecretWatcher`.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `conf.setBoolean(RpcServer.CAUSYNTH_TOKEN_SECRETS, true)` (fork-only switch in `RpcServer#createSecretManager`) | `hbase.rpc.server.impl` (`RpcServerFactory.CUSTOM_RPC_SERVER_IMPL_CONF_KEY`, an upstream extension point) set to the test's `NettyRpcServer` subclass `TokenSecretsRpcServer`, whose `createSecretManager()` is upstream's without the `isSecurityEnabled` early return | upstream has no such switch and the tracked `RpcServer.java` must not change; the subclass reproduces the fork's behaviour (same manager, same constructor arguments, same start in `NettyRpcServer#start`, used by both the master and the region server, which both create their RPC server through `RpcServerFactory`) |
| class/method names, token user `causynth` | `TestAdhocWorkload34#run`, user `adhoc` | neutral names (B3) |
| javadoc naming GraphChecker, the switch, and why the key is removed (a validation before the watch event of the key is processed, so the keys are refreshed from ZooKeeper) | javadoc listing the set-up and the operations only | no comment states the mechanism |

**Operator note (decision).** The original's `other.removeKey(keyId)` is kept: it is part of the original scenario (the other manager validates before it has applied the key), and `removeKey` is the call `ZKSecretWatcher` itself makes on a key znode's deletion. It does touch `allKeys`, the map the guard's operand comes from (`masterKey = allKeys.get(keyId)`). It does not set the guard's value: after the miss, `retrievePassword` calls `ZKSecretWatcher#refreshKeys`, which reloads every key from ZooKeeper before the guard reads `allKeys` again. Dropping the call would make the method find the key on its first lookup and skip the refresh. Ask the owner if the stricter reading of "never write the guard's operands" should drop it.

The workload injects no fault.
