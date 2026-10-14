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
Where a pinned terminal review reports them, `reviewed_campaign_wall_seconds`
and `reviewed_static_to_terminal_wall_seconds` preserve separate wall clocks.
For HDFS-30 those are 2166.528 and 3124.749 seconds, respectively, compared
with 1862.14 seconds of cumulative healthy and fault trial execution plus
per-trial graph analysis. The exporter checks the review's cumulative trial
time against the original trial receipts before exposing either wall value.

`target_exception_candidate` means the native campaign observed an exact
target exception with its required trial evidence. It does not assert a new
bug. `confirmed_new_bug` remains null until independent source-level review
provides that conclusion.

The committed snapshot has 102 rows and eight verified terminal imports:
ZOOKEEPER-01, ZOOKEEPER-02, ZOOKEEPER-07, HDFS-11, HDFS-29, HDFS-30,
HBASE-02, and SOLR-01. Active bound campaigns show checkpoint observations
without a terminal receipt. HDFS-11's
separate terminal review records incomplete SASL value provenance. HDFS-29
finished its fault budget without an exact target throw. SOLR-01 has a
client-only static map with no proven server receive edge; its completed
budget also has no exact target throw. A completed budget counts as tested
without treating graph novelty or a target exception as established.
HBASE-02 finished 16 attempts with 11 valid checked strict target-retained
trials and no exact target throw. Its Recorder timed out in r0016, which is
excluded from valid checked counts; the healthy graph mapped no edge or
closure families despite 256 paired exchanges. The source-backed u8 guard to
u17 throw identity and terminal quality review are pinned separately.

For these eight terminal rows, `strict_in_target_closure_trials` counts strict
target-retained trials whose **last applied fault occurrence ID** belongs to
the target-selected original Finalizer plan. The exporter validates each
frozen plan and fault-event SHA against a pinned read-only audit, its method,
the original GraphChecker ID helper and engine JAR, and a combined audit
index. `closure_attribution_basis` states the exact-ID method. The older
REGION_STATE same-occurrence proxy is retained only in the coverage sidecar;
it gave wrong counts in both directions (HDFS-11: 5 to 0; ZOOKEEPER-01: 0
to 32). Plan membership does not establish temporal causality or an exact
target throw. All eight reviewed terminal campaigns remain without a
confirmed new bug. Native `closureEdgeFamilies` are not interpreted as
target-reachable edge families in this table.

HBASE-01 and SOLR-05 are bound to active direct campaigns on node2 and node1,
respectively, with pinned case-scoped source reviews of their port policies.
HDFS-28 is bound to an active direct campaign on node0 with its separate
immutable campaign Python source, config, engine, and port source/runtime gate.
The queue must honor their direct campaign locks until those processes finish.
`promotion-v2.json` and `promotion-v2-manifest.json` record the initial
two-completion promotion. Later rows are pinned by completion receipts,
coverage sidecars, review pins, and this snapshot.
`promotion-bind-v1.json` and `promotion-bind-v1-manifest.json` pin the current
ten bindings, five completions, source archive, launch code, and result digest
at the previous handoff. `promotion-bind-v4.json` and its manifest pin the
eight-completion successor, exact-ID audit index, and current launcher.

For a newly prepared case, run the one-command promoter on its physical owner
host after the immutable native config, healthy target gate, and port review
are ready. It verifies the inventory throw site, native config SHA, port
source digests, existing checkpoint identity, and queue pilot before writing
the binding. It then runs one two-slot host wave, which skips held direct
campaign locks and completed receipts. Use `--bind-only` while another case on
that host awaits an independent terminal audit; then run `run-host-once.sh`
after the audit is pinned. The HBASE-01 binding can be verified again with:

```bash
PYTHONPATH=/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2/python-snapshot-bind-v4 \
python3 -m Mallory.native_graphchecker_queue.bind_and_run \
  --case-id HBASE-01 --host node2 \
  --native-config /proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-01-20261014-native-v5/campaign-config.json \
  --native-state /proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-01-20261014-native-v5/campaign \
  --port-review /proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-01-20261014-native-v5/port-review.json \
  --bind-only
```

The HDFS-29 inventory identity audit references a node0-local source file.
Cross-host exporters verify its exact source SHA against a shared source
archive receipt under the durable queue root if that original path is absent.
If the original path exists but changes, the export fails.

These files are distinct from the earlier custom/preliminary
`data/mallory/graphchecker_port/final-results.tsv` and never read that table.

Regenerate from the promoted durable queue state:

```bash
cd /proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2/python-snapshot-bind-v4
python3 - <<'PY'
from pathlib import Path
from Mallory.native_graphchecker_queue.results import export_native_results
b = Path('/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2')
export_native_results(b / 'python-snapshot-bind-v4/Mallory/cases/inventory.json',
    b / 'config/ownership.json', b / 'config', b / 'state',
    b / 'results')
PY
```
