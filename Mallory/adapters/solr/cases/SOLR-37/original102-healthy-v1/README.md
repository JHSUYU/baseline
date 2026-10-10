# SOLR-37 original-102 healthy-only stage

Selected JUnit: `org.apache.solr.cloud.api.collections.ShardSplitTest#test`. Selected exact guard: `DistributedZkUpdateProcessor.doDefensiveChecks@994`. Source and compiled target class hashes, JUnit source hash, catalog, agent, adapter, and frozen graph-order core are pinned in `config-healthy-node2.json`. The site catalog is unchanged from the staged full-v1 package.

This package runs one fresh healthy seed and stops after trial 0. `calibration_only=true` and `auto_promote_if_healthy=false` are enforced by the runner and frozen core. It cannot run a fault trial. `admission-request.json` has `go=false`, and no dispatch GO receipt is staged. The full-v1 package remains unadmitted.

The previous subshard HTTP fault used a `StdNode` with `maxRetries=0`; seven strict applications had later target checks in other requests but no time-respecting fault-to-target path. A fresh healthy observation must identify a different source-backed door before any fault pilot.

## Runtime gate

On node2, stage the pinned checkout at `/users/ZhenyuLi/.mallory-worktrees/solr-lane3` and all absolute-path artifacts in the config. Run `python3 run_campaign.py --mode healthy --preflight-only`; it must pass source, JUnit, compiled-class, artifact, catalog, manifest, and core checks without launching a JVM. Dispatch may then issue `admission-healthy-node2.json` matching the request's case, host, mode, config SHA, runner SHA, and intended output. Only that receipt permits `run_node2.sh healthy`. The shell requires node2, exclusive case and shared Solr source locks, at least 7,650,410,496 available disk bytes, and at least 8,388,608 KiB MemAvailable. Run after the HDFS lane and serially with other Solr source users.

After the fresh healthy run, require JUnit 1/0/0, the exact named nonthrowing target on an attested node and class, and an event-time-respecting graph path from a named typed I/O door to that target on a relevant request or actor. Healthy success alone does not authorize full execution. A source-backed fault model and a separate bounded target-retention pilot are required before any full GO.
