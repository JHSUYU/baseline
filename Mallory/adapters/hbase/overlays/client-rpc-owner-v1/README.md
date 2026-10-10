# HBase client RPC owner overlay (source stage only)

The sealed HBASE-19 r0001 sequence includes a named `master0` response
`SEND` followed by a client `RECV`, `TASK_SUBMIT`, and `TASK_CLAIM` whose
actor is `unknown`. The base adapter records the response on the `Call`
receiver. It registers that receiver only when `Call` is created under a
named actor. The selected test gets its shared connection through
`HBaseTestingUtility.getConnection()`, but that connection's actual
`ConnectionImplementation.rpcClient` receiver is not currently scoped.

This overlay registers only the RPC client owned by the connection explicitly
returned from `HBaseTestingUtility.getConnection()`. It scopes
`AbstractRpcClient.callMethod` while `Call` is created and
`callBlockingMethod` through its completion claim. Both methods use the
registered receiver identity. Unregistered clients retain their previous
actor. The scope restores that actor on normal and exceptional exits. This
adds no graph edges by time, thread name, destination port, or guessed
request number. The existing base adapter's transported response token and
completion token remain the only handoff evidence.

The source and compiled HBase 2.6.6 sites, base adapter protocol, and staged
Java files are checked by `python3 preflight.py` without starting a JVM.
The overlay has **not** been compiled, installed, or run. A future isolated
Maven build runs the staged bytecode tests and must place
`edu.uva.liftlab.mallory.hbase.clientowner.ClientRpcOwnerTransformer`
**after** `HBaseAdapterTransformer` in `adapter.transformers`, then test
its transformed classes offline before any healthy MiniCluster run. Do not
replace the live HBASE-20 adapter or modify sealed HBASE-19 evidence.

Healthy runtime admission requires a JUnit pass and a named `client` response
`RECV`, `TASK_SUBMIT`, and `TASK_CLAIM` paired by the existing exact
response/completion tokens with `master0`'s response `SEND`. An
independent postfault invariant is still required to count a correctness
bug; the selected HBASE-19 exception alone is insufficient.
