# SOLR-40 node0 healthy watcher handoff

This is a separate **one-trial healthy-only** port of
`healthy-watcher-handoff-v1`. The unchanged Solr 8.11.4 JUnit is
`TimeRoutedAliasUpdateProcessorTest#test` on a four-node cluster. This
package cannot queue a fault or launch a full campaign:
`calibration_only=true`, `auto_promote_if_healthy=false`, and the budget is
one trial. `admission-request.json` has `go=false`; dispatch must create a
matching `admission-healthy-node0.json` only after the node0 lane is free.

The selected check is `RoutedAliasUpdateProcessor.getAliasProps@132:branch:1`
(line-133 throw). The typed candidate door is the
`ZkStateReader$AliasesManager.process@2312:door:1` watcher
`SolrZkClient.getData`, with `KeeperException.ConnectionLossException` caught
at source lines 2317-2319. A successful watcher read may write the volatile
alias cache via `setIfNewer` at line 2342, and a later request reads it via
`getAliases` at line 2223. The watcher and request normally have different
occurrences, so an observed cross-context handoff is still required. The
committed event-order analyzer retains its exact same-occurrence admission
rule; `audit_healthy.py` separately reports observed graph paths and sampled
cache handoffs without treating time or sampled versions as causal proof.

`python3 run_healthy.py --preflight-only` verifies the SHA-pinned Solr source
revision, JUnit and production source, compiled target and watcher classes,
agent, adapter, site catalog, frozen core, committed analyzer, runner and
runtime closure. It starts no JVM. The source, build, and same-JUnit healthy
fixture use the existing verified node0 paths; the package pins its own
config, sites, audit, runner, preflight, and admission request. The original
node2 package remains a separately pinned provenance input.

For a future runtime admission, dispatch must supply a case-local GO receipt
matching node0, healthy mode, config SHA, runner SHA, and the fresh node0
output. The runner checks host and output, at least **7,650,410,496 free disk
bytes** and **8,388,608 KiB MemAvailable**, then holds the active ZK node0
lock, Solr node0 lane lock, and shared Solr source lock in that order. It
also rejects another user JVM after acquiring the locks. The current ZK11
campaign occupies node0; no JVM was run to stage this port.

The fresh healthy result must pass one JUnit and show a nonthrowing exact
target on a named physical actor plus an exact typed watcher door before it.
Full-campaign review additionally requires an observed watcher-to-request
causal path or valid same-occurrence proof. A sampled cache version or
same-node temporal order alone leaves the source handoff gap open.
