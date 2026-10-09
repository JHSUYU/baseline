#!/usr/bin/env python3
"""Keep the SOLR-13 checklist row current while its tmux campaign runs."""

import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROGRESS = HERE / 'evidence/campaign/progress.json'
STAGE2_MIRROR = HERE.parent / 'stage2/evidence/campaign-node1-mirror/progress.json'
STAGE2_REMOTE = ('/users/ZhenyuLi/baseline/crashfuzz/'
                 'cases/SOLR-13/independent/stage2/evidence/campaign/progress.json')
TERMINAL = {'budget_complete', 'queue_exhausted',
            'candidate_target_exception', 'attempt_cap_exhausted'}


def stage2_progress():
    command = ['ssh', '-i', str(Path.home() / '.ssh/id_ed25519_nodes'),
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=5', 'ZhenyuLi@node1',
               'cat', STAGE2_REMOTE]
    try:
        remote = subprocess.run(command, capture_output=True, text=True,
                                timeout=8, check=True)
        parsed = json.loads(remote.stdout)
        if parsed.get('case_id') != 'SOLR-13' or parsed.get('phase') != 'overseer_alias_write':
            raise ValueError('unexpected remote progress identity')
        STAGE2_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        temp = STAGE2_MIRROR.with_suffix('.json.tmp')
        temp.write_text(json.dumps(parsed, indent=2, sort_keys=True) + '\n')
        temp.replace(STAGE2_MIRROR)
        return parsed
    except (OSError, subprocess.SubprocessError, ValueError) as failure:
        if STAGE2_MIRROR.is_file():
            print('SOLR13_STAGE2_MIRROR_STALE ' + str(failure), flush=True)
            return json.loads(STAGE2_MIRROR.read_text())
        return None


def main() -> None:
    previous = None
    was_live = True
    while True:
        if PROGRESS.is_file():
            progress = json.loads(PROGRESS.read_text())
            stage2 = stage2_progress()
            signature = (progress['attempted_plans'], progress['status'],
                         stage2 and stage2['attempted_plans'],
                         stage2 and stage2['status'])
            if signature != previous:
                subprocess.run(['python3', str(HERE / 'sync_result.py')],
                               check=True)
                previous = signature
            if (progress['status'] in TERMINAL and stage2 is not None
                    and stage2['status'] in TERMINAL):
                return
        live = subprocess.run(['tmux', 'has-session', '-t', 'solr13_fuzz'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
        if not live and was_live and progress['status'] not in TERMINAL:
            print('SOLR13_STAGE1_RUNNER_INTERRUPTED; checkpoint remains resumable',
                  flush=True)
        was_live = live
        time.sleep(15)


if __name__ == '__main__':
    main()
