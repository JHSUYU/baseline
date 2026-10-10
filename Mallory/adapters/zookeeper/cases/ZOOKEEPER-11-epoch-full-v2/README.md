# ZOOKEEPER-11 epoch full stage v2

This independent package retains the v1 healthy seed, target, overlay, agent,
site catalog, and 80 trial / 3600 second / at most 3 faults budget. It uses a
new immutable core release built from controller commit `12018488` and sets
`multi_fault_exploration_interval: 4` explicitly. When a queued multi-fault
plan exists, the scheduler reserves every fourth fault trial for one. The v1
package and the live ZK10 campaign remain unchanged.

The prior ZK11 same-occurrence one-fault pilot lost the target. A passing
healthy seed or exact injection does not establish postfault target retention
or a causal graph path; the offline audit must report those separately. A
selected throw remains a candidate for source and reproduction review.

The no-JVM preflight checks all pins, source and compiled artifacts, the
prior healthy/target-loss evidence, the release manifest, and the budget:

```sh
python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v2/run.py --preflight
```

Only after ZK10 is naturally terminal, its source lock and JVMs are gone,
and disk admission succeeds, start exactly one node0 tmux run:

```sh
MALLORY_ZK11_NODE0_V2_GO=1 python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v2/run.py --run
```

Raw evidence is written to
`data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v2/`. The runner preserves
terminal checkpoints and never starts itself.
