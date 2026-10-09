#!/usr/bin/env python3
"""Write three case-specific summaries after their shared campaign completes."""
import json
from campaign import CASES, EXPECTED, THROW_LINES, case_path

CHECKS = {
    13: ('`MetaTableAccessor.hasMergeRegions` returns true', 'false', 488),
    14: ('`RegionStates.getRegionState` returns null', 'non-null', 498),
    15: ('`RegionState.isOpened` returns false', 'true', 502),
}

for number in CASES:
    data = json.loads((case_path(number) / 'result.json').read_text())
    assert data['status'] in ('quality_complete', 'candidate_review')
    predicate, healthy_value, guard_line = CHECKS[number]
    trials = data['fault_trials']
    passed = sum(x['junit_passed'] for x in data['fault_trial_details'])
    valid = [x for x in data['fault_trial_details']
             if x['strict'] and x['target_after_final_fault']]
    unique = len({x['plan'] for x in data['fault_trial_details']})
    text = f'''# HBASE-{number}: merge preparation check

+`MergeTableRegionsProcedure.prepareMergeRegion` checks whether {predicate} at HBase 2.6.6 source line {guard_line}. Its failure arm at line {THROW_LINES[number]} throws `{EXPECTED[number]}`. The unchanged original `TestMergeTableRegionsProcedure#testMergeTwoRegions` submits one merge of two regions to a MiniHBaseCluster. The counted healthy JUnit passed in {data['healthy_elapsed_seconds']:.2f} seconds and reached this check twice, once for each region, with the normal value `{healthy_value}`. JaCoCo covered guard line {guard_line}; failure line {THROW_LINES[number]} was uncovered.

+The shared independent campaign completed **{trials} unique ordered fault trials**, at most {data['fault_budget']['max_faults_per_trial']} faults each. **{data['applied_fault_events']}/{data['requested_fault_events']} requested events** matched and were applied in exact selector order. For this check, **{data['target_after_fault']}/{trials} trials** reached the same region's check after the final fault; **{passed}/{trials} unchanged original JUnit runs passed**. The selected failure arm occurred in **{data['selected_target_exception_trials']}** valid trials. The six selected production classes covered {data['healthy_coverage']['total_branches']} branches in the healthy run and {data['fault_union_production_branches']} in the valid trial union (gain {data['coverage_gain']}). This result is for this JUnit workload, the observed I/O sequence, and the stated JaCoCo scope.

+The healthy preparation trace observed a `META` Get for each region. A `REGION_INFO` RegionServer RPC follows each region's three checks, and the first such RPC precedes the second region's checks. A separate uncounted `REGION_INFO:1:IOException` probe precisely applied the fault but then ended prepare before another selected check and failed the original JUnit. It was excluded from valid feedback. Two uncounted META calibrations confirmed retry after one and eight faults; their exact selector sequences were excluded from the {trials} formal trials. The first uncounted healthy startup exposed a probe visibility error, which was repaired before the counted healthy baseline.

+The shared [runner](../HBASE-13/native/run.sh), [ByteBuddy probe](../HBASE-13/native/src/HBase1315Agent.java), and [campaign](../HBASE-13/native/campaign.py) execute one unchanged original JUnit per fault plan, then separately record the three checks' post-fault reachability, exact guard result, original JUnit outcome, elapsed time, and production coverage in each [case ledger](result.json). The counted runtime used no GraphChecker JAR or prewoven classes, read no region skeleton or static scope map, and ran no GraphChecker static aggregate or closure. The [shared evidence archive](../HBASE-13/evidence/hbase13-15-native-evidence.tar.gz) includes per-trial logs and JaCoCo exec files; its [manifest](../HBASE-13/evidence/native-manifest.json) records SHA-256 hashes.

+Stop reason: {data.get('stop_reason', data['status'])}. The summed per-run elapsed time for this shared execution is {data['elapsed_seconds']:.2f} seconds, including the counted healthy run.
'''
    (case_path(number) / 'README.md').write_text(text.replace('\n+', '\n'))
