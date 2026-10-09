# Static target frontier

This module independently builds a **conservative candidate frontier** for a
declared exception check. It uses Soot 4.4.1 to inspect the compiled classes
used by a cluster-based unit test. It does not import GraphChecker code or
claim that a static edge is an observed causal edge.

Build and run:

```sh
mvn -q test
mvn -q dependency:build-classpath -Dmdep.outputFile=/tmp/mallory-static-cp.txt
java -cp "target/classes:$(cat /tmp/mallory-static-cp.txt)" \
  edu.uva.liftlab.mallory.staticfrontier.StaticFrontier \
  case.json frontier.json
```

Input example:

```json
{
  "case_id": "ZOOKEEPER-01",
  "target": {
    "class": "org.apache.zookeeper.server.SessionTrackerImpl",
    "method": "checkSession",
    "line": 317,
    "exception": "SessionExpiredException",
    "source_file": "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
  },
  "analysis": {
    "process_dirs": ["/absolute/path/to/zookeeper-3.8.7.jar"],
    "classpath": ["/absolute/path/to/zookeeper-3.8.7.jar"],
    "max_call_depth": 3,
    "max_sites": 3000,
    "io_patterns": ["java.io.", "org.apache.zookeeper.server.quorum."]
  }
}
```

`method` may be a method name or full Soot signature. A target must resolve
to exactly one `throw` statement at the declared line and type; ambiguity is
an error. For a multi-line check, optional `line_start` and `line_end` bound
the search interval, while `line` remains the check's selected line. The
resolved throw line is returned. `process_dirs` names jars or class
directories to analyze, while
`classpath` includes their dependencies. Include application jars in
`process_dirs` to find their writers and callers.

The JSON result contains `target`, `frontier`, and `gaps`. Each frontier row
has a method signature, a `site_id`, source line when available, `kind`,
distance, and one or more evidence strings. A bytecode offset is used for
site identity when Soot provides it; otherwise `@jimpleN` denotes the
original Jimple unit index. The `jimple_only_site_ids_require_runtime_bytecode_mapping`
gap tells the runtime integrator that this index cannot be matched by an ASM
probe without a mapping pass.

Evidence classes are intentionally cautious:

* `local_reaching_definition` is a within-method data-flow predecessor.
* `control_postdom_may` is a CFG branch that can decide whether a site runs.
* `field_name_may_writer` is a field assignment or a recognized mutation of a
  container loaded from that field. It does not establish heap object or key
  identity.
* `call_return_may` and `activation_call_may` are interprocedural candidates.
* `caught_call_may` marks calls inside a trap that may lead to a selected
  handler; it does not establish which exceptions they can throw.
* `io_api_match_in_selected_method` is an I/O candidate in a selected
  method, not proof that the I/O affects the target.

The `gaps` list names unresolved dispatch, unavailable bodies, missing
writers, depth cuts, and site budget cuts. Runtime identity matching and
observed read/write or send/receive pairing belong to separate modules.
