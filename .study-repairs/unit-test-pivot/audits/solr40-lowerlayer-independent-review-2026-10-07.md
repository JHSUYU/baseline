# SOLR-40 lower-layer retry control: independent review

This is a read-only review of the five unchanged-original-JUnit runs in
`cases/SOLR-10/actor-v2/evidence/lowlevel-single-retry-v10/`. It is a
selector variation: each run first faults the physical `jetty:node1`
collection-state `EXISTS_WATCH`, then injects **one** underlying
`ConnectionLoss` into the same client's `/aliases.json` watch read. The
first selector uses occurrence 10, whereas the prior trial 481 used 15;
these are not identical replay plans. The audit file reports `issues=[]`
and records each trace, JUnit, JaCoCo, manifest, and failed-run ZooKeeper
transaction-log hash.

Runs 1–2 reached the target on the same reader with alias properties present;
the underlying read retried successfully about 1,501 ms after the injected
failure, and the original JUnit passed. Run 3 passed without reaching that
same-reader target. Runs 4–5 reached the selected target with properties
missing and raised its exception 184.302 and 188.611 ms after the injected
failure. Both original JUnits failed with an `/update` 500. Neither run
recorded a retry return before JUnit shutdown. Their ZooKeeper transaction
logs show the alias creation persisted; the JUnit logs show CREATEALIAS
status 0 before the update failure. The target exception is a same-client,
same-manager cache read result, rather than direct propagation of the
injected `ConnectionLoss` to the test thread.

The Solr 8.11.4 source explains the timing: `SolrZkClient.getData` delegates
to the retry path; `ZkCmdExecutor` waits 1,500 ms before its first retry;
`RoutedAliasUpdateProcessor.getAliasProps` reads the local alias cache during
that interval. `RoutedAliasUpdateProcessor.wrap` turns the target's initial
503 into a 500, so the cloud client does not classify it as a connection
error to retry. The original test class and routed-processor class hashes
were unchanged in the isolated control; only the SolrZkClient/probe classes
were instrumented.

**Classification:** reproducible transient stale-cache failure candidate,
not yet a confirmed new production bug. The control does not establish the
outcome after the 1,500 ms retry completes, nor does it exercise a real
ZooKeeper disconnect and watch recovery. A minimal next control is a single
underlying alias-read failure without the preceding collection-state fault,
plus a version that lets the same reader run after retry completion. Preserve
the current `novelty_pending` mark until these are source-reviewed and
replayed.
