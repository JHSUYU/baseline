# HBASE-35 consumed scanner result handoff

The HBASE-35 healthy JUnit run reaches the exact `HBaseFsck$3.visit` target four times, but its causal graph has no event-time path from an RPC door to the target. The existing HBase adapter emits a `TASK_CLAIM` when a completed scanner future is returned, then immediately closes that context. `MetaTableAccessor.scanMeta` subsequently invokes `visitor.visit(data)` under the root context.

This isolated overlay reuses the **already published token for the exact `QueueingFuture`**. On a successful `QueueingFuture.get()` return, it binds that token to the `Result` objects in the returned `Pair<Result[], ScannerCallable>`. It restores the token only while `MetaTableAccessor.scanMeta` invokes `Visitor.visit(data)` for the identical object. The binding is consumed once and the scope closes on normal return or exception. Missing, ambiguous, reconstructed, or garbage collected result identities create no edge. There is no actor-wide token or temporal matching.

`CompleteScanResultCache` passes complete rows through unchanged. A row assembled from multiple partial results may have a new identity and is deliberately not linked by this version. A fresh healthy trace must demonstrate that the selected HBASE-35 target's region has the consumed token as parent, with a named event-time RPC/scanner path. If it does not, this overlay does not justify a fault run.

The overlay runs after the existing `HBaseAdapterTransformer` and does not change that adapter or HBase source. Its private-field lookup is tied to the existing adapter's `SCANNER_TOKENS` and `ScannerTokens.result`/`resultPublished` layout. The healthy-only configuration is staged for dispatch; its new adapter JAR and fa5f agent must be copied to the specified isolated runtime locations before a host run.

## Reproduce offline checks

```sh
mvn -o -q -DhbaseClientJar=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-client-2.6.6.jar test package
python3 preflight.py
```

With `-DhbaseAdapterJar=/users/ZhenyuLi/baseline/Mallory/adapters/hbase/target/mallory-hbase-adapter.jar` added, the Maven command runs nine focused tests, including transformation of the pinned compiled HBase 2.6.6 classes and composition after the existing HBase adapter. It does not start a MiniCluster.

## Pinned evidence

* HBase source commit: `d5f63f523c065f963992ea4e74db268d17816631`.
* `MetaTableAccessor.java` SHA256: `1231841a2cdae7a9e2b2dd7354da624dc153fa6862b65e7aa0a22515f80881cd`.
* `ResultBoundedCompletionService.java` SHA256: `fff82effe9cc1ac8c89eef774de41af5e042f51d35687ce2646c2a21884dcf01`.
* HBase client JAR SHA256: `b3c9537a0c5f4b057134c59298b453ae207d2e6279be66d71c80da36d0d2de54`.
* Compiled `MetaTableAccessor.class` SHA256: `f8e84aaa560a1cdfd3e181beb001cb6d56e2aafd2504579b8c39ce9bc5d2543b`.
* Compiled `QueueingFuture.class` SHA256: `df7b42a5ed86f4677a141eb5c0d127d42752e45a8eb00e9a1665c8c65b703bee`.
* Existing adapter JAR SHA256: `5f83ae1146141c3559073c13fd5b9b952f09af87e4c9d83d2288fbd2c4fd2827`.
* Overlay JAR SHA256: `0934fa17acd86e42fe3e79b9d97fdeca183b4c63b9d02352532461e798ccbe73`.
