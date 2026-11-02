# zk-adhoc-b4: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.zookeeper.retry.CausynthZooKeeperRetryQuotaTest#createsTwoSequentialChildrenUnderAHardQuota`, in the fork tree `/bulk/wt/zookeeper-checks`, `zookeeper-contrib/zookeeper-contrib-zooinspector/src/test/java/org/apache/zookeeper/retry/CausynthZooKeeperRetryQuotaTest.java` (case `zk-bugs-retry-seq-quota`). It extends `ClientBase`, which the fork makes visible to ZooInspector's tests by adding to the module's `pom.xml` the `zookeeper` test-jar, the JUnit 5 engine and platform runner, `snappy-java` and `metrics-core` (test scope) and the GraphChecker jar.
- **Port**: `org.apache.zookeeper.retry.TestAdhocWorkloadB4#run`, in `tree/zookeeper-contrib/zookeeper-contrib-zooinspector/src/test/java/org/apache/zookeeper/retry/TestAdhocWorkloadB4.java`, plus `tree/.mvn/maven.config` (see below). Both are untracked files of the case tree; no tracked file (no `pom.xml`) changes.

## Kept (same scenario)

- Topology: one standalone server in the test's JVM, set up as `ClientBase` sets up its server: fresh data directory, `new ZooKeeperServer(dataDir, dataDir, 3000)`, `setCreateSessionTrackerServerId(1)`, `ServerCnxnFactory.createFactory(addr, 0)` (`ClientBase.maxCnxns` = 0), `zookeeper.preAllocSize=100` and `FilePadding.setPreallocSize(100 KB)` (`ClientBase.setupTestEnv`), client connection timeout 30 s (`ClientBase.CONNECTION_TIMEOUT`).
- The test's own configuration: `zookeeper.enforceQuota=true` set before the server starts and cleared in tear-down (as the original's `setUp`/`tearDown`). The target's `jvm_properties: -Dzookeeper.enforceQuota=true` is therefore not needed; ZooInspector's surefire passes no `-D` from the Maven command line to the forked test JVM anyway (no `argLine`/`systemPropertyVariables` in its pom).
- The operations in the same order: a plain client connects; creates the path; `SetQuotaCommand.createQuota` with a hard count limit of 3; a `ZooKeeperRetry(hostPort, 30000, watcher)` connects (waits up to 30 s); two `PERSISTENT_SEQUENTIAL` creates of `PATH + "/n-"` through it; it closes.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `extends ClientBase` (JUnit 5), its server, `createClient()`, `CountdownWatcher.waitForConnected` | JUnit 4 test (the module's own engine, `junit-vintage-engine`) that starts the server with the same production calls `ClientBase.startServerInstance` makes, and waits for `SyncConnected` with a latch | upstream ZooInspector's test classpath has neither the `zookeeper` test-jar (`ClientBase`) nor the JUnit 5 engine; the fork's `pom.xml` additions cannot be overlaid as untracked files. Port allocation uses an ephemeral port (`PortAssignment` is in the test-jar). `ClientBase`'s JMX bean checks and fd counting are test-hygiene checks, not part of the scenario |
| fork `pom.xml`: test-scope `metrics-core` and `snappy-java` | `tree/.mvn/maven.config`: `-Dmaven.test.additionalClasspath=${settings.localRepository}/io/dropwizard/metrics/metrics-core/4.1.12.1/metrics-core-4.1.12.1.jar,${settings.localRepository}/org/xerial/snappy/snappy-java/1.1.10.5/snappy-java-1.1.10.5.jar` | the server needs both at run time (`ServerMetrics` -> `com.codahale.metrics.Reservoir`; snapshot naming -> `org.xerial.snappy.SnappyInputStream`); `zookeeper-server` declares them `provided`, so they are not on ZooInspector's test classpath. Without them the server does not start (`NoClassDefFoundError`). `.mvn/maven.config` is read by every `mvn` run in the tree, so any test command Specula uses gets them; the jars are already in the case's Maven repository |
| fork `pom.xml`: GraphChecker jar (`provided`) | dropped | GraphChecker |
| class/method names, path `/causynth-retry-quota`, javadoc on `ZooKeeperRetry` re-creating a create that lost its connection unless `exists` finds the path | `TestAdhocWorkloadB4#run`, `/adhoc-workload-b4`, javadoc listing the operations and the server set-up | neutral names; no comment states the failure or the mechanism |

**Operator decision.** The port relies on the untracked `.mvn/maven.config` (classpath only, no scenario change). The alternative is to put the same `-Dmaven.test.additionalClasspath=...` in the target's `test_command`; then Specula must remember it for every test run it makes. The test needs `-Pfull-build` (the module is in the reactor only under that profile), which the target already has.

The workload injects no fault.
