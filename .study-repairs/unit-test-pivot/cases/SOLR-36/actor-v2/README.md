# SOLR-36/37 ZooKeeper actor-aware V2

This is an isolated replacement for the ZooKeeper side of the earlier
`ShardSplitTest#test` campaign. It runs the unchanged Solr 8.11.4 cluster JUnit
from `../independent/run.py`. The earlier campaign remains raw legacy evidence;
its ZK steps cannot be counted as actor-matched V2 trials.

## Identity

The ASM agent hooks `ZkController.<init>` immediately after it stores its
`SolrZkClient`. It records the exact client object, the raw Solr node name, and
the stable role derived from `CoreContainer.getSolrHome()` (`control`,
`shard0`...`shard3`). Each ZK lambda passes its receiver object to the probe.
The fault selector and per-site ordinal include the stable `actorKey`, I/O
operation, source, caller, ZK path, and that client's connection generation.
`SolrZkClient.updateKeeper` replaces the underlying ZooKeeper handle during
reconnect, so every I/O row records the actual handle identity, session ID,
state, configured endpoint, client identity, raw node name, MDC node/core,
and Solr home. The raw handle and session ID are audit evidence rather than
cross-run replay keys. A different connection generation, unregistered
client, or disconnected session cannot consume a planned step. The endpoint
is Solr's connection string, not proof of a particular ensemble peer.

The target ASM hook passes the actual receiving `ZkController.getZkClient()`.
Its guard is bound only when that client's registration agrees with the
receiving node and has raw handle/session evidence. A trial counts for a
check only if the calibrated child and receiving actor reach the guard after
all planned faults.

This role is tied to the original test's serial `createServers` setup. The
calibration fails closed if the original test maps a child to different roles
across two fresh JVM runs. Rebooted clients under the same Solr home retain
the same logical role; a different physical node cannot satisfy its selector.

## Workflow on the designated free node

Do not run the two healthy cluster calibrations until a node slot is
explicitly released. `run_healthy.py` checks clean tracked source at original
Solr revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9` and records the
JUnit, target, ZK source and original Solr core JAR hashes before either JVM.
The build and smoke tests are safe offline and passed on node0.

```sh
python3 build_agent.py
python3 smoke_transform.py
python3 smoke_actor_match.py
python3 run_healthy.py
python3 calibrate.py
python3 fuzz_v2.py --max-effective 80 --max-faults 8
python3 audit_v2.py --archive
```

The controller holds a single-worker lock and uses durable atomic writes for
its own `campaign/state.json`, active plan, per-trial raw
events, JaCoCo coverage, JUnit result and elapsed seconds. Re-running the same
command resumes without repeating a completed plan. It requires two clean
original JUnit runs, matching source/JAR/agent SHAs, and an actor calibration
receipt. The independent auditor recomputes exact step application, raw
actor/session identity, same-child post-fault guards, time and exceptions
from the raw traces. It emits a per-check trial table and raw archive hashes.
It counts a trial as effective for a check only when all plan steps match and
that same child/receiver actor reaches its guard after the final injection.
The joint campaign continues until both checks have 80 effective trials,
the queue is exhausted, or the default 256 selected plans have been tried
(`--max-selected-plans` can extend this cap without resetting progress). If the last
eight joint effective trials add production probes or a new I/O family, it
extends to 128 effective trials and ten faults per sequence. Any target throw
is a candidate that stops the campaign for source and replay review; it is
not labeled a new bug automatically.

`calibration-receipt.json` is required before the first fault trial. The
smoke tests run against the original class bytes and verify that a matching
ZK I/O on a different `SolrZkClient` cannot consume a fault intended for the
selected actor.
