# HBase namespace actor identity, offline V2 preparation

This standalone passive Java agent is a reusable identity layer for
HBASE-08, HBASE-21, and HBASE-22. It targets the unchanged HBase 2.6.6
production JAR and the original two-master `TestNamespaceAuditor` methods.
It has not run a cluster JUnit, injected a fault, or contributed a V2 trial
to any of the three case counters.

## Source relationship

At source revision `d5f63f523c065f963992ea4e74db268d17816631`,
`TableNamespaceManager` constructs its `ZKNamespaceManager` with
`masterServices.getZooKeeper()`; region servers also use
`ZKNamespaceManager`. Thus a znode path and call site alone can merge a
master's I/O with a region server's or the other master's I/O. The selected
`ClusterSchemaServiceImpl` and `NamespaceStateManager` instances each retain
their own `MasterServices`. HBASE-21's quota exception and HBASE-22's region
quota exception are already expected by their unchanged healthy JUnit tests;
an observed throw alone is not a bug.

The agent records the `Abortable` owner of each `ZKWatcher` at construction,
and records a `ZKNamespaceManager` identity for the same watcher. At each
namespace-related `ZKUtil` API attempt it logs the current active/standby
master role or region-server role, the raw `ServerName`, the manager ID, the
watcher identity, the operation, znode path, production call site, and the
ordinal scoped to that watcher and point. It also logs whether the API
returned or threw. At each of the three selected target methods it logs the
same Master watcher, raw `ServerName`, and manager ID, plus the target
argument and exception outcome. These are high-level ZooKeeper API attempts;
they do not assert that an underlying network packet was sent or persisted.

The optional `-Dns.actor.fault.plan` accepts semicolon-separated ordered
steps of `role~family~URL-safe-Base64(path)~site~ordinal~kind`, copied from
healthy `IO_ATTEMPT selector=` receipts and suffixed with
`CONNECTIONLOSS`, `OPERATIONTIMEOUT`, or `SYSTEMERROR`. With no property, the
agent is passive. Fault matching accepts only an `ACTIVE_MASTER` event with
a bound namespace manager and raw `ServerName`. Once the first fault applies,
all later faults must be on the **same raw Master and manager**. The agent
throws the selected `KeeperException` at the `ZKUtil` method entry and logs
each application; an unmatched step cannot be counted as applied. This
models a high-level API failure, which can bypass retries inside that API.
No fault plan has been exercised yet.

The cross-run plan selector uses the observed role, I/O family, path,
call site, and per-watcher ordinal. A candidate is target-retaining only if
its postfault target receipt has the **same raw Master `ServerName` and
manager ID** as the injected event within that run. A healthy seed must show
that the chosen role selector uniquely selects the intended Master in the
two-master test before enabling any fault. If the active Master changes, the
new Master is a different actor and cannot satisfy this same-actor check.
The default run is passive; a fresh V2 checkpoint can use the optional fault
mode only after two original healthy seeds validate stable role selection.
The old HBASE-08/21/22 coverage results remain historical and must not be
imported into a new V2 denominator.

## Offline checks

- Java 8 `javac` compiled `src/NamespaceActorAgent.java` and
  `src/NamespaceActorSmoke.java` against the release distribution.
- `NamespaceActorSmoke` loaded all five instrumented classes with the agent;
  no ByteBuddy transform error appeared. It started no HBase or ZooKeeper
  cluster.
- ByteBuddy's class dump contains transformed `ZKWatcher`,
  `ZKNamespaceManager`, `ZKUtil`, `ClusterSchemaServiceImpl`, and
  `NamespaceStateManager`. `javap` confirmed constructor advice in the
  transformed `ZKWatcher`. `ZKWatcher` needs retransformation because the
  agent's own type references cause it to load before the transformer is
  installed.

The agent source SHA-256 is
`705d653a5aa51e4f9c1cff01185ff3b42aee4d9f920ca10c680fb7139e03b8db`.
`bash run.sh build` regenerates the small local agent JAR; its timestamped
archive bytes can differ between builds, so each cluster seed should record
the JAR's SHA-256 in that seed's manifest.
The unchanged server and test JAR SHA-256 values are
`27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696`
and `b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5`.

Before running a cluster seed, capture a fresh scratch directory and Java
agent output for each case. Verify actor and manager binding in at least two
healthy repetitions, actual pre-target I/O families, source-specific target
arguments, and unchanged JUnit pass. HBASE-22's selected predicate is at
source lines 165–167; checklist line 172 belongs to its exception message.
