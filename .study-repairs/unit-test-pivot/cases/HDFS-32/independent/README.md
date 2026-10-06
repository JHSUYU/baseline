# HDFS-32 independent baseline

The selected check is Hadoop 3.4.3 `DataNode.deleteBlockPool` at
`DataNode.java:3819–3824`: `blockPoolManager.get(blockPoolId) != null` leads to
the explicit `IOException` at line 3822. The bytecode overlay records the
`BlockPoolManager.get` result and the exact `ATHROW`, each at one verified
injection site. `TestDeleteBlockPool#testDeleteBlockPool` is the original JUnit
method from the distribution test JAR. It starts two NameNodes and two
DataNodes. The healthy test intentionally reaches this throw twice, once per
DataNode; those exceptions are baseline behavior, not new failures.

The guard reads a local `BlockPoolManager` map, but that map is changed by
asynchronous service shutdown: `refreshNamenodes` stops and joins the old
`BPOfferService`, whose actor cleanup calls back into
`BlockPoolManager.remove`. This provides the coordination context for the
selected check. The first delete call on the **second distinct DataNode** is
the runtime target. Valid fault trials require every planned
`Client.getRpcResponse` selector to match and apply in order, followed by this
same DataNode guard after the final fault. The original JUnit result and the
exact selected throw are compared with the healthy baseline. Production
JaCoCo coverage and observed RPC I/O provide the only mutation feedback.
Probe coverage is filtered by exact class membership in the original
production HDFS, HDFS client, and Common JARs. The first 19 current-method
trials were normalized from saved JaCoCo data after this filter was added;
none of their JUnits were rerun. The pre-correction checkpoint and counts are
in `evidence/probe-filter-correction`.

`run_native.py` uses clean Hadoop 3.4.3 distribution JARs and a case-local ASM
overlay, with no GraphChecker or skeleton on the classpath. The healthy
baseline is `evidence/healthy-baseline.json`; complete raw outputs are at its
`raw_run` path. `campaign.py` atomically checkpoints each trial in
`evidence/campaign-state.json`, appends `trial-ledger.jsonl`, and atomically
updates this case's `result.json`. The campaign uses 80 trials and up to eight
ordered faults; late new production coverage or stable new target-before-I/O
families conditionally extend it to 128 trials and ten faults.

## Invalid first recorder and quarantine

The initial 11 trials used `Files.write` for probe events and let its
`ClosedByInterruptException` escape. On the interrupted `BPServiceActor`
cleanup thread, this prevented `BlockPoolManager.remove` from running. In
trial 005, the test then failed its `getAllBpOs().size() == 1` assertion. This
was probe interference, not an HDFS failure. The 11 trial records and the
original probe class are preserved in `evidence/invalid-probe-interference`;
full raw runs were moved to
`/users/ZhenyuLi/hdfs32-invalid-probe-runs-20261006`. All 11 are excluded from
the current budget, coverage, and bug counts.

The replacement recorder catches logging `IOException` without interrupting
the original method. `evidence/recorder-error-path-smoke.log` shows that an
interrupted callback returns while a deliberately invalid trace destination
causes a logging error. The new healthy original JUnit passes with five guard
events, two expected target throws, and both refresh callbacks removing the
old block pool before subsequent delete calls.

## Completed campaign

The campaign completed 80 attempts at up to eight ordered RPC faults. The
final audit at `evidence/final-audit.json` independently rechecked every run
manifest, production probe class, fault event sequence, target identity,
selected exception, and JUnit result. It found 74 strictly applied plans and
47 target-retaining trials, all with the healthy expected selected throw and
a passing JUnit. No target-retaining run had a new failure. Of 21 nonzero
JUnits, 17 ended with the injected RPC `IOException` before the target, three
timed out before it, and trial 047 failed an earlier first-DataNode assertion
after the write pipeline excluded that DataNode. The selected second-DataNode
guard was never reached in those 21 runs. The trial 047 test assumption and
dataset source review are recorded in the final audit and case README.
