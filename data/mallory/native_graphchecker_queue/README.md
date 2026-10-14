# Native GraphChecker 102-case results

`native-102-results.json` and `native-102-results.tsv` are deterministic
exports from the original 102-case inventory and **native queue completion
receipts**. The worker refreshes both files by atomic replacement immediately
after a verified case adoption or newly completed native campaign. The JSON
contains the inventory and ownership SHA-256; each verified row includes its
config, checkpoint, summary, and completion receipt paths and digests.

`verified_terminal` means the queue accepted a native completion receipt after
its full original GraphChecker audit. `running_no_terminal_receipt` and
`terminal_awaiting_adoption` preserve observed checkpoint progress separately;
their final fault counts, elapsed time, target throws, and bug marks remain
unset until receipt adoption. `checkpoint_observed_*` fields are preliminary.
`elapsed_seconds` for a verified row is the sum of original native JUnit trial
times, as stated in `elapsed_basis`.

The committed snapshot has 102 rows and one verified terminal import,
ZOOKEEPER-07. HDFS-11 is budget terminal and awaiting queue adoption; its
separate terminal review records 24 trials, 15 strict target-retained trials,
and no new closure-edge families or target throw. This export does not upgrade
that result to a high-quality check or a bug candidate.

These files are distinct from the earlier custom/preliminary
`data/mallory/graphchecker_port/final-results.tsv` and never read that table.

Regenerate from an explicitly selected queue state and binding root:

```bash
python3 - <<'PY'
from pathlib import Path
from Mallory.native_graphchecker_queue.results import export_native_results
export_native_results(
    Path('Mallory/cases/inventory.json'),
    Path('Mallory/native_graphchecker_queue/preflight_existing/native-ownership.draft.json'),
    Path('Mallory/native_graphchecker_queue/preflight_existing/bindings'),
    Path('/proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-native-system-queue-v1/state'),
    Path('data/mallory/native_graphchecker_queue'))
PY
```

The preflight binding/profile paths remain branch-local drafts; use a durable
promotion path for actual worker launch.
