# HBASE-23 repeated real-procedure MiniCluster workload

HBASE-23 is the PB-magic guard in `ZKProcedureCoordinator.sendGlobalBarrierReached`
at source line 127 (throw at 131). The unmodified
`TestProcedureManager#testSimpleProcedureManager` starts a two-RegionServer
MiniCluster and executes one distributed procedure. It reached the exact,
nonthrowing check once in archived v13; later passing seeds and typed-read
attempts 1–3 entered the method but missed the check. The coordinator creates
the reached parent and immediately scans each member. If a member writes its
completion child after that scan, the distinct `nodeCreated` callback handles
the bytes. Thus a passing JUnit with no line-127 event is a timing miss, not
proof that the selected check is absent from the system.

This overlay changes only that existing test method. It executes 16 sequential
`Admin.execProcedureWithReturn` calls, with distinct `mytest-0` through
`mytest-15` instance names, and checks each return value. It preserves the
real Master, two RegionServers, ZooKeeper procedure implementation, and
production HBase bytecode. Sixteen operations increase the opportunities for
the member completion child to precede the coordinator's synchronous scan;
they do not guarantee that ordering. If the exact check is still absent, the
healthy attempt remains inconclusive.

The Java 8 compiled overlay shadows only `TestProcedureManager.class` at the
front of the JUnit classpath. The frozen `fa5f` Mallory core, future-handoff
adapter, selected target and typed `RecoverableZooKeeper.getData@405` door are
the same as in `hbase23-zk-read-admission-v1`. The healthy verifier requires a
passing JUnit, named exact target, a matched procedure submission and worker
claim token, and an observed same-thread, same-occurrence typed read before
the target. It reports local timeline evidence separately from graph edges.
The target guard's malformed-PB exception is a candidate observation and
requires source review before any bug claim.

## Dispatch gate

On node1, after synchronizing this package and the existing lane9 runtime,
run the no-JVM preflight:

```sh
python3 Mallory/adapters/hbase/pilot/hbase23-repeated-procedure-v1/preflight.py --strict-runtime
```

Then, with the node1 HBase lane free, dispatch may run one healthy-only JUnit:

```sh
MALLORY_NODE1_CAPACITY_GRANTED=1 python3 Mallory/adapters/hbase/pilot/hbase23-repeated-procedure-v1/run_healthy.py --attempt 1
```

At most four immutable healthy attempts are supported. The runner holds the
node1 lane lock and refuses another JVM. It writes under
`data/mallory/HBASE-23/healthy/repeated-procedure-v1/attempt-NN/` and starts
zero fault trials. `full.json` is a staged 80-trial, 3600-second, maximum
three-fault configuration. Hold it until a fresh healthy receipt proves the
target, typed door, actor identity, and event-time path; then dispatch can
start a separate full campaign. Existing healthy attempts and v13 remain
archived and are not counted as a completed campaign.

The overlay source, compiled class, jar, production target bytecode, physical
ZooKeeper door, runtime artifacts, and two configurations are SHA-checked by
`preflight.py`. The local static receipt is `stage-preflight.json`. No JVM was
launched while staging this package.
