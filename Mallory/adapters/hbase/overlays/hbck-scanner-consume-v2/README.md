# HBASE-35 unique consumed scanner row tokens

The v1 healthy run (`data/mallory/calibration_v25/HBASE-35`) reached the exact named `HBaseFsck$3.visit` check four times, but its event-time audit had zero causal path doors. It reused one `QueueingFuture` completion token for five visited rows. The existing adapter had already claimed that completion token once at scanner receipt, so the graph correctly rejected all six consumers as ambiguous.

This v2 overlay emits **one new task token for each distinct `Result` object** after the worker has set `QueueingFuture.result` and before it notifies the waiting scanner. The base HBase adapter's `QueueingFuture.run` scope and RPC completion observation remain active at that point. `MetaTableAccessor.scanMeta` claims each row token only while invoking `visitor.visit(data)`, then closes the scope on normal return or exception. The base future completion token is never claimed by this overlay.

Tokens are attached to object identity, not row value, thread name, or timing. Duplicate identities, failed futures, missing results, and rows reconstructed by `ScanResultCache` do not create a visitor edge. A fresh fa5f healthy run must prove a named event-time path from an observed RPC door through the scanner handoff to the exact target check before fault testing can begin.

The overlay changes neither HBase source nor the existing HBase adapter. Its transformer runs after `HBaseAdapterTransformer`; it targets only `QueueingFuture.run` and the exact `MetaTableAccessor.scanMeta` visitor call. The staged config is healthy-only and requires dispatch admission plus immutable node1 runtime staging.

## Offline validation

```sh
mvn -o -q -DhbaseClientJar=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-client-2.6.6.jar -DhbaseAdapterJar=/users/ZhenyuLi/baseline/Mallory/adapters/hbase/target/mallory-hbase-adapter.jar test package
python3 preflight.py
```

These commands run ten focused tests, including transformation of pinned HBase 2.6.6 bytecode and composition after the existing adapter. They start no MiniCluster.
