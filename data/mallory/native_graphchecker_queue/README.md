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
`elapsed_seconds` for a verified row is the sum of the original native trial
receipts, including the healthy run. `elapsed_basis` records what those
receipts actually timed. Current native receipts include JUnit execution and
per-trial original graph analysis; they exclude one-time static analysis,
recording, weave, and other setup. Legacy ZOOKEEPER-07 receipts predate total
trial timing and count JUnit execution only: its 65 reported trial times sum
to 648.415 seconds, matching its checkpoint and completion receipt. They do
not include graph analysis. The exporter verifies this basis from each
campaign's immutable trial result receipts.

`target_exception_candidate` means the native campaign observed an exact
target exception with its required trial evidence. It does not assert a new
bug. `confirmed_new_bug` remains null until independent source-level review
provides that conclusion.

The committed v2 snapshot has 102 rows and four verified terminal imports:
ZOOKEEPER-07, HDFS-11, HDFS-29, and SOLR-01. The remaining four bound
campaigns show checkpoint observations without a terminal receipt. HDFS-11's
separate terminal review records incomplete SASL value provenance. HDFS-29
finished its fault budget without an exact target throw. SOLR-01 has a
client-only static map with no proven server receive edge; its completed
budget also has no exact target throw. A completed budget counts as tested
without treating graph novelty or a target exception as established.
`strict_in_target_closure_trials` is audited against each original native
trial graph and stays separate from target retention. Coverage sidecars pin
the trial files used for that count.

`promotion-v2.json` and `promotion-v2-manifest.json` record the initial
two-completion promotion. The later terminal rows are pinned by their
completion receipts, coverage sidecars, and this snapshot.

These files are distinct from the earlier custom/preliminary
`data/mallory/graphchecker_port/final-results.tsv` and never read that table.

Regenerate from the promoted durable queue state:

```bash
python3 - <<'PY'
from pathlib import Path
from Mallory.native_graphchecker_queue.results import export_native_results
b = Path('/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2')
export_native_results(b / 'python-snapshot-closure-v1/Mallory/cases/inventory.json',
    b / 'config/ownership.json', b / 'config', b / 'state',
    Path('data/mallory/native_graphchecker_queue'))
PY
```
