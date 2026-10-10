# SOLR-39: bounded exact-reference fault pilot

This package stages **one** typed exception trial in `TimeRoutedAliasUpdateProcessorTest#test`, which uses a four-server `MiniSolrCloudCluster`. The selected site is the first `ZkStateReader.AliasesManager.process` watcher `getData` door on physical actor `node2`, epoch 0. It injects `KeeperException.ConnectionLossException` before that call. The trial budget is one fault, one trial, 480 seconds per trial, and 900 seconds total. It makes no new-bug claim.

The sealed healthy archive has SHA-256 `d84c06f6b10af3375c807aab723c3794c7ff66d2b58bfb177bf21ce1298106db`. Its offline audit paired 310 of 310 exact-reference markers and found one source-supported path: watcher door 4593, cache write 4630, constructor read 4849, target read 4867, and exact target check 4870. The healthy JUnit passed. The diagnostic only admits the injection site; it does not predict a postfault result.

`run_node1.py --preflight-only` performs static admission without starting a JVM. It checks the healthy archive, reference audit, fault plan, source and test files, target class, core and agent releases, adapter JAR, and runtime artifact hashes. The printed hashes form the dispatch request in `stage-request.json`. The node1 steward must issue a **fresh GO receipt** containing the same `case_id`, `host`, `mode`, `config_sha256`, `fault_plan_sha256`, `agent_sha256`, `healthy_archive_sha256`, `healthy_review_sha256`, `pins_sha256`, `audit_sha256`, `runner_sha256`, and `intended_output` fields, plus `"go": true` and a nonempty `attempt_id`. A receipt for a prior package cannot start this pilot.

Once dispatch grants GO and reserves the node1 Solr lane, the steward runs:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-fault-node1-v3/run_node1.py --admission-receipt /path/to/dispatch-go.json
```

The runner acquires the Solr lane and source locks, rejects competing JVMs and low disk or memory, and writes under `data/mallory/pilots/SOLR-39-exact-alias-reference-node1-v3`. A completed trial is audited without repeating it. An interrupted trial is archived only after its process group is confirmed dead, then the same plan can be retried.

`fault-audit.json` requires exact typed `FAULT_MATCHED` and `FAULT_APPLIED` receipts on the selected actor, epoch, door ordinal, occurrence, and thread. It then requires a target check **after** the fault and two paired `getAliases` reads by the same request thread and context from the same manager object as the watcher. An exact postfault `TARGET_THROW` in that request is a **candidate for source review**, never an automatically confirmed new bug. If the fault removes the target or the exact object path, the pilot records that loss and stops.

Static controls (no JVM):

```sh
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-offline-v2 -p 'test_*.py' -v
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-fault-node1-v3 -p 'test_*.py' -v
python3 Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-fault-node1-v3/run_node1.py --preflight-only
```
