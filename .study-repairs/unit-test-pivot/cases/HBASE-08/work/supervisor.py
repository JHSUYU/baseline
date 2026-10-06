#!/usr/bin/env python3
"""Resume a crashed tmux campaign, then conditionally extend the same checkpoint."""
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
LOG = HERE / 'logs/supervisor.log'


def say(message):
    with LOG.open('a') as f:
        f.write(f'{time.time():.3f} {message}\n')


def session(name):
    return subprocess.run(['tmux', 'has-session', '-t', name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def tmux_start(name, command):
    if not session(name):
        subprocess.run(['tmux', 'new-session', '-d', '-s', name, command], check=True)


def late_novelty(trials):
    return any(x['strict'] and x['target_after_final_fault']
               and (x.get('new_production_methods', 0)
                    + x.get('new_production_branches', 0)
                    + x.get('new_io_selectors', 0) > 0)
               for x in trials[-16:])


def main():
    while True:
        if session('hbase08_fuzz'):
            time.sleep(10)
            continue
        try:
            state = json.loads((HERE / 'checkpoint.json').read_text())
            result = json.loads((CASE / 'result.json').read_text())
        except (OSError, ValueError):
            time.sleep(10)
            continue
        n = len(state['trials'])
        if result.get('status') == 'candidate_review':
            say(f'candidate_review after {n}; awaiting source review')
            return
        if not state['queue'] and not (n == 64 and late_novelty(state['trials'])):
            say(f'stop at {n}: candidate queue exhausted')
            return
        if n < 64:
            trials, faults = 64, 6
            say(f'resume interrupted campaign at {n}/64')
        elif n == 64 and late_novelty(state['trials']):
            trials, faults = 128, 8
            say('late production coverage or I/O novelty; extend 64/6 to 128/8')
        elif 64 < n < 128 and state.get('depth_expanded_to', 0) == 8:
            trials, faults = 128, 8
            say(f'resume interrupted extension at {n}/128')
        else:
            say(f'stop at {n}: no extension criterion or budget finished')
            return
        prefix = 'cd /users/ZhenyuLi/baseline && '
        command = (prefix + f'HBASE08_MAX_TRIALS={trials} HBASE08_MAX_FAULTS={faults} '
                   'python3 .study-repairs/unit-test-pivot/cases/HBASE-08/work/campaign.py '
                   '>> .study-repairs/unit-test-pivot/cases/HBASE-08/work/logs/campaign.log 2>&1; '
                   'echo $? > .study-repairs/unit-test-pivot/cases/HBASE-08/work/logs/campaign.exit')
        tmux_start('hbase08_fuzz', command)
        tmux_start('hbase08_watchdog', prefix +
                   'python3 .study-repairs/unit-test-pivot/cases/HBASE-08/work/watchdog.py')
        time.sleep(10)


if __name__ == '__main__':
    main()
