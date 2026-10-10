# SOLR-37 bounded strict fault pilot (node0)

This package is an isolated successor to the sealed v3 healthy run. The v3 receipt
records one passing `ShardSplitTest#test` JUnit invocation, 188 exact @994 target
checks, 188 watcher-to-target paths containing both observed exact-reference
`STATE` edges, and zero candidate `STATE` edges. This package pins that archive,
the source and compiled Solr artifacts, the case-local agent and adapter, and the
released Mallory core. It does not authorize a JVM until dispatch writes the
matching `admission-pilot-node0.json` GO receipt.

The only injectable site is the `ZkStateReader.fetchCollectionState` `getData`
call for `/collections/collection1/state.json` inside the real
`StateWatcher.refreshAndWatch` occurrence on `shard-4`, epoch 0. The actual
reader must be registered to that actor and its current `clusterState` must be
the same Java reference as the last instrumented publication. The agent emits
`reader_ref`, exact `state_version`, resource, region, dynamic occurrence, and
stable per-site ordinal on the door and both fault receipts. The plan matches
the stable ordinal and structural watcher occurrence. It can also require a
literal occurrence when one is supplied; a healthy run's transport-generated
occurrence is not replayed across processes.

The controller admits the healthy seed only if a qualified door has an
event-time path to @994 containing both observed exact-reference state edges.
After a fault, it admits a trial only if all planned faults have unique,
ordered, identical door/match/apply identities and @994 executes later on
`shard-4`, epoch 0. A lost target is recorded and not expanded. These are
reachability and fault-effectiveness gates, not a bug classification.

Budget: six fault trials plus a fresh healthy trial, 1,800 seconds total,
360 seconds per trial, and at most three exceptions per sequence. Automatic
I/O doors and exploration outside the observed closure are disabled. Output
resumes from its checkpoint after controller interruption.

Offline verification:

```sh
python3 -m unittest -q test_audit_exact_path.py test_run_campaign.py
python3 run_campaign.py --preflight-only
```

Node0 steward, after a dispatch GO receipt:

```sh
python3 run_campaign.py --admission-receipt admission-pilot-node0.json
```

Every trial has `strict-audit.json` alongside the ordinary Mallory result and
compressed trace. Only dispatch owns checklist updates.
