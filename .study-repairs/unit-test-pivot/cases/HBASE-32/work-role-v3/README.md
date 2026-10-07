# HBASE-32 dynamic meta-host and replica diagnostic (V3)

This is a new plan and ledger, separate from the original supplemental fuzz
checkpoint, the six exact s272 replays, and the V1/V2 no-fault calibrations.
It runs the unchanged HBase 2.6.6
`TestRegionReplicaFailover#testLotsOfRegionReplicas` MiniHBaseCluster JUnit.

The V1 fixed region was not on the meta host in its passing healthy run.
V2 removed the fixed region but kept replica 2; in its passing healthy run,
all 60 replica-2 OPENED reports came from a non-meta RS. The meta host
served different replica indices in the two fixtures. Both raw runs and
JaCoCo were archived with per-file SHA verification on node1, and neither
is counted toward V3's two required healthy passes.

V3's first fault selector chooses the first actual table2 **secondary**
OPENED RPC whose reporting full `ServerName` equals the most recent
successfully written `hbase:meta` OPEN location. It records actual replica
number, raw primary and secondary region, stable region, server, and meta
generation. The second selector only fires for that saved primary,
secondary, and replica inside the corresponding target invocation's first
`FlushRegionCallable.call:81` RPC. The post-run auditor checks the exact
two faults in order, matching raw identities, selected target invocation,
and B7 rethrow after the final fault. The trace-only ServerStateNode lock
agent remains enabled. Dynamic selector tokens do not substitute for these
actual runtime identities.

`bash run.sh build` and `bash run.sh smoke` passed with Java 8 against the
release JAR's meta-location write, Master report RPC, and client flush RPC
callsites. Synthetic positive and wrong-replica audit controls passed. V3's
healthy parser also found 178 complete role→target→RPC chains in the
**historical V2 raw healthy log**, which is parser validation only; it is
not imported as a V3 healthy pass. Frozen plan, source, original test JAR,
agent, runner, and auditor SHA values are in [role-plan.json](role-plan.json).

After an explicit isolated node0 slot handoff, run two V3 no-fault original
JUnit calibrations with `python3 role_pilot.py healthy --lease-ready` in
persistent tmux. Both must pass and show a same-run role→actor→target→RPC
chain. Only then run up to three diagnostic fault attempts, one per
`python3 role_pilot.py fault --lease-ready` invocation. The controller has
an atomic checkpoint, 3 GiB hard disk gate, 4 GiB review threshold, and
no-other-Java/TCP-listener gate before each JUnit. It records run time,
JUnit, JaCoCo, actual identity, exit, raw trace and lock dumps. A crash can
be settled with `python3 role_pilot.py recover` without rerunning a suffix.
After each full round, `archive_role_pilot.py <suffix>` mirrors the raw
receipt and evidence to node1 and checks every file SHA.

A B7 exception is the expected effect of the injected DNR exception. A
timeout remains a candidate until an isolated same-plan original JUnit
replay and independent source/lock review. No V3 diagnostic trial enters
the old 128/128 main or 68/80 supplemental effective denominator.
