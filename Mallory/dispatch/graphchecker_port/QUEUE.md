# Resumable GraphChecker case queue

`queue.py` is a lane worker for the native GraphChecker Mallory baseline. Run
one worker on each owner host (`node0`, `node1`, or `node2`). Each worker takes
a host `flock` lease and executes one inventory check at a time; independent
hosts can run concurrently. Its default mode is a read-only plan.

```bash
python3 -m Mallory.dispatch.graphchecker_port.queue --manifest /path/to/lane.json
python3 -m unittest Mallory.dispatch.graphchecker_port.test_queue -v
```

Only use `--run` after reviewing the dry run and staging a pinned tool/source
snapshot. A queue started in tmux can be reattached; after the queue process
itself stops, the same command resumes from durable receipts:

```bash
python3 -m Mallory.dispatch.graphchecker_port.queue \
  --manifest /path/to/lane.json --run
```

The queue never invokes Docker. The workload is the inventory-selected
original JUnit cluster test. The system adapters pass the target throw to
Soot; Soot discovers the regions, coverage sites, and fault doors. The queue
does not accept case-specific I/O or fault-site lists.

## Manifest contract

The lane JSON has `schema_version: 1`, `host`, `system`, an absolute
`inventory` and its `inventory_sha256`, durable absolute `state_root` and
`import_root`, `pins` mapping each tool/recipe file to its SHA-256, and one
shared `recipe` for the whole system. Omit `case_ids` to show all inventory
cases of that system; a subset is useful for a pilot. `recipe.steps` has
`kind`, argv array, relative output files, and optional `timeout_seconds`.
Only `{case_id}`, `{prep}`, and `{inventory}` are substituted; the command is
executed directly, without a shell. `config_relative` is the native config
under the unique preparation directory.

The exact phase order and required generated files are:

| System | Step kinds | Native config | Scope outputs to list in `outputs` |
| --- | --- | --- | --- |
| HDFS | `hdfs_scope`, `scope_planner`, `hdfs_campaign` | `case.json` | `scope/weave_manifest.json`, `scope/static_scope_map.jsonl` |
| HBase | `hbase_prepare` | `case.json` | `scope/weave_manifest.json`, `scope/static_scope_map.jsonl` |
| Solr | `solr_scope`, `solr_scope_planner`, `solr_campaign` | `project/config.json` | `scope-output/weave_manifest.json`, `scope-output/static_scope_map.jsonl` |
| ZooKeeper | `zookeeper_prepare` | `campaign-config.json` | `scope/weave_manifest.json`, `scope/static_scope_map.jsonl` |

List each generated scope file in the step that produces it; list the config
in the final step. The HDFS/Solr planner steps run `ScopePlanner` and Solr's
generated `{prep}/run_scope.sh`, respectively. The other steps invoke the
matching system `prepare_case.py` or `prepare_zk_campaign.py` with
`--case-id {case_id}`. Supply the required arguments shown in each adapter's
README. Every absolute recipe input file, analyzer jar, runtime jar, and
weaver jar belongs in `pins`. Build/source directories referenced by these
recipes must be immutable snapshots; the native weave receipt checks selected
original class hashes and adapter hashes again during execution.

For example, the ZooKeeper recipe shape is:

```json
{
  "config_relative": "campaign-config.json",
  "steps": [{
    "kind": "zookeeper_prepare",
    "argv": [
      "python3", "/PINNED/prepare_zk_campaign.py",
      "/PINNED/zookeeper-3.8.7", "{prep}",
      "--case-id", "{case_id}",
      "--scope-jar", "/PINNED/static-scope.jar",
      "--weaver-jar", "/PINNED/weaver.jar",
      "--runtime-jar", "/PINNED/runtime.jar",
      "--analyzer-jar", "/PINNED/analyzer.jar",
      "--adapter-classes", "/PINNED/adapter-classes",
      "--fault-trials", "64", "--seconds", "1800", "--max-faults", "4"
    ],
    "outputs": [
      "scope/weave_manifest.json", "scope/static_scope_map.jsonl",
      "campaign-config.json"
    ]
  }]
}
```

This is a recipe fragment, not a ready deployment: replace `/PINNED` paths,
add the lane fields and hashes, and first run without `--run`.

`existing_campaigns` maps already started case IDs to absolute `config` and
`campaign` paths. A terminal existing campaign is verified through
`import_case.py`; a running one is never taken over. `holds` maps a stopped
case to `{reason, evidence_paths}` so the queue can continue to other cases
without relaunching it. The HDFS-29 v1 and SOLR-05 v1 campaigns require holds
until their raw-target/graph-target attribution gap has been repaired and a
separate v2 config is prepared. `no_suitable_junit` has the same review shape
and records an explicit skip only after source/test evidence supports it.

ZooKeeper's current preparer supports only `ZOOKEEPER-05`, `-06`, `-07`, `-11`,
and `-12`. A ZooKeeper lane must set `adapter_supported_case_ids` to these five
IDs (or an evidence-backed subset). With `case_ids` omitted, the other eight
inventory rows appear as `blocked_unsupported_adapter_case` in the dry run;
they are not silently counted as completed. HBASE-37 currently needs a wider
compiled `hbase-zookeeper` input. Original tests that pass setup but lose raw
`TARGET_CHECK` attribution in the graph are marked
`blocked_healthy_target_attribution`, not sent to target-absent bootstrap.

Set `compact_runtime_trace: true` only for a *new* queue campaign. The queue
verifies the SHA-pinned runtime JAR implements
`mallory.graphchecker.trace.compact`, then adds its `-D...=true` JVM argument
to that case's fresh config before hashing it. It never edits an existing
campaign or frozen runtime pin. Static selection and weave remain once per
case; each fault trial still emits its own compact runtime trace and graph
feedback.

## Durable state and result import

For each check, `state_root/<case-id>/preparations/<uuid>/` contains the
immutable preparation inputs, outputs, step logs, and SHA receipt. A crashed
preparation is left in place and a new UUID attempt starts. The successful
config is never rewritten on resume. Campaign attempts live at
`state_root/<case-id>/campaigns/<uuid>/`; the native core's checkpoint resumes
completed fault trials without repeating them. An incomplete weave attempt
gets a fresh campaign UUID while retaining the old attempt as evidence. The
worker inspects the core lock, checkpoint status, raw healthy trace, and
weave/config identity before resuming. A missing tmux session alone never
authorizes a restart.

A terminal campaign is imported into `import_root/imports/` with
`import_case.py`, which verifies every trial receipt and keeps the full traces
at their source. `state_root/<case-id>/result.json` records the source
location/function/line, original JUnit, per-case trial and dispatch time,
injection/target counts, and candidate count. A reviewed no-JUnit or hold
decision has `review-result.json`. The existing `aggregate.py` can read the
import index to produce the 102-row final table. A case with a terminal
receipt is skipped on subsequent queue runs; interrupted import/result
publication can be recovered from the content-addressed import snapshot.
