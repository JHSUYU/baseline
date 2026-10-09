#!/usr/bin/env python3
"""Read-only final provenance and exact-target audit for SOLR-18."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

import campaign


def main():
    state = json.loads(campaign.STATE.read_text())
    baseline = json.loads((campaign.HERE / 'healthy-baseline.json').read_text())
    expanded = json.loads((campaign.HERE / 'expanded-io-baseline.json').read_text())
    inspected = []
    problems = []
    failures = Counter()
    failure_details = []
    exact_throws = []
    for item in state['trials']:
        run_id = item['run_id']
        phase = 1 if int(run_id.split('-')[-1]) <= 15 else 2
        root = campaign.RUN_ROOT / run_id
        manifest = json.loads((root / 'run.json').read_text())
        trace = campaign.events(run_id)
        matches = [campaign.selector(row) for row in trace if row[1] == 'FAULT_MATCHED']
        applied = [row for row in trace if row[1] == 'FAULT_APPLIED']
        selected = campaign.selected_guard(trace)
        last = applied[-1][0] if applied else 0
        strict = matches == item['plan'] and [campaign.selector(row) for row in applied] == item['plan']
        retained = strict and selected is not None and selected[0] > last
        guard = next((row for row in reversed(trace) if row[1] == 'TARGET_GUARD'
                      and selected is not None and row[0] < selected[0]
                      and row[2] == selected[2] and row[3] == selected[3][:6]), None)
        if manifest['original_source_commit'] != baseline['source_revision']:
            problems.append((run_id, 'source revision drift'))
        if manifest['original_solrj_jar_sha256'] != baseline['solrj_jar_sha256']:
            problems.append((run_id, 'original SolrJ JAR drift'))
        if manifest['original_core_jar_sha256'] != baseline['core_jar_sha256']:
            problems.append((run_id, 'original Core JAR drift'))
        if manifest['overlay_alias_manager_sha256'] != baseline['overlay_alias_manager_sha256']:
            problems.append((run_id, 'selected ASM target overlay drift'))
        if manifest['overlay_solr_zk_client_sha256'] != baseline['overlay_solr_zk_client_sha256']:
            problems.append((run_id, 'I/O ASM overlay drift'))
        expected_probe = baseline['probe_class_sha256'] if phase == 1 else expanded['probe_class_sha256']
        if manifest['probe_class_sha256'] != expected_probe:
            problems.append((run_id, 'phase recorder drift'))
        if manifest['classpath_has_graphchecker_or_skeleton_jar']:
            problems.append((run_id, 'forbidden runtime JAR'))
        if manifest['test'] != 'org.apache.solr.cloud.AliasIntegrationTest#testProperties':
            problems.append((run_id, 'test mapping drift'))
        if manifest['plan'] != item['plan']:
            problems.append((run_id, 'manifest plan drift'))
        if (item['strict_ordered_injection'], item['selected_equal_check_after_final_fault']) != (strict, retained):
            problems.append((run_id, 'strict/target-retained ledger mismatch'))
        if retained and (guard is None or guard[0] <= last):
            problems.append((run_id, 'target guard missing after final fault'))
        if not manifest['elapsed_seconds'] > 0 or manifest['test_started_count'] != 1:
            problems.append((run_id, 'invalid elapsed time or missing test start'))
        if manifest['assumption_failure_count']:
            problems.append((run_id, 'assumption skip'))
        if selected is not None and selected[3][6] == 'false':
            exact_throws.append((run_id, 'unequal JSON at selected check'))
        for row in trace:
            if row[1] == 'TARGET_THROW':
                exact_throws.append((run_id, row[3]))
        text = (root / 'console.log').read_text(errors='replace')
        if 'SOLR18_PROBE_WRITE_ERROR' in text:
            problems.append((run_id, 'recorder write error during trial'))
        if not (root / 'covered_probes.txt').exists():
            problems.append((run_id, 'missing production coverage feedback'))
        summary = re.search(r'SOLR18_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', text)
        if summary is None or summary.group(1) != '1' or summary.group(2) != '0':
            problems.append((run_id, 'missing/incomplete JUnit summary'))
        if manifest['junit_exit'] != 0:
            block = re.search(
                r'(?m)^testProperties\(org\.apache\.solr\.cloud\.AliasIntegrationTest\)\n'
                r'([^\n]+)([\s\S]*?)SOLR18_ORIGINAL_JUNIT', text)
            if block is None:
                category, headline, direct = 'missing_junit_failure_block', '', False
            else:
                headline = block.group(1)
                direct = 'research.solr18.Solr18Probe.aliasIo' in block.group(2)
                if 'KeeperException$ConnectionLossException' in headline:
                    category = 'direct_keeper_connection_loss'
                elif 'KeeperErrorCode = ConnectionLoss' in headline:
                    category = 'remote_connection_loss'
                elif 'Error reading cluster property' in headline:
                    category = 'remote_cluster_property_read_error'
                elif 'Timeout waiting for active collection' in headline:
                    category = 'remote_collection_activation_timeout'
                elif 'SolrServerException: Timeout occurred' in headline:
                    category = 'client_http_response_timeout'
                elif 'Could not load collection from ZK' in headline or 'Error inc and get counter' in headline or 'Underlying core creation failed' in headline:
                    category = 'remote_collection_setup_error'
                elif 'RemoteSolrException' in headline and 'org.apache.solr.common.SolrException' in headline:
                    category = 'remote_solr_exception'
                else:
                    category = 'other_failure_requires_review'
            failures[category] += 1
            failure_details.append({'run_id': run_id, 'category': category,
                                    'junit_headline': headline,
                                    'probe_in_junit_failure_stack': direct})
            if category in ('missing_junit_failure_block', 'other_failure_requires_review'):
                problems.append((run_id, category))
        inspected.append({'run_id': run_id, 'phase': phase,
                          'fault_count': item['fault_count'], 'strict': strict,
                          'same_body_target_after_fault': retained,
                          'target_json_equal': selected[3][6] if selected else None,
                          'junit_exit': manifest['junit_exit'],
                          'elapsed_seconds': manifest['elapsed_seconds']})
    report = {'inspected_trials': len(inspected), 'strict_trials': sum(x['strict'] for x in inspected),
              'effective_trials': sum(x['same_body_target_after_fault'] for x in inspected),
              'maximum_fault_depth': max((x['fault_count'] for x in inspected), default=0),
              'exact_target_throw_candidates': exact_throws,
              'junit_nonzero_source_categories': dict(failures),
              'junit_nonzero_details': failure_details,
              'audit_problems': problems, 'trials': inspected}
    out = campaign.HERE / 'evidence/final-audit.json'
    campaign.atomic_json(out, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'trials'}, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
