# SOLR-37 target-actor strict fault pilot (node0)

V5 corrects the v4 actor pin. The original `ShardSplitTest#test` cluster
JUnit can place the @994 target on a different shard actor in different
healthy runs. [Actor drift evidence](actor-drift-evidence.md) identifies an
observed source-backed watcher-to-target path on the v4 run's actual actor.

The unchanged v4 agent enforces a registered reader, exact latest
instrumented ClusterState Java reference, resource, official watcher region,
actor/epoch, and structural occurrence before injecting an exception. The
v5 adapter emits the manual door on named shard actors. The controller
selects only qualified doors on the healthy run's actual target actor whose
path to @994 contains both observed exact-reference state edges. It keeps
multi-fault mutations on that actor. Every trial records ordered exact
door/match/apply receipts; fault trials require a later @994 check on the
injected actor. This is a candidate observation gate, not a bug finding.

Budget: six fault trials plus a fresh healthy run, 1,800 seconds total,
360 seconds per trial, at most three exceptions per sequence. Automatic
I/O doors and exploration outside the observed closure are disabled.
The runner resumes a matching checkpoint after interruption and records
`strict-audit.json` for each trial. Dispatch alone may update the checklist.

Offline validation:

```sh
python3 -m unittest -q test_audit_exact_path.py test_run_campaign.py
python3 verify_v4_actor_drift.py
python3 run_campaign.py --preflight-only
```

After dispatch issues the exact case-local GO receipt, the node0 steward
runs:

```sh
python3 run_campaign.py --admission-receipt admission-pilot-node0.json
```
