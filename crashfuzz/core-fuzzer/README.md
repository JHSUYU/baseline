# Soot-selected CrashFuzz runner

`rerun102_worker.py` is the entry point for the current checklist campaign.
Each row in `data/crashfuzz/checklist102.json` identifies an exact target
check and an unchanged cluster JUnit method. The row does not declare I/O
fault sites or coverage sites.

## Execution path

1. `prepare_case_selection.py` locates the system binaries and shared RPC
   mappings. `soot_selection.py` invokes `static-selection/` to select a
   bounded set of methods, branches, typed throw sites and I/O callsites
   around the target. The selection is saved as `soot-selection.json`.
2. The system-specific `original_*_junit.py` runner starts the original
   embedded-cluster JUnit with the ASM agent from `runtime-agent/`. A healthy
   run records the selected I/O, target, and method/branch coverage events.
   If no replayable I/O appears, the worker widens the Soot selection and
   repeats the healthy run before reporting a setup limitation.
3. `fuzzer.py` builds ordered fault plans from *observed* selected I/O. Each
   trial reruns the same JUnit in fresh scratch storage. Runtime matching
   includes the I/O site, call phase, normalized actor/node identity, and
   invocation ordinal. Both pre-call exceptions and lost synchronous RPC
   replies are supported where the Soot selection permits them.
4. New selected I/O and method/branch outcomes guide sequence mutation and
   priority. A matched injection, post-fault target reach, exact target throw,
   and JUnit exit are recorded separately. An observed target exception is a
   review candidate; source and trace evidence determine whether a fault
   actually caused it.

No graph, manually listed per-check I/O sites, or modified workload is needed.
The worker preserves the selection, healthy trace, fault plans, attempt logs,
coverage feedback, and atomic checkpoint under its result root. Resuming a
case uses its existing checkpoint and does not repeat completed trials.

## Build and run

```sh
mvn -q -f crashfuzz/static-selection/pom.xml package
mvn -q -f crashfuzz/runtime-agent/pom.xml package
cd crashfuzz/core-fuzzer
python3 rerun102_worker.py \
  --system HDFS \
  --checklist ../../data/crashfuzz/checklist102.json \
  --result-root /path/to/isolated-results \
  --case-id HDFS-01 \
  --max-trials 240 --max-faults 10
```

`--system` accepts `HDFS`, `HBase`, `Solr`, or `ZooKeeper`. Repeat `--case-id`
for selected rows, or omit it to run a system's checklist. Independent
workers can use `--shard-index` and `--shard-count`; keep their result roots
isolated. The source and binary paths configured in `prepare_case_selection.py`
and the four `original_*_junit.py` runners must be available on the worker.
The HBase runner uses the retained JUnit Platform launcher JAR in
`crashfuzz/vendor/`.

The default budget is 80 base trials, at most 240 trials, and at most 10
faults per plan. A campaign continues beyond 80 trials while trying to obtain
30 strict post-fault target reaches, subject to the 240-trial cap. A worker
that cannot find an original cluster JUnit marks the row `no_cluster_test`.

`audit_rerun102_selection.py --result-root /path/to/isolated-results` checks
that the target and I/O sites came from the saved Soot artifact and that the
healthy JVM used the same selection digest. `collect_rerun102.py` merges
per-case summaries into `data/crashfuzz/static102-rerun.tsv`. The table and
source reviews under `data/crashfuzz/` are the committed research record.

`fuzzer.py <campaign-config.json> --root <campaign-root>` runs or resumes one
already prepared case. The worker writes that config as
`<result-root>/<case-id>/campaign-config.json`; the selected JUnit and
selection artifact are included there. Each trial's `result.json`, fault
selector, and archived trace provide the evidence needed to inspect its
outcome.
