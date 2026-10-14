# Solr ZooKeeper return-port translation audit

This audit uses the frozen original GraphChecker static artifacts for SOLR-19 and SOLR-06 on node1. It does not rerun static analysis, JUnit, or a fuzz campaign, and it does not alter their pins.

## Observed gap

Both cases use the system-wide `solr-zk-versioned-payload` wire declaration: the producer is the `byte[]` parameter of `SolrZkClient.malloryWrittenPayload(byte[])`; the consumer is the `byte[]` method return of `SolrZkClient.getData(...)`. In each frozen original `region_skeletons.jsonl.gz`, 415 selected region ports are OUT `METHOD_PARAMETER` and 449 are IN `METHOD_RETURN`. The original `static_scope_map.jsonl` has 415 `EXPORT_SITE` rows and no `IMPORT_SITE` rows. Original GraphChecker publishes export sites in its static scope map but carries both port sides in the region skeleton; zero import rows in that original map alone are expected.

The Mallory translation is where information was lost. Its frozen `static/static_scope_map.jsonl` again has 415 exports and no imports; its `weaveManifest.rpcPorts` contains one port with 415 export references and zero import references. `ScopePlanner.exactSite()` accepts only a `#uN` Jimple identity. The original port catalog names a `METHOD_RETURN` capture by the method signature without `#uN`. The translator already resolves `METHOD_PARAMETER` to its identity statement, but did not resolve `METHOD_RETURN`, so the 449 IN region declarations became one deduplicated `original_graphchecker_port_unmapped` gap. The producer had a translated site; the consumer did not.

Frozen artifact locations on node1:

- SOLR-19: `/dev/shm/mallory-solr19-native-v1/static-prep/{original,static}/`.
- SOLR-06: `/dev/shm/mallory-solr06-native-v2/static-prep/{original,static}/`.

| Case | Original map SHA-256 | Original skeleton SHA-256 | Translated map SHA-256 |
| --- | --- | --- | --- |
| SOLR-19 | `4ec50e06ab4f75ab70318d5a004b097ae4c74ed1cb3fb33600bb5e4d350412e7` | `2b11621c389e55845a26f8ffa5011301714960071e3fe98f0bed5f446773d475` | `8b8410a46ece79511660030f6db6bbcc34cbf004228661c7bc3183365942149c` |
| SOLR-06 | `2f5ab0340161fbc4c057964510a532c5b0ed39b19c6051f419734d4b02e8c74e` | `d1663fae5162399c8482cac2df9016ff8679b77b210886` | `fd12b843cc60bfff8f730b402932ffb982f3d1797e5ee27d3b5339d50b5db91f` |

The protocol declaration and patched Solr source are in `Mallory/adapters/solr/graphchecker_port/native_original/communication-mappings.jsonl` and `solr-e27f44e-original-engine.patch`. GraphChecker's `WireFlowCatalog.CaptureSite` validates a nonvoid `METHOD_RETURN` and records its return type; `SeedBackwardStaticAnalyzer.seedPort()` joins the declared producer and consumer value facts, and `RuntimeSelectedRegionFinalizer.declaredCutPortCell()` names the returned value as `<method>.return`.

## General correction

`ScopePlanner` now resolves a method-level `METHOD_RETURN` capture to **every value-return Jimple unit** of the declared method, after checking its actual return type against the catalog's `javaType`. It emits an `IMPORT_SITE` for each selected region and return exit and records `ORIGINAL_METHOD_RETURN_CAPTURE` provenance. A method with multiple return exits is deliberately overapproximated; a missing method, wrong type, or no value-return exit still fails closed and keeps the existing unmapped gap. No Solr method name or ad hoc check is hard-coded.

The synthetic Jimple test checks two return exits, rejects a mismatched declared type, and rejects `return void`. All 20 `ScopePlannerTest` tests pass. A full Solr static rerun is needed to measure the exact post-change import count in a new, pinned artifact; the frozen original and translated outputs remain unchanged.

## Runtime limit

This correction admits the **static value port**. It does not assert that a particular ZK read observed a particular writer or that a watch callback reached a target check. In original GraphChecker `MessageDoors.fetched`, a versioned ZK read outside `MessageDoors.notified` returns without installing an inbound causal context; the source comments intentionally treat polling reads as data rather than a notification cause. A runtime read-from edge would require an observed version-to-writer match and its own value-edge type, separate from the watch/activation cause. Therefore this patch does not manufacture a cross-process causal closure edge or change fault eligibility from the 449 static IN declarations alone.
