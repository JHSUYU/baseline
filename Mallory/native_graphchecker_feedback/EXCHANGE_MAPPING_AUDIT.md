# REGION_STATE exchange-to-plan audit

The original GraphChecker records a physical exchange before the receiver's
first instrumented method enters. Such a `EXCHANGE_RECEIVE` has `callId=0`, so
walking its call ancestry cannot find a Finalizer region plan. The protocol
envelope also carries a `producerEndpointId`; GraphChecker places that exact ID
in the subsequent occurrence address as `/ctx:Anchor:<id>@...`. The feedback
bridge now uses that recorded identity when call ancestry has no plan owner.

The fallback requires one exact Finalizer producer occurrence, the same
physical `sourceKey` at the sender and producer, a receiver occurrence under
the exact producer endpoint ID on the receive actor, and ordered producer
entry → send → receive → receiver entry. Role-only endpoints, unmatched
anchors, and plans on another actor remain unmapped. Multiple observed
receiver regions under one exact message anchor are separate control-flow
consequences of that message; they produce distinct stable region edge
families. This is message-context reachability, not proof that every region
reads a particular RPC field.

| Frozen healthy input | Paired exchanges | Unmapped before → after | Edge families before → after | Anchor-mapped pairs |
| --- | ---: | ---: | ---: | ---: |
| HBASE-02 `r0000` | 256 | 256 → 256 | 0 → 0 | 0 |
| SOLR-05 `r0000` | 178 | 130 → 120 | 9 → 17 | 10 |

HBASE-02 evidence:
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-02-20261014-native-v1/campaign/trials/r0000/`.
Its 83 original Finalizer plan rows all name the JUnit source
`TestConnectionImplementation#testMetaLookupThreadPoolCreated`; none name
`master0`, `rs0`, or `rs1`. The 128 request receives occur before a method
enters (`callId=0`); the 128 response receives occur in
`RpcConnection.readResponse` outside any selected plan. The catalog has 89
`LINEAGE_LOST` gaps. A request reached a server method in the raw trace, but
its server region was not admitted to this target's Finalizer plan. Pairing
alone therefore cannot justify a target-closure edge. This patch deliberately
leaves the HBase campaign feedback unchanged.

SOLR-05 evidence:
`/proj/silentfailure-PG0/mallory/solr05-native-formal-v1/formal/trials/r0000/`.
All 95 `SOLR_HTTP`/`SOLR_HTTP2` receives lack a call-stack plan owner. Ten
`SOLR_HTTP` receives have both an exact producer plan and a later receiver
plan with the transported endpoint ID. They add eight distinct region edge
families; after exact Finalizer membership filtering, the recomputed healthy
summary has 15 closure edge families. The `SOLR_HTTP2` sends inspected here
start from a `ROLE.EXECUTOR_TASK` endpoint, with no exact producer plan; these
remain unmapped. Most other ZooKeeper/HTTP receives also lack one side of the
exact mapping. This does not claim complete Solr cross-process coverage or a
fault-induced target exception.

The frozen traces, original plans, and trial verdicts were read only. The
bridge unit tests include positive pre-method receive mapping and negative
anchor/role cases. On this branch, six focused synthetic/read-only tests pass.
The optional recorded ZooKeeper-07 test currently fails its pre-existing
`newClosureEdgeFamilies > 0` expectation on both the parent commit `86407c02`
and this branch: exact Finalizer membership yields zero for that fixture. This
is separate from the new fallback and needs a fixture expectation audit.
