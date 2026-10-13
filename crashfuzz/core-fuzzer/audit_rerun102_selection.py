#!/usr/bin/env python3
"""Verify that original-JUnit campaigns use their Soot-selected sites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from soot_selection import _validate_selection

ROOT = Path(__file__).resolve().parents[2]
INCOMPLETE = {'preparing', 'healthy', 'blocked_setup', 'claimed_elsewhere'}


def default_checklist() -> Path:
    for path in (ROOT / 'data/crashfuzz/checklist102.json',
                 ROOT / 'checklist102.json'):
        if path.is_file():
            return path
    return ROOT / 'data/crashfuzz/checklist102.json'


def applied_digests(trace: Path) -> list[str]:
    with trace.open() as stream:
        return [event.get('digest') for line in stream
                if (event := json.loads(line)).get('event') == 'STATIC_SELECTION_APPLIED']


def healthy_trace_path(manifest: dict, manifest_path: Path) -> Path:
    trace = Path(manifest['trace'])
    if trace.is_file():
        return trace
    # A case mirrored to another host retains its original absolute trace
    # path in the manifest.  The same trace is copied beside that manifest.
    relocated = manifest_path.parent / trace.name
    if relocated.is_file():
        return relocated
    return trace


def case_path(recorded: str | Path, base: Path) -> Path:
    """Resolve a path retained from another host after mirroring a case."""
    path = Path(recorded)
    if path.is_file():
        return path
    if base.name in path.parts:
        suffix = path.parts[path.parts.index(base.name) + 1:]
        relocated = base.joinpath(*suffix)
        if relocated.is_file():
            return relocated
    return path


def audit_runtime_scope(trace: Path, selection: dict) -> None:
    methods = set(selection['coverage_methods'])
    io_sites = {row['site_id'] for row in selection['io_calls']}
    coverage_events = {'METHOD_ENTER', 'METHOD_EXIT_NORMAL',
                       'METHOD_EXIT_THROW', 'BRANCH', 'CALL_SITE_ENTER',
                       'CALL_SITE_RETURN', 'CALL_SITE_THROW'}
    observed_selected_work = False
    with trace.open() as stream:
        for line in stream:
            event = json.loads(line)
            kind = event.get('event')
            if kind in coverage_events and event.get('method') not in methods:
                raise ValueError('runtime coverage escaped Soot method selection')
            if (kind == 'FAULT_POINT_OBSERVED' and
                    event.get('siteId') not in io_sites):
                raise ValueError('runtime I/O escaped Soot callsite selection')
            if kind in coverage_events or kind == 'FAULT_POINT_OBSERVED':
                observed_selected_work = True
    if not observed_selected_work:
        raise ValueError('healthy JUnit executed no Soot-selected work')


def audit(result_root: Path, checklist: Path) -> dict:
    original = {row['case_id']: row for row in json.loads(checklist.read_text())['rows']
                if row.get('selection_group') == 'original_102'}
    report = {'audited': 0, 'audited_cases': [], 'archived': 0,
              'incomplete': [], 'skipped': [],
              'errors': []}
    for cid, row in original.items():
        base = result_root / cid
        summary_path = base / 'case-summary.json'
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text())
            if summary['status'] == 'no_cluster_test':
                report['skipped'].append(cid)
                continue
            if summary['status'] in INCOMPLETE:
                report['incomplete'].append(cid)
                continue
            expanded = summary.get('selection_profile') == 'caller_expanded'
            artifact = (case_path(summary['selection_artifact'], base)
                        if summary.get('selection_artifact') else
                        base / ('caller-expanded/soot-selection.json' if expanded
                                else 'soot-selection.json'))
            selection = json.loads(artifact.read_text())
            target_site = row['exact_check_location']['site_id']
            target_method = target_site.split('#u', 1)[0]
            _validate_selection(selection, target_method)
            method_budget = (800 if summary.get('selection_profile') ==
                             'caller_expanded_800' else 400)
            if len(selection['coverage_methods']) > method_budget:
                raise ValueError('Soot selection exceeds its method budget')
            if selection.get('target_site_id') != target_site:
                raise ValueError('selected target site differs from checklist')
            if not selection['io_calls']:
                raise ValueError('Soot selected no I/O callsites')
            if (summary.get('static_io_calls') != len(selection['io_calls']) or
                    summary.get('static_coverage_methods') !=
                    len(selection['coverage_methods'])):
                raise ValueError('summary counts differ from Soot selection')
            healthy_manifest = (case_path(summary['healthy_manifest'], base)
                                if summary.get('healthy_manifest') else
                                base / ('healthy-expanded' if expanded else 'healthy') /
                                'manifest.json')
            manifest = json.loads(healthy_manifest.read_text())
            if manifest.get('returncode') != 0:
                raise ValueError('healthy JUnit did not pass')
            trace = healthy_trace_path(manifest, healthy_manifest)
            if applied_digests(trace) != [selection['input_digest']]:
                raise ValueError('runtime selection digest differs from Soot artifact')
            audit_runtime_scope(trace, selection)
            config = json.loads((base / 'campaign-config.json').read_text())
            if (case_path(config['static_selection']['artifact'], base).resolve() !=
                    artifact.resolve()):
                raise ValueError('campaign uses another selection artifact')
            manual_scope = {'io_scope', 'coverage_include_methods',
                            'coverage_include_prefixes'}
            if (manual_scope & config.keys() or
                    manual_scope & config['target'].keys()):
                raise ValueError('campaign declares case-specific I/O or coverage')
            states = [json.loads(path.read_text()) for path in
                      base.glob('campaign*/' + cid + '/state.json')]
            if states:
                if not any(state.get('static_selection_digest') == selection['input_digest']
                           for state in states):
                    raise ValueError('campaign checkpoint has no matching selection digest')
            else:
                receipt = json.loads((base / 'archive.json').read_text())
                final = json.loads((base / 'campaign-result.json').read_text())
                if (receipt.get('remote_path') != summary.get('archive_path') or
                        receipt.get('case_id') != cid or
                        final.get('static_selection_digest') != selection['input_digest']):
                    raise ValueError('archived campaign digest or receipt differs')
                report['archived'] += 1
            report['audited'] += 1
            report['audited_cases'].append(cid)
        except (OSError, KeyError, TypeError, ValueError) as error:
            report['errors'].append({'case_id': cid, 'error': str(error)})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--result-root', required=True, type=Path)
    parser.add_argument('--checklist', type=Path,
                        default=default_checklist())
    args = parser.parse_args()
    report = audit(args.result_root, args.checklist)
    print(json.dumps(report, indent=2))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
