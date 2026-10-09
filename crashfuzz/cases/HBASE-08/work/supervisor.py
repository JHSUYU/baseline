#!/usr/bin/env python3
"""Resume a crashed tmux campaign, then conditionally extend the same checkpoint."""
import json
from pathlib import Path
import re
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


def io_sites(log_path):
    text = log_path.read_text(errors='replace')
    selectors = re.findall(r'HBASE08 IO seq=\d+ selector=(\S+)', text)
    # The hit ordinal locates an exact runtime event but repeated retries of
    # the same call site and znode are not new I/O points for feedback.
    return {'~'.join(selector.split('~')[:3]) for selector in selectors}


def io_families(log_path):
    return {site.split('~', 1)[0] for site in io_sites(log_path)}


def late_novelty(state):
    healthy = io_families(HERE / 'logs/healthy2.log')
    seen = set(healthy)
    trials = state['trials']
    for trial in trials[:-16]:
        if trial['strict'] and trial['target_after_final_fault']:
            seen.update(io_families(CASE / trial['log']))
    for trial in trials[-16:]:
        if not (trial['strict'] and trial['target_after_final_fault']):
            continue
        current = io_families(CASE / trial['log'])
        novel_family = bool(current - seen)
        seen.update(current)
        if (trial.get('new_production_methods', 0)
                + trial.get('new_production_branches', 0) > 0 or novel_family):
            return True
    return False


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
        if not state['queue'] and not (n == 80 and late_novelty(state)):
            say(f'stop at {n}: candidate queue exhausted')
            return
        if n < 80:
            trials, faults = 80, 8
            say(f'resume or extend campaign at {n}/80 with eight-fault depth')
        elif n == 80 and late_novelty(state):
            trials, faults = 128, 10
            say('late production coverage or stable I/O family; extend 80/8 to 128/10')
        elif 80 < n < 128 and state.get('depth_expanded_to', 0) == 10:
            trials, faults = 128, 10
            say(f'resume interrupted extension at {n}/128')
        else:
            say(f'stop at {n}: no extension criterion or budget finished')
            return
        prefix = 'cd /users/ZhenyuLi/baseline && '
        command = (prefix + f'HBASE08_MAX_TRIALS={trials} HBASE08_MAX_FAULTS={faults} '
                   'python3 crashfuzz/cases/HBASE-08/work/campaign.py '
                   '>> crashfuzz/cases/HBASE-08/work/logs/campaign.log 2>&1; '
                   'echo $? > crashfuzz/cases/HBASE-08/work/logs/campaign.exit')
        tmux_start('hbase08_fuzz', command)
        tmux_start('hbase08_watchdog', prefix +
                   'python3 crashfuzz/cases/HBASE-08/work/watchdog.py')
        time.sleep(10)


if __name__ == '__main__':
    main()
