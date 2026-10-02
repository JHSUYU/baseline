# Target-guided CrashFuzz baseline

This is a new implementation under `baseline/crashfuzz`. It does not execute
GraphChecker or import its graph files. It borrows the idea of starting at one
target check and expanding a causal graph as faulted executions expose new
behavior. CrashFuzz's one-fault-at-a-time mutation and crash/reboot constraints
inspired the search loop. The event protocol, graph builder, controller,
scheduler, and Java 8 probe here are independent code.

Each node must be a separate JVM process. The first cluster driver uses Docker
CLI (`docker stop` / `docker start`); Compose is not required. A `prepare`
command recreates a known initial cluster and runs once per trial. Container
volumes persist **within** a trial across stop/start, while `prepare` resets
them **between** trials. The probe writes into a host-mounted per-run trace
directory.

## Implemented path

```text
configured target check + real workload
  -> Java 8 probe: methods, fields, branches, basic blocks, I/O points, handoffs
  -> Docker controller: exact fault-point match, crash/reboot, journal
  -> per-run graph: CALL/RETURN, STATE_CANDIDATE, ASYNC, MESSAGE
  -> target backward closure -> novel node/edge/block/branch features
  -> broad basic-block and conditional-branch coverage -> exploration feedback
  -> one-more-fault mutation -> next trial
  -> fatal target in a concrete run -> replay and report
```

The generic graph builder never assumes a lease, commit, leader, or other
protocol name. A `MESSAGE` edge requires the same unambiguous correlation key
at its send and receive endpoints. System adapters may call
`org.greygraph.baseline.agent.Hook.messageSend(String)` and
`Hook.messageReceive(String)` at a transport's real boundaries. A bare RPC
call ID is insufficient if it can be reused on different connections; the
adapter must include a connection or attempt identity. Missing or duplicate
producers are recorded as gaps, not guessed edges.

Plain Java field probes record the field and the exact object identity within
one process. They cannot establish which concurrent write a read observed, so
the graph labels the most recent recorded write as `STATE_CANDIDATE`. An adapter
that supplies `state_version` and `observed_version` can create an exact
`STATE` edge. Graph growth guides search; only the target check in a concrete
run is a candidate finding.

## Build and verify

```bash
cd /users/ZhenyuLi/baseline/crashfuzz/agent
mvn -q -DskipTests package
cd ..
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m adhoc_crashfuzz.cli inspect \
  --trace-dir /path/to/one-run/traces --target-site 'class#method(desc)#B3'
```

The tests include a Java 8 agent smoke test and a simulated two-node campaign
that generates a crash from a fault-free seed, observes the target, and replays
the sequence. They do not substitute for a Docker/HBase cluster run.

`examples/tiny_docker` is an additional real two-container integration
fixture. In this workspace it completed 8 search runs, found a `BEFORE`-write
crash whose target check fired, and reproduced it once. The healthy run's
target closure contained both request and response `MESSAGE` edges. This
validates the Docker execution path, but it is not an HBase evaluation.

## Probe configuration

Run each node JVM with
`-javaagent:/path/to/adhoc-crashfuzz-agent-0.1.0.jar=/path/to/agent.properties`.
The JAR is produced by Maven above. A minimal `agent.properties` is:

```properties
include.prefixes=org/apache/hadoop/hbase/
node.id=rs1
trace.dir=/mounted/host/run/traces
controller.host=host.docker.internal
io.rules=java/io/FileOutputStream#write,java/nio/channels/SocketChannel#write
trace.fields=true
trace.branches=false
coverage.blocks=true
coverage.branches=true
coverage.include.prefixes=org/apache/hadoop/hbase/
target.guard=org/apache/.../TargetClass#method(Descriptor)#B3
target.throw=org/apache/.../TargetClass#method(Descriptor)#L123
```

`include.prefixes` selects application packages; `include.classes` selects
exact classes, and `method.rules` can narrow the methods woven in each class.
`coverage.blocks=true` adds stable `#BB<n>` probes to those detailed methods.
`coverage.include.prefixes` also collects first-hit basic blocks and conditional
branch outcomes in other classes under those prefixes without adding their
methods to the causal graph. Detailed `BLOCK` and `BRANCH` events carry the
current method span; only those events can be attributed to a target closure.
The broad coverage-only events guide exploration but do not establish a causal
edge to the target. Current branch coverage covers conditional JVM jumps;
switch arms and exception edges are not yet counted as branch outcomes.
`io.rules` matches callee owner and method at call sites; a trailing `*` is a
prefix wildcard. It can select I/O calls or declared coordination boundaries.
Each selected call reports `BEFORE` and `AFTER` fault points. The probe fsyncs its
trace before asking the controller to act, retaining the crash prefix. The
controller freezes matching when the workload returns. The later checker
cannot inject a fault, and its JVM events do not contribute search coverage.
The controller's advertised host and port can also come from
`ADHOCFUZZ_CONTROLLER_HOST` and `ADHOCFUZZ_CONTROLLER_PORT`; a cluster setup
script should pass the dynamically chosen port from the campaign. Leave
`controller.port` out of the properties file when using a dynamic port.

With `trace.branches=true` in a discovery run, branch IDs appear as
`class#method(descriptor)#B<n>`. Configure the target guard and the source-line
throw site from that **same compiled build**. With both properties set, the
guard's healthy evaluation records `TARGET fatal=false`, and the actual throw
records `TARGET fatal=true`. The `target.site` in the campaign config must be
the guard site. If a target cannot be represented as a direct throw, an adapter
can call `Hook.target(site, boolean)` at its check. Rebuilding the application
can move branch IDs; do not reuse a campaign configuration across bytecode
revisions without checking them.

The current automatic async hook covers `Thread.start()` and single-argument
`execute(Runnable)` / `submit(Runnable|Callable)` call sites in included
classes. The HBase 2.4.8 adapter also correlates Netty RPCs by client endpoint
and call ID, and follows CallRunner and procedure-object handoffs. Other
transports need similar adapters; the graph builder itself is system
independent.

## Campaign configuration

Create a JSON file like this, with a setup script that creates named
containers and mounts `ADHOCFUZZ_RUN_DIR/traces` into each instrumented JVM:

```json
{
  "target": {"site": "org/apache/.../TargetClass#method(Descriptor)#B3"},
  "output_dir": "out",
  "controller": {"bind": "0.0.0.0", "advertise": "host.docker.internal", "port": 0},
  "roles": {"hm1": "master", "hm2": "master", "rs1": "regionserver",
            "rs2": "regionserver", "rs3": "regionserver"},
  "node_groups": [
    {"members": ["hm1", "hm2"], "max_down": 1},
    {"members": ["rs1", "rs2", "rs3"], "max_down": 2}
  ],
  "docker": {
    "command": ["sudo", "-n", "docker"],
    "containers": {"hm1": "example-hm1", "hm2": "example-hm2",
                   "rs1": "example-rs1", "rs2": "example-rs2",
                   "rs3": "example-rs3"},
    "prepare": ["./prepare-cluster.sh"],
    "workload": ["./run-workload.sh"],
    "checker": ["./check-cluster.sh"],
    "workload_timeout_s": 300
  },
  "search": {"max_runs": 100, "max_faults": 6,
             "max_candidates_per_run": 300,
             "exploration_probability": 0.15, "replay_count": 2}
}
```

Then run `PYTHONPATH=src python3 -m adhoc_crashfuzz.cli run --config
/path/to/campaign.json`. The `prepare` script receives the absolute run
directory and controller address as environment variables. The workload and
checker scripts receive `ADHOCFUZZ_RUN_DIR`. Commands are argument arrays;
the runner never invokes a shell implicitly.

The target should be reached by the fault-free workload, even though its fatal
branch should not be taken. When a planned point does not recur, the trial is
recorded as untriggered; it does not become a bug or contribute graph coverage.
The controller journal contains every observed point and the actual fault
orders. A fatal target is replayed `replay_count` times, with each outcome
saved separately.

## Current integration limits

- The Docker daemon is available through `sudo -n docker` in this workspace.
  The two-container fixture passed. A real HBase 2.4.8 cluster with two
  masters, three RegionServers, HDFS, and ZooKeeper completed a healthy
  truncate seed and a precisely injected active-Master crash. The backup
  Master completed the operation; the target fatal check did not fire.
- The HBase seed's target closure contained 21 occurrences and 37 edges,
  including one RPC edge and two cross-thread handoffs. Recovery from the
  Master crash reloads procedure state from HDFS; that durable dependency is
  not yet connected across processes in the graph. The cloned
  `JHSUYU/hbase` master targets Java 17, so the first Java 8 run uses a
  separate `rel/2.4.8` worktree.
- HDFS has targeted workloads and a fifty-candidate audit under
  `examples/hdfs_random50/`. Solr and ZooKeeper still need cluster adapters
  and validated target workloads. The HBase adapter is pinned to the tested
  2.4.8 bytecode.
- The current target report is a concrete candidate plus replay results.
  Automated sequence minimization and exact concurrent field read-from
  require additional implementation.
