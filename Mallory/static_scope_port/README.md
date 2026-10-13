# GraphChecker-derived static scope for Mallory

`ScopePlanner` runs Soot over the compiled classes used by an original JUnit
cluster test. Its input declares the target check and the application class
paths. It computes a conservative backward candidate scope. The output is a
static **may** relation; only a runtime trace can establish which request,
field version, or message instance reached the target.

Build and run:

```sh
mvn -q test package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
java -Xmx4g -cp "target/classes:$(cat target/classpath.txt)" \
  edu.uva.liftlab.mallory.scope.ScopePlanner input.json output-directory
```

Minimal input:

```json
{
  "case_id": "HDFS-32",
  "target": {
    "class": "org.apache.hadoop.hdfs.server.datanode.DataNode",
    "method": "deleteBlockPool",
    "line": 3822,
    "kind": "THROW",
    "exception": "java.io.IOException",
    "check_line": 3819
  },
  "analysis": {
    "process_dirs": ["/path/to/hadoop-hdfs/target/classes"],
    "classpath": ["/exact/ordered/dependency/classpath:from:WeaveMain"]
  }
}
```

The fatal `THROW` and its controlling `check_line` must each resolve to one
Soot unit. The check branch is the healthy target anchor; the throw is the
exception oracle. For a direct `BRANCH` target, the planner also selects its
unique controlled `THROW` of the configured exception type in the same method.
`target.throw_line` can disambiguate multiple controlled throws; a missing
or ambiguous throw is reported explicitly and is not silently used as an
oracle. Current `Mallory/cases/*.json` can be used when an `analysis` object
is added; their `target.site_id`, `target.source_line`, and
`target.exception_class` are accepted. `analysis.classpath` is the exact
ordered dependency classpath passed to `WeaveMain`; Soot unit indices may
change when resolution context differs. The manifest carries its SHA-256,
which the weaver checks before changing bytecode.

Before any Jimple body is materialized, the planner installs GraphChecker's
original content-derived Soot lambda factory. The source is copied byte for
byte from `original_engine/vendor/src/main/java/edu/uva/liftlab/graphchecker/LambdaClassNames.java`
(SHA-256 `dda375c85351ed2c8f48ed67c33c02109e5b4dccec335280dfaf720aeb9641d8`);
`MalloryLambdaClassNames` is only a public call bridge. This gives synthetic
lambda methods the same names in static region skeletons and the original
GraphChecker weave. The regression test checks the exact source copy and
compares lambda names across independent Soot scenes.

Outputs:

* `static_scope_map.jsonl`: `STATIC_SCOPE_SITE` rows, one per selected
  `(role, site, cell/port)`. Roles are `TARGET_SITE` (the check branch),
  `THROW_SITE` (the fatal oracle), `REGION_SITE`, `READ_SITE`, `WRITE_SITE`,
  `DOOR_SITE`, `EXPORT_SITE`, and `IMPORT_SITE`.
  Every row has `siteId` (`<Soot method>#uN`), `unitIndex` (jtp-entry Jimple
  index), `vmSite`, class/method/descriptor, line, region ID, and guards.
  State rows name a declared field in `cell`; port rows name `portId`.
* `weave_manifest.json`: `regions`, `frames`, `targets`, `coverage`, `doors`,
  `stateCandidates`, and `rpcPorts`. The weave selects target/door/state units
  by the jtp-entry Jimple `unitIndex`; both the branch and throw are targets.
  Door entries carry `exceptionClass`, defaulting to `java.io.IOException`.
  `stateCandidates` request observation;
  they do not assert a read/write version match. A region's `sourceOwner` is
  `CURRENT` by default, or `THIS` when its instance class matches one of
  `analysis.source_owner_classes` regexes and the runtime registered that
  receiver as a node source.
* `analysis.json`: the above together with unresolved-body/field information.

The I/O classifier includes checked `read*` and `write*` operations on
standard Java stream, reader, writer, and data interfaces, including
`BufferedReader.readLine()`. Resource-opening constructors are recognized
as candidate I/O calls, but their fault probes are disabled by default until
the generic weaver validates constructor bytecode for the target JVM. The
planner records `resource_constructor_probe_unverified` gaps for selected
calls. A verified weaver may opt in with
`analysis.constructor_io_doors_verified=true`. The current verified pattern
is `FileReader.<init>(File)`; other constructors remain gaps even with that
flag until their bytecode patterns have a verifier fixture.

Calls inside Mallory or GraphChecker tracing helpers stay in the static MAY
scope when reached, but are excluded from injectable `DOOR_SITE` rows. This
prevents a fault trial from corrupting its own protocol tracing code while
retaining the helper's causal regions and communication hooks.

The worklist follows GraphChecker's seed backward rules for local definitions,
post-dominance guards, field-wide writer jumps, application call results and
effects, formal-to-actual values, activation callers, and standard Java
callback dispatch and executor submissions. Receiver allocation types narrow
virtual-call and callback candidates only when every reaching origin is known;
Soot's generated `bootstrap$` factory for a lambda is one such concrete
origin. Otherwise all type-compatible methods remain. Local field-origin walks stop
on cycles rather than at an arbitrary depth. It treats generated
protobuf message/builder bodies as transport implementation: a call result
still depends on receiver and arguments, and a demanded primitive/String
getter on an RPC-carried message derives a static field port to all matching
builder setter arguments, following GraphChecker's F3 rule. It also recognizes
protobuf RPC service methods with `RpcController` and emits request/response
ports. Static breadth can remain large because field-wide writer jumps are
conservative; the planner does not impose a hidden depth cap.
Callback submissions enter the static MAY scope only. Runtime TASK_SUBMIT/
TASK_CLAIM receipts and child return receipts must still identify the actual
handoff and value return; a selected callback method alone proves neither.
For other transports a **system-wide**, not per-check, mapping can be added:

```json
{
  "analysis": {
    "rpc_mappings": [
      {
        "portId": "system:message-family",
        "transport": "HTTP",
        "sendMethod": "<package\\.Client:.*send\\(",
        "receiveMethod": "<package\\.Server:.*read\\("
      }
    ]
  }
}
```

These regexes select static API callsites only. Protocol adapters still have
to propagate and verify the runtime envelope at the actual send/receive
boundary. Soot cannot infer request identity from a method name, and a plain
field access does not provide a version token. The runtime should report a
missing identity or version as a gap and must not create a causal edge from
the static scope alone.
