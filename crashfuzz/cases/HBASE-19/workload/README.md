# HBASE-19 and HBASE-20 JUnit workload

`TestModifyNoReopenCrashFuzz` is a small adaptation of the first operation in
HBase 2.6.6 `TestModifyTableProcedure.testModifyWillNotReopenRegions` (source
lines 593–612). It uses the same `TestTableDDLProcedureBase` embedded cluster,
creates a table, submits `ModifyTableProcedure` with `reopenRegions=false`, and
checks the resulting descriptor. It ends before the original test's forced
region moves and Snappy compression change. On this test host, Snappy is
unavailable and the original test times out during later assignment retries.

The healthy adapted operation keeps the column-family count and coprocessors
unchanged, so it reaches both selected checks without taking their exception
branches:

- HBASE-19: `ModifyTableProcedure.preflightChecks#u50`, source line 135.
- HBASE-20: `ModifyTableProcedure.preflightChecks#u55`, source line 139.

The unchanged original test reached these checks too (four and three
`CHECK_REACHED` events respectively) but each healthy JUnit returned 124 after
300 seconds. Isolated adapted probes on node1 and node2 returned 0 in 40.144
and 39.506 seconds, with one exact `CHECK_REACHED` event for each selected
site. The probe manifests are under each node's
`/users/ZhenyuLi/static-rerun/results/HBASE-{19,20}/adapted-probe/healthy/`.

`adapted-checklist.json` contains only these two original check locations and
points them at the adapted JUnit method. Each case must use its own result
directory and a new campaign suffix so old timed-out healthy traces and any
future fault trials remain distinct. Compile this source into the runner's
`build-original-hbase-junit` classpath on the execution host before running.
The Soot selection must be refreshed for this new workload; the previous
artifacts were generated before target throw sites were recorded.

## Fresh campaigns

The isolated tool copy at
`/users/ZhenyuLi/static-rerun/workload/hbase1920/tool` contains the updated
selector, runtime agent, and fuzzer. The `HBASE-19` campaign runs on node1 and
`HBASE-20` on node2, each in its own tmux session named
`crashfuzz-hbase-adapted-HBASE-<number>`. The initial command for either case is:

```sh
cd /users/ZhenyuLi/static-rerun/workload/hbase1920/tool/core-fuzzer
python3 rerun102_worker.py --system HBase \
  --checklist /users/ZhenyuLi/static-rerun/workload/hbase1920/adapted-checklist.json \
  --result-root /users/ZhenyuLi/static-rerun/results \
  --case-id HBASE-19 --campaign-suffix no-snappy-v1 \
  --refresh-selection --max-trials 80 --max-faults 10
```

Use `HBASE-20` for the second case. For a restart, omit `--refresh-selection`
to pin the generated Soot artifact and resume the existing checkpoint. The
fresh selection identifies the exact `HBaseIOException` throw at `#u50`
(line 135) and `#u55` (line 139). Both new healthy runs reached their check and
returned 0: 37.711 seconds for HBASE-19 and 34.398 seconds for HBASE-20. The
fault campaigns are running under `campaign-no-snappy-v1` in their respective
case result directories; these are separate from the earlier timed-out healthy
probes.
