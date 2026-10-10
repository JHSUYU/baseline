# Node2 HDFS-20/29/30 v3 terminal collectors

This sibling package pins only the immutable v3 full configs for HDFS-20/29/30 (config SHA prefixes `7fa13018`, `228928e5`, `7d6c54ac`). It does not alter the active HDFS-19 v1 collector manifest, SHA `8d984734`. `cases.json` has unique v3 private outputs and node0/node2 state roots.

The node2 collector locks the natural terminal campaign, checks every raw file SHA and disk reserve, archives complete evidence, runs the frozen fa5f audit and publishes only after a matching checkpoint/result. The node0 watcher verifies the remote archive SHA/size, copies only result/config/audit and SHA receipts under a 5 GiB + 128 MiB floor, then atomically publishes the compact terminal case. Trial traces remain on node2. Both scripts refuse a different existing canonical result.

Read-only static preflight and three integrity tests passed locally and on node2. No JVM or collector was launched during staging. Dispatch must use the exact v2 manifest SHA and actual worker tmux name, then arm durable watchers only after that case's independent full admission:

```
python3 collect_node2.py --case HDFS-20 --manifest-sha e7d12da86178392fcedf7cb9fb527ac62ba05d4f8a253e6ecb009f968f36d74c --worker-session <actual-worker-tmux>
python3 sync_node0.py --case HDFS-20 --manifest-sha e7d12da86178392fcedf7cb9fb527ac62ba05d4f8a253e6ecb009f968f36d74c
```

Use HDFS-29 or HDFS-30 with the same scripts when its full campaign starts. Keep the v1 HDFS-19 watchers and manifest untouched. If any v3 full config changes, make a new versioned manifest rather than changing this one.
