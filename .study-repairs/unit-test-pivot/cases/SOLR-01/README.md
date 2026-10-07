> **Actor identity recheck pending.** Earlier fault trials, coverage, and elapsed time are preserved under `legacy_coarse_actor` in `result.json` and in the original raw evidence. Their selectors did not establish the same runtime actor across runs. An actor-aware V2 campaign is required before this check counts as quality complete. [Independent audit](../../audits/completed-solr-actor-identity-2026-10-07.md).

# SOLR-01: HTTP alias fallback guard

**Current 102-check status: quality complete for the independent graph-free method.** The unchanged `CloudHttp2SolrClientTest.testAliasHandling` passed without instrumentation in 20.895 seconds and with case-local instrumentation in 25.942 seconds. The healthy trace reached the selected `getAliases` outcome 36 times and observed 15 actual `LISTALIASES` HTTP calls, yielding 30 initial request-failure selectors across two exception families. The method records the HTTP operation/resource, production callsite, alias-fetch invocation and attempt ordinal, plus the actual endpoint URL. Complete ordered injection and a later selected check are required for feedback; JaCoCo production coverage and stable I/O identities guide mutation.

The independent campaign finished **80/80 valid trials**, all with exact ordered injections and a selected check after the final fault. It used at most three faults per sequence, gained **110 production coverage probes, 12 methods, and 59 branches**, and observed **39 exact selected exceptions**. The last eight valid trials added neither production coverage nor a stable I/O identity, so the 128/max10 extension did not apply. Faulted JUnit runs used **1,809.497 seconds** in total. Every trial has its own raw event trace, JaCoCo file, JUnit log, elapsed time, and atomic checkpoint under `independent/evidence/campaign/`. The [trace audit](independent/evidence/campaign/audit.json), [coverage summary](independent/evidence/campaign/coverage-summary.json), and [candidate review](independent/evidence/campaign/candidate-review.json) reconcile the saved results.

All 39 selected exceptions followed injected failures at **every known live-node endpoint** of the same alias lookup. Original source line 267 explicitly throws when the loop exhausts those nodes. An all-`IOException` candidate and a mixed `SolrServerException`/`IOException` candidate both reproduced with three exact injections and the same selected throw. These observations establish the expected fallback and **no new bug** in this tested scope.

The six trials below remain historical evidence in `legacy-graph-result.json`.

The independent method's trial 3 injected three `IOException`s at the `LISTALIASES` HTTP callsite for attempts 1, 2 and 3 of one `getAliases` invocation, each against a distinct observed live-node URL. Its clean replay applied the same three logical selectors in order and reached the same selected throw. The replay trace and `independent/evidence/campaign/replay-summary.json` preserve the evidence; mixed-exception trial 7 has a second replay under `independent/evidence/replay-trial-007/`.
`run.sh` loads the GraphChecker runtime, and the exact selectors contain
precomputed `REGION.*` identities. The source review that all three failed
endpoints cause the expected exception remains useful, but these trials do not
count as the graph-independent runtime campaign.

## Selected check and original test

The selected check is the `RuntimeException` at
[`BaseHttpClusterStateProvider.getAliases(boolean):267`](../../source/solr-8.11.4/solr/solrj/src/java/org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider.java#L267),
instrumented target site
`<org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider: java.util.Map getAliases(boolean)>#u93`.
`getAliases` first tries `LISTALIASES` against each entry in the `liveNodes`
set. It returns after a successful response. The selected exception is its
explicit fallback after every attempted node fails.

The unchanged
[`CloudHttp2SolrClientTest.testAliasHandling`](../../source/solr-8.11.4/solr/solrj/src/test/org/apache/solr/client/solrj/impl/CloudHttp2SolrClientTest.java#L197)
is the workload. Its `SolrCloudTestCase` fixture starts three Jetty nodes and
embedded ZooKeeper. `getRandomClient()` at source line 151 always selects the
HTTP-backed client in this release. The test creates two collections and
three aliases, then updates and queries them through that client. No Docker
cluster or rewritten test operation was used. Exact source commit:
`e27f44e3d78dfcec230c97e0a1240e3751daeff9` (Apache Solr 8.11.4).

## Healthy seed and feedback

The native JUnit method passed in **12.17 s**. The instrumented healthy
recording reached `getAliases` **36** times without the selected throw. It
recorded **122 HTTP sends**, **113 receives**, and **1,044 observed I/O fault
markers**. Runtime selectors use the complete target occurrence, I/O site,
marker, hit ordinal and source key. The original JUnit source was unchanged.

## Bounded fault mutation

The first fault was selected from the healthy target occurrence. Each
subsequent fault came from a new I/O point observed in the preceding run of
that **same** `getAliases` occurrence. Thus, the sequence exercised one,
then two, then all three node attempts. Both I/O fault families followed the
same sequence:

```text
LISTALIASES → node A → injected exception
            → node B → injected exception
            → node C → injected exception
            → selected getAliases throw (#u93)
```

| Fault family | Faults | Exact applied | Test result | Selected guard after fault | New production method/branch outcomes | JUnit run |
| --- | ---: | --- | --- | --- | ---: | ---: |
| HTTP2 request `ConnectException` | 1 | 1/1 | Passed | Safe | 3 | 14.017 s |
| HTTP2 request `ConnectException` | 2 | 2/2 | Passed | Safe | 3 | 14.055 s |
| HTTP2 request `ConnectException` | 3 | 3/3 | Failed at selected throw | `#u24=true` | 4 | 12.900 s |
| HTTP2 response `TimeoutException` | 1 | 1/1 | Passed | Safe | 3 | 15.325 s |
| HTTP2 response `TimeoutException` | 2 | 2/2 | Passed | Safe | 3 | 13.449 s |
| HTTP2 response `TimeoutException` | 3 | 3/3 | Failed at selected throw | `#u24=true` | 4 | 13.868 s |

All six trials retained a target-method event after the final fault. The two
terminal traces each contain the fatal `#u24=true` branch and
`METHOD_EXIT_THROW java.lang.RuntimeException` **in the same target call**
after the third applied fault. The coverage counts exclude woven synthetic
fault guards `Http2SolrClient.request#u30` and `#u45`; the four new outcomes
in terminal trials are in the original `getAliases` method.

The exact three-fault `ConnectException` sequence was replayed once. All
three selectors applied again, the target guard and exception recurred in
the same call, and the original JUnit method failed at source line 267.
`[selectors.json](selectors.json)` preserves every exact selector,
`[trials-summary.json](trials-summary.json)` gives per-run counts and time,
and `[replay-summary.json](replay-summary.json)` gives replay evidence.
The raw traces remain in the node2 case workspace;
`[trace-integrity.json](trace-integrity.json)` records their SHA-256 digests.

## Source review and disposition

Both observed target exceptions are **expected all-endpoints-failed
outcomes**, not confirmed new bugs. The source explicitly catches each
failed `LISTALIASES` attempt and continues to the next live node. With one
or two injected request failures, a remaining node serves the alias lookup
and the JUnit method passes. With all three attempts faulted, there is no
successful endpoint, so line 267 deliberately raises the recorded
`RuntimeException`. The replay supports the same conclusion. This result is
scoped to the original test and these two exception families; other workloads
and fault types were not evaluated for this check.

The successful native run took **12.17 s**, the healthy instrumented run
**13.462 s**, six faulted JUnit runs **83.614 s**, and replay **11.8 s**.
These workloads totaled **121.046 s**. From the successful native run's
start to replay completion, including investigation and orchestration, the
elapsed wall time was **873 s** (2026-10-06 18:02:39–18:17:12 UTC).
