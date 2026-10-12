# HBASE-35 one-shot scanner result handoff

The v1 healthy run reached `HBaseFsck$3.visit` but reused one Future completion token for five visitor calls. The graph rejected the repeated claims. V2 gave each returned `Result` a separate worker-published token, but its identity map could issue another token if the same `Result` object appeared in a later Future after its first visit. V2 was never run on a cluster.

V3 preserves the per-row worker publication and adds a **one-shot weak identity tombstone**. A `Result` object receives at most one task token in its lifetime. The visitor consumes that token once. If HBase reuses that object for another row, the later visitor has no edge. Duplicate objects within one response, shared objects across Futures, failed Futures, and reconstructed cache rows also fail closed.

This identity is supported by the HBase 2.6.6 source path used by the HBCK meta scan: `ScannerCallableWithReplicas` returns the actual `Pair`'s `Result[]` (lines 203–213 and 247–260); `CompleteScanResultCache.addAndGet` returns unchanged complete rows when it has no pending partials (lines 96–99); `ClientScanner.nextWithSyncCache` returns the cached `Result` object (lines 326–343); and `MetaTableAccessor.scanMeta` passes that object directly into `visitor.visit(data)` (lines 843–846). When any cache step creates a different object, the v3 mapping has no match and creates no claimed path.

The transformer runs after the existing HBase adapter. It publishes each unique token in the worker's `QueueingFuture.run` scope after `resultObtained` is set and before `tasks.notify()`. The visitor claim is scoped exactly around `MetaTableAccessor.scanMeta`'s call to `Visitor.visit(data)`, including exception cleanup. The existing Future completion token remains consumed once by the base adapter and is never claimed by this overlay.

A fresh fa5f healthy calibration must prove a named, event-time RPC/scanner path to the exact HBASE-35 check before any fault trial. The staged configuration is healthy-only; dispatch must approve runtime staging and execution.

## Offline validation

```sh
mvn -o -q -DhbaseClientJar=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-client-2.6.6.jar -DhbaseAdapterJar=/users/ZhenyuLi/baseline/Mallory/adapters/hbase/target/mallory-hbase-adapter.jar test package
python3 preflight.py
```

Eleven focused tests cover row uniqueness, Result reuse after consumption, failure/duplicate/partial identity rejection, pinned compiled HBase 2.6.6 bytecode, and composition with the existing adapter. These checks start no MiniCluster.
