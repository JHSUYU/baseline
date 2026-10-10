# HBASE-32 copied-worktree source admission

This revision keeps every v1 target, JUnit, door, configuration, runtime JAR,
and campaign-core input immutable. Its runner uses the v1 configurations after
the v2 preflight. The v1 package and report gate remain unchanged.

The source checkout on node1 is a byte-identical copy of the clean HBase
2.6.6 source at Git commit `d5f63f523c065f963992ea4e74db268d17816631`,
but its `.git` worktree pointer references metadata present only on node0.
`source-snapshot-pin.json` records a digest of **all 6,062 source files**,
including relative paths, executable mode, and file contents. The pin was
calculated on node0 while Git verified that commit and tree
`9b304397e891105f5c003063c2cba12cf8cdb089`. Both hosts must match the
same whole-tree digest. If Git metadata is present, the preflight also verifies
the commit and tree; it accepts the copied snapshot only when the pinned Git
pointer's referenced metadata is absent. Changed source bytes, added files,
changed modes, changed pointer, or broken existing Git metadata fail closed.

The v1 manifest still independently pins the selected cluster JUnit source and
class, the target source and class, the flush RPC door source and class, all
runtime JARs, and the prior negative healthy receipt.

Offline admission and provenance tests (no Java launch):

```sh
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v2/test_source_identity.py
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v2/preflight.py --mode both
```

On an isolated assigned lane, run the fresh healthy discovery first. Run a
fault campaign only after its exact target and named RPC door are observed:

```sh
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v2/run_campaign.py --mode healthy --out /path/to/healthy
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v2/run_campaign.py --mode full --out /path/to/full
```

No JVM healthy or fault run is implied by the static preflight.
