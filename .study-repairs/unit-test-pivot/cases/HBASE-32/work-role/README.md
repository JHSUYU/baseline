# HBASE-32 role-aware supplemental variation

This is a **new fault plan**, separate from the six exact s272 replays and from
both fuzz denominators. It keeps the original HBase 2.6.6
`TestRegionReplicaFailover#testLotsOfRegionReplicas` and its MiniHBaseCluster.
No cluster JUnit has been run with these role agents yet.

## Runtime identity

The upstream ASM agent observes the four-argument
`MetaTableLocator.setMetaLocation` only at normal method return, after its
ZooKeeper `setData` or `createAndWatch` call. For default replica 0, an `OPEN`
state records the full `ServerName` (host, port, startcode); later non-`OPEN`
updates clear it. The `MASTER_OPENED_RPC` hook compares the reporting region
server's full `ServerName` to this current value *at the actual RPC callsite*.
Only a matching table2 replica-2 report can receive F1. Its complete primary
and secondary region names are saved before injecting `DoNotRetryIOException`.

The client `FlushRegionCallable.call:81` hook then accepts F2 only inside the
target invocation for that saved **raw primary region** and replica 2, with
target ordinal 1 and RPC ordinal 1. Thus the two faults are linked by an
actual same-run region identity rather than the stable table/start-key prefix
alone. The old trace-only ServerStateNode lock agent remains enabled for the
future JUnit. Post-run validation must still independently compare F1, F2,
and B7 raw identities, the latest successful pre-F1 meta host, and cluster
liveness. Target-lost or role-mismatched runs will remain attempts only.

The frozen plan and SHA-256 hashes are in [role-plan.json](role-plan.json).
The F1 selector includes `meta-host`; F2 includes `actor-selected`. This plan
is deliberately different from s272's original `attempt-1`/`target-1` plan.

## Offline validation and next gate

`bash run.sh build` compiled both isolated Java 8 ASM agents. `bash run.sh
smoke` checked the OPEN/CLOSING role state, full actor region/replica matching,
both fault selector strings, and that ASM weaves the release JAR's successful
meta write, master report RPC, and client flush RPC callsites. The smoke
output is [smoke.log](smoke.log). This test starts no cluster.
The independent [runtime auditor](audit_role_run.py) checks the last
successful pre-F1 meta `OPEN` generation, F1's full server identity, saved
raw primary/secondary and replica, F2's selected actor and target ordinal,
and the matching post-fault B7. A labeled synthetic trace passes, while a
copy with a different F1 server is rejected; these are parser smokes, not
cluster evidence. Their receipts are
`synthetic-role-audit-{positive,negative}.json`.

Before fault injection, run one unchanged, **fault-free** original JUnit with
these agents in an isolated slot and verify `META_LOCATION`/`PROBE_WOVEN`
events, test pass, exact target invocations, and the full F1/F2 actor receipt.
Only then start a bounded role-aware fault phase with a separate checkpoint,
fresh effective count, and per-run raw/JUnit/JaCoCo/lock trace. Never merge it
into the s272 exact replay count or the earlier 128+68 effective trials.

`role_pilot.py` is the isolated controller for that gate. Its `preflight`
command verifies the frozen plan, original HBase JAR, three agent JARs,
runner, auditor, and disk headroom without starting a cluster. After node0
is explicitly released, run `python3 role_pilot.py healthy --lease-ready`
in persistent tmux. The healthy run uses **empty fault plans** and a 360-second
cap. It must pass the original JUnit and show one same-run meta host,
replica-2 Master report, target invocation, and flush RPC for the same raw
region before `fault` is allowed. `python3 role_pilot.py fault --lease-ready`
runs one 600-second fault trial per invocation, with at most three distinct
fresh-fixture attempts. Each invocation writes an atomic in-flight checkpoint,
raw log, JaCoCo, exit, receipt, and fault-run `Thread.print -l` dumps; an
interrupted run requires manual evidence settlement and is never silently
rerun. `python3 role_pilot.py recover` settles a finished orphan from its
terminal log or records it as an interrupted attempt; it never starts a JVM.
After each settled run, `python3 archive_role_pilot.py <suffix>` mirrors the
raw log, JaCoCo, receipt, thread dumps, frozen plan, and agents to node1 and
verifies every archived file SHA on the remote side. Fault trials are
diagnostic repeats of one new role-aware plan, so
their count is separate from the fuzz effective denominator. A timeout
remains a candidate until independently reviewed.

Limitations: the passive meta location hook observes successful writes made
in this MiniCluster JVM. It must be compared with the source system's
pre-fault meta `OPEN` log and any later role changes in each trial. An F1 on
the meta host alone does not imply the s272 stall: exact same-plan replays 4
and 6 both selected a meta-host and recovered because no report READ holder
remained when the tracker requested WRITE.
