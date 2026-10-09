#!/usr/bin/env python3
"""Wait for SOLR-07 V4's natural end, audit its raw data, then start V5.

Run this in its own tmux session. Any failed gate is fatal and leaves the
checkpoint untouched, except for immutable evidence already frozen/audited.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import campaign_v2 as v2
import campaign_v5 as v5


LOG = Path(__file__).with_name('handoff-v5-supervisor.jsonl')


def record(event: str, **data: object) -> None:
    row = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'event': event, **data}
    with LOG.open('a') as output:
        output.write(json.dumps(row, sort_keys=True) + '\n')
        output.flush()
    print(json.dumps(row, sort_keys=True), flush=True)


def main() -> None:
    record('waiting_for_v4_natural_stop')
    while True:
        state = json.loads(v2.STATE.read_text())
        if state.get('stopped'):
            break
        time.sleep(15)
    if state.get('stop_reason') not in {'queue_exhausted',
                                         'effective_budget_met',
                                         'selected_trial_cap'}:
        raise RuntimeError(f'V4 stop is not natural: {state.get("stop_reason")}')
    record('v4_checkpoint_stopped', selected=state['selected_count'],
           effective=state['effective_count'], reason=state['stop_reason'])

    # A final checkpoint can be written just before V4 exits. Wait for its
    # process and any target JUnit to leave; keep all validation in freeze().
    for _ in range(40):
        try:
            v5.no_v4_process()
            break
        except RuntimeError:
            time.sleep(15)
    else:
        raise RuntimeError('V4/JUnit still alive ten minutes after stop')

    frozen = v5.freeze()
    record('frozen', selected=frozen['selected'], snapshot=frozen['snapshot'],
           manifest=frozen['manifest'], sha256=frozen['checkpoint_sha256'])
    audit = Path(frozen['snapshot']).with_name(
        Path(frozen['snapshot']).name.replace('state-', 'audit-'))
    subprocess.run([sys.executable, 'audit_v2_checkpoint.py',
                    '--state', frozen['snapshot'], '--output', str(audit)],
                   check=True)
    result = json.loads(audit.read_text())
    if result['errors'] or result['selected'] != frozen['selected'] or \
            result['effective'] != state['effective_count']:
        raise RuntimeError('independent raw audit disagrees with frozen V4')
    audit.chmod(0o444)
    record('audited', selected=result['selected'], effective=result['effective'],
           strict=result['strict'], exact_target_throws=result['exact_target_throws'],
           errors=result['errors'], audit=str(audit))

    # The V4 queue has low actor-retention; V5 exhaustively backfills the
    # productive parents with a fixed selected cap and 8-fault depth.
    effective_budget = max(80, result['effective'] + 1)
    selected_cap = max(512, result['selected'] + 1)
    fault_depth = max(8, state['budget']['max_faults'])
    record('activating', effective_budget=effective_budget,
           selected_cap=selected_cap, fault_depth=fault_depth)
    v5.activate(Path(frozen['snapshot']), Path(frozen['manifest']), audit,
                effective_budget, selected_cap, fault_depth, backfill_cap=512)
    record('v5_runner_returned')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        record('failed_closed', error=repr(error))
        raise
