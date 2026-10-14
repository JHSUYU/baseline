# Inventory-driven native Solr preparation

`prepare_case.py` prepares an eligible `SOLR-*` row in `Mallory/cases/inventory.json` for the **source-built original GraphChecker** path. It selects the original JUnit class and method, branch/throw lines, and exception from the inventory. It does not declare a case-specific fault site. One Solr-wide I/O method policy is intersected with the methods selected by the original static analyzer; the resulting manifest supplies the exact typed doors. The pinned native Solr protocol mapping supplies cross-thread/transport hooks and is passed to both static analysis and `REGION_STATE` weaving.

The three preparation phases do not run a campaign or modify an active one:

1. `scope` verifies the selected target and unchanged JUnit sources plus the pinned native protocol patch, checks the supplied compiled class tree and ordered classpath, and emits `static-input.json` and `run_static.sh`. It records SHA-256 fingerprints of the first target and JUnit classes resolved from that classpath; later phases reject changed class bytes. Run the script to produce the original static scope and manifest. The class tree must be the first entry in the ordered classpath, and the original JUnit class must occur later in it.
2. `weave` verifies the manifest's **unique** branch/throw pair and typed doors, copies the original static sidecars into a new immutable recording directory, and emits a `REGION_STATE` weave config, an unchanged JUnit healthy-run script, and an original Recorder/Scheduler script. It never supplies a hand-written concolic task or I/O site. Run these scripts in order. The healthy script uses a no-fault plan, fresh trace directory, and the selected JUnit. The Recorder/Scheduler script uses `--target-occurrence first` as the same generic policy for every case; an ambiguous decider is an error. Its command runner writes receipts only after each original JVM exits successfully, pinning the executed argv, script/helper source, and logs. `--analysis-heap-mb` sets the Recorder/Scheduler heap; the campaign may use a different heap without changing the graph result.
3. `campaign` requires a passing original JUnit result, a closed healthy trace that reaches the exact target branch, one original Scheduler target task, the same static sidecars, and the `REGION_STATE` weave receipt. It emits `campaign-config.json` and `run_campaign.sh`. With both executed command receipts, it seals a `precomputed-schedule.json`; admission verifies the exact CLOSED trace, inputs, engine, JVM arguments, source commands, and output bytes before reusing the schedule. Successful preparation is not an admission or bug finding.

Older Solr preparations without the executed command receipts still rerun
Recorder/Scheduler at admission. Do not infer a receipt from an existing plan.
`region_state_no_schedule` campaigns already skip scheduled admission;
their fresh `r0000` graph remains required.

A typical invocation, with all paths on one host, is:

```bash
python3 -m Mallory.adapters.solr.native_graphchecker_port.prepare_case scope \
  --case-id SOLR-05 --source /pinned/native-patched-solr \
  --class-tree /pinned/selected-solr-classes \
  --classpath-file /pinned/ordered-static-classpath.txt \
  --planner-jar /pinned/mallory-static-scope.jar \
  --planner-deps /pinned/static-dependencies.txt \
  --java /usr/lib/jvm/java-8-openjdk-amd64/bin/java \
  --output /new/solr05/static-prep
/new/solr05/static-prep/run_static.sh

python3 -m Mallory.adapters.solr.native_graphchecker_port.prepare_case weave \
  --case-id SOLR-05 --source /pinned/native-patched-solr \
  --static-input /new/solr05/static-prep/static-input.json \
  --static-output /new/solr05/static-prep/static \
  --sidecars /new/solr05/static-prep/original \
  --adapter-jar /pinned/native-fault-adapter.jar \
  --engine-root /pinned/source-built-original-engine \
  --runner-classpath-file /pinned/ordered-runtime-classpath.txt \
  --java /usr/lib/jvm/java-8-openjdk-amd64/bin/java \
  --output /new/solr05/native-prep
/new/solr05/native-prep/run_region_state_weave.sh
/new/solr05/native-prep/run_healthy_original_junit.sh
/new/solr05/native-prep/run_original_recorder_scheduler.sh

python3 -m Mallory.adapters.solr.native_graphchecker_port.prepare_case campaign \
  --case-id SOLR-05 --source /pinned/native-patched-solr \
  --static-input /new/solr05/static-prep/static-input.json \
  --static-output /new/solr05/static-prep/static \
  --sidecars /new/solr05/native-prep/recording-artifacts \
  --trace-dir /new/solr05/native-prep/healthy/trace \
  --junit-result-log /new/solr05/native-prep/healthy/junit.stdout.log \
  --schedule-index /new/solr05/native-prep/healthy/scheduled/runtime_workflow_schedule_index.json \
  --schedule-plan /new/solr05/native-prep/healthy/scheduled/execution_task_plan.jsonl \
  --weave-config /new/solr05/native-prep/native-weave-config.json \
  --runner-classpath-file /pinned/ordered-runtime-classpath.txt \
  --engine-root /pinned/source-built-original-engine \
  --java /usr/lib/jvm/java-8-openjdk-amd64/bin/java \
  --output /new/solr05/campaign-prep
```

The runtime classpath file begins with the **future woven directory**, followed by the native Solr overlay/runner, source-built engine, compiled original test, and ordered dependencies. Its order is checked again at campaign preparation. Generated files are write-once: a changed input requires a new output root. The default campaign budget is 64 fault trials, 1,800 cumulative JUnit seconds, and at most four faults per trial.

## Frozen-artifact validation

The adapter read the unchanged SOLR-01 static/healthy/scheduled artifacts: 305 regions, 32 typed doors, 15 observed target branches, and one original Scheduler target task. It also read the SOLR-05 559-class static and healthy artifacts on node1: 1,564 regions, 287 typed doors, and 9 observed target branches. The canonical native-patched Solr source at `/proj/silentfailure-PG0/mallory/solr-native-e27f44e` passed the inventory target/JUnit and native protocol source checks for SOLR-05. These are read-only validation of existing artifacts; the new generic Solr-wide I/O policy has not yet regenerated either static scope. An earlier SOLR-05 Scheduler run reported eight ambiguous target guard deciders; the separate generic Scheduler fix needs a new source-built engine pin and fresh schedule before this preparer can admit that case. This preparer does not select a decider by hand.

Run the local regression tests with `python3 -m unittest Mallory.adapters.solr.native_graphchecker_port.test_prepare_case Mallory.adapters.solr.native_graphchecker_port.test_executed_schedule Mallory.native_graphchecker_campaign.test_precomputed_schedule -v`.
