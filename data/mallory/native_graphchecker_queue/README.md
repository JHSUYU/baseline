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

The committed snapshot has 102 rows and thirteen verified terminal imports:
ZOOKEEPER-01, ZOOKEEPER-02, ZOOKEEPER-07, HDFS-11, HDFS-28, HDFS-29,
HDFS-30, HDFS-31,
HBASE-01, HBASE-02, SOLR-01, SOLR-05, and SOLR-07. Active bound campaigns
show checkpoint observations without a terminal receipt. HDFS-11's
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

HBASE-01 finished 19 strict target-retained fault trials in 3769.085
cumulative seconds with no exact target throw. Its source lineage receipt
pins the GraphChecker executor overlay outside the target method and matches
the inventory target source and normalized target-method instructions. Its
healthy graph mapped no edge families despite 258 paired exchanges, so the
result does not establish causal closure. SOLR-07 finished 24 fault trials
in 1884.160 cumulative seconds: 10 strict target-retained, 14 unmatched,
and no exact target throw. Its generated RPC port had 415 exports and zero
imports, leaving a cross-process receive edge unproven. Both elapsed sums
include JUnit and per-trial graph analysis.

SOLR-05 finished 51 fault trials in 3648.371 cumulative seconds: 22 strict
injections, 16 strict target-retained, 29 unmatched, six target-lost, and no
exact target throw. Five of 16 retained faults meet the recorded target
closure proxy, while its static manifest has no communicationPorts; no
cross-process receive edge is proven.

HDFS-31 finished its 64-trial budget in 2110.928 cumulative seconds: 63
strict injections, 30 strict target-retained, 33 target-lost, one unmatched,
and no exact target throw or graph novelty. Its source review records 2578.0
seconds of campaign wall time. HDFS-28 finished its time budget after 56
trials and 3679.792 cumulative seconds: 46 strict injections, 31 strict
target-retained, 15 target-lost, ten unmatched, and zero strict target
throws. One exact IOException THROW occurred in unmatched r0029 after only
two of three planned faults during MiniDFSCluster teardown while JUnit
passed. That receipt is preserved separately; it is not a strict candidate
or confirmed bug.

For the eight earlier exact-ID-audited terminal rows,
`strict_in_target_closure_trials` counts strict
target-retained trials whose **last applied fault occurrence ID** belongs to
the target-selected original Finalizer plan. The exporter validates each
frozen plan and fault-event SHA against a pinned read-only audit, its method,
the original GraphChecker ID helper and engine JAR, and a combined audit
index. `closure_attribution_basis` states the exact-ID method. The older
REGION_STATE same-occurrence proxy for those eight is retained only in their
coverage sidecars;
it gave wrong counts in both directions (HDFS-11: 5 to 0; ZOOKEEPER-01: 0
to 32). Plan membership does not establish temporal causality or an exact
target throw. All eight reviewed terminal campaigns remain without a
confirmed new bug. Native `closureEdgeFamilies` are not interpreted as
target-reachable edge families in this table.
HBASE-01, HDFS-28, HDFS-31, SOLR-05, and SOLR-07 retain the explicitly labelled REGION_STATE
same-occurrence proxy until an exact-ID frozen-evidence audit is pinned;
their proxy counts do not establish causal closure.

SOLR-19, ZOOKEEPER-03, and ZOOKEEPER-05 are bound to active direct campaigns
with immutable configs and isolated states. SOLR-19's original healthy JUnit
passed and retained its exact target before read-only binding. ZOOKEEPER-05
v5 is the bound campaign; its earlier v3/v4 blocked states remain separate.
The queue must honor their direct campaign locks until those processes finish.
`promotion-v2.json` and `promotion-v2-manifest.json` record the initial
two-completion promotion. Later rows are pinned by completion receipts,
coverage sidecars, review pins, and this snapshot.
`promotion-bind-v1.json` and `promotion-bind-v1-manifest.json` pin an earlier
handoff. `promotion-bind-v4.json` and its manifest pin the eight-completion
successor and exact-ID audit index. `promotion-bind-v5.json` pins the fifteen
bindings, ten completions, v5 launcher, and HBase source lineage at the
previous handoff. `promotion-bind-v6.json` pins the eleventh completion;
`promotion-bind-v7.json` pins both HDFS terminal reviews. The current
`promotion-bind-v8.json` pins the SOLR-19 active binding, ownership, port
profile, and this result snapshot.

For a newly prepared case, run the one-command promoter on its physical owner
host after the immutable native config, healthy target gate, and port review
are ready. It verifies the inventory throw site, native config SHA, port
source digests, existing checkpoint identity, and queue pilot before writing
the binding. It then runs one two-slot host wave, which skips held direct
campaign locks and completed receipts. Use `--bind-only` while another case on
that host awaits an independent terminal audit; then run `run-host-once.sh`
after the audit is pinned. The active ZOOKEEPER-05 v5 binding can be verified again with:

```bash
PYTHONPATH=/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2/python-snapshot-bind-v5 \
python3 -m Mallory.native_graphchecker_queue.bind_and_run \
  --case-id ZOOKEEPER-05 --host node0 \
  --native-config /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-05-20261014-native-prep-v1/config/case-region-state-frontier-v5.json \
  --native-state /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-05-20261014-native-prep-v1/state/formal-region-v5 \
  --campaign-python-root /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-05-20261014-native-prep-v1/inputs/campaign-python-v2 \
  --campaign-python-tar /proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-05-20261014-native-prep-v1/inputs/campaign-python-v2-source.tar \
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
cd /proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2/python-snapshot-bind-v5
python3 - <<'PY'
from pathlib import Path
from Mallory.native_graphchecker_queue.results import export_native_results
b = Path('/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2')
export_native_results(b / 'python-snapshot-bind-v5/Mallory/cases/inventory.json',
    b / 'config/ownership.json', b / 'config', b / 'state',
    b / 'results')
PY
```
