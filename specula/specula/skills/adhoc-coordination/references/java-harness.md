# Java Harness Notes for Ad Hoc Targets

These notes complement the harness-generation skill's `trace-module-patterns.md` (Category A pattern, git-patch instrumentation).

## Build with Maven (Hadoop, HBase, ZooKeeper)

- Source the target file's `build.env` before every build call. It sets the JDK, the build tool and the local repository.
- Build once with `build.prepare`. After instrumenting, rebuild only the modules you touched, offline:

  ```
  mvn -B -o install -DskipTests -Dmaven.javadoc.skip=true -pl <module>
  ```

- Run one test with surefire in the workload module:

  ```
  mvn -B -o surefire:test -pl <module> -Dtest='<Class>#<method>' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false
  ```

  Running `test` instead of `surefire:test` recompiles first. Use `test` after you edit test sources.
- Large integration tests (mini clusters) take 20 to 120 s each. Always wrap them in `timeout`, and keep the test's own timeout.

## Build with Ant and Ivy (Solr 8)

- Source the target file's `build.env` before every `ant` call. It sets the JDK, Ant, and the Ivy cache that already holds every dependency; do not resolve from the network.
- Run commands from the module directory, for example `solr/core`. `ant compile compile-test` builds it; `build.prepare` and `build.test_command` in the target file give the exact commands.
- Run one test:

  ```
  ant test -Dtestcase=<Class> -Dtests.method=<method> -Dtests.jvms=1
  ```

  Keep the printed `-Dtests.seed=...` of a run to repeat it. Pass a system property to the forked test JVM with `-Dargs="-D<name>=<value>"`.

## Trace module

Put one `SpeculaTrace` class in the module whose code you instrument, in that module's base package. For example `org.apache.hadoop.hdfs.SpeculaTrace` in `hadoop-hdfs`. A module that cannot see that class (for HDFS: `hadoop-common`, `hadoop-hdfs-client`) either gets a second copy under its own package, or emits through `System.getProperty`-gated reflection; record the choice in `INSTRUMENTATION.md`.

```java
package <module base package>;

import java.io.*;
import java.nio.charset.StandardCharsets;

/** NDJSON trace writer for Specula: one line per event, flushed, enabled by -Dspecula.trace.file. */
public final class SpeculaTrace {
  private static final String FILE = System.getProperty("specula.trace.file");
  private static Writer out;
  private SpeculaTrace() {}

  public static synchronized void emit(String name, String nid, String stateJson, String msgJson) {
    if (FILE == null) return;
    try {
      if (out == null) out = new OutputStreamWriter(new FileOutputStream(FILE, true), StandardCharsets.UTF_8);
      out.write("{\"tag\":\"trace\",\"ts\":" + System.nanoTime() + ",\"event\":{\"name\":\"" + name
          + "\",\"nid\":\"" + nid + "\",\"state\":" + stateJson + ",\"msg\":" + msgJson + "}}\n");
      out.flush();
    } catch (IOException e) { /* tracing must never change behavior */ }
  }
}
```

Rules:

- Never throw, block, or take a lock of the system from `emit`.
- Build the JSON by hand. The build must not need new dependencies.
- Pass the system property to forked test JVMs, for example `-DargLine="-Dspecula.trace.file=..."` (Maven) or `-Dargs="-Dspecula.trace.file=..."` (Ant), or set it with `System.setProperty` in the test before the cluster starts. The forked test JVM does not inherit `-D` flags from the build tool's own JVM.

## Node identity in a mini cluster

All nodes run in one JVM, so identify them from their own state rather than from the process. Map the ids to model names in the test once the cluster is up, and write the mapping as a first `Init` trace line.

- **HDFS** (`MiniDFSCluster`): NameNode `nn<i>` from its RPC address; DataNode `dn<i>` from its xfer port or `DatanodeUuid`; any other daemon `<role><i>` from its storage directory or RPC port.
- **HBase** (`HBaseTestingUtil`): the HMaster `m<i>` and each RegionServer `rs<i>`, from their `ServerName` (host, port, start code).
- **ZooKeeper** (`QuorumBase`, `QuorumPeerTestBase`, `ClientBase`): quorum peers `p<sid>` from `QuorumPeer.getMyId()`; a standalone server `s0`; clients by session id.
- **Solr** (`MiniSolrCloudCluster`, `SolrCloudTestCase`): nodes `n<i>` from their node name (`host:port_solr`). The Overseer is a role held by one node at a time; record which node holds it, by node name.
- **Clients and other callers**: the thread or the object that issued the call.

## Workload variants

Put variants in the workload's test package, as a new class `SpeculaAdhoc<Target>Test`. Build them from the original test's setup code, copied rather than modified. Each variant gets its own trace file. Allowed changes:

- more rounds of the same operations;
- a second client or writer;
- time compression through the configuration keys the test already uses;
- a fault injected through the codebase's own fault-injection points.

Not allowed: writing the target guard's operands, or editing the target method.
