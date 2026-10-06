#!/usr/bin/env python3
"""Resume the isolated MiniZK campaign and apply the conditional extension gate."""
import json
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
LOG = HERE / 'logs/supervisor.log'


def say(message):
    with LOG.open('a') as out:
        out.write(f'{time.time():.3f} {message}\n')


def running(name):
    return subprocess.run(['tmux', 'has-session', '-t', name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def start(effective, attempts, faults):
    command = ('cd /users/ZhenyuLi/baseline && '
               f'HBASE24_MAX_EFFECTIVE={effective} HBASE24_MAX_ATTEMPTS={attempts} '
               f'HBASE24_MAX_FAULTS={faults} '
               'python3 .study-repairs/unit-test-pivot/cases/HBASE-24/work/campaign.py '
               '>> .study-repairs/unit-test-pivot/cases/HBASE-24/work/logs/campaign.log 2>&1; '
               'echo $? > .study-repairs/unit-test-pivot/cases/HBASE-24/work/logs/campaign.exit')
    subprocess.run(['tmux', 'new-session', '-d', '-s', 'hbase24_fuzz', command], check=True)


def families(path):
    lines = path.read_text(errors='replace')
    return {'~'.join(x.split('~')[:3])
            for x in re.findall(r'HBASE24 IO seq=\d+ selector=(\S+)', lines)}


def late_novelty(state):
    seen = families(HERE / 'logs/multi_identity_healthy.log')
    admitted = [t for t in state['trials'] if t['effective']]
    for trial in admitted[:-16]:
        seen.update(families(CASE / trial['log']))
    for trial in admitted[-16:]:
        current = families(CASE / trial['log'])
        novel_family = bool(current - seen)
        seen.update(current)
        if trial.get('new_production_methods', 0) + trial.get('new_production_branches', 0) > 0 \
                or novel_family:
            return True
    return False


def main():
    last_attempts = -1
    repeated_failures = 0
    while True:
        if running('hbase24_fuzz'):
            time.sleep(10)
            continue
        try:
            state = json.loads((HERE / 'checkpoint.json').read_text())
            result = json.loads((CASE / 'result.json').read_text())
        except (OSError, ValueError):
            time.sleep(10)
            continue
        n = len(state['trials'])
        valid = sum(t['effective'] for t in state['trials'])
        if result['status'] == 'candidate_review':
            say(f'candidate after {n} attempts, {valid} effective; source review required')
            return
        if n == last_attempts:
            repeated_failures += 1
        else:
            repeated_failures = 0
        last_attempts = n
        if repeated_failures >= 3:
            say(f'stop after three restart failures at attempt {n}; inspect campaign.log')
            return
        if valid < 80 and n < 240 and state['queue']:
            say(f'resume {n} attempts, {valid}/80 effective, max depth eight')
            start(80, 240, 8)
        elif valid >= 80 and valid < 128 and state['queue'] and late_novelty(state):
            say(f'late novelty at {valid} effective; extend to 128/max10')
            start(128, 384, 10)
        elif 80 < valid < 128 and n < 384 and state['queue'] \
                and state.get('depth_expanded_to') == 10:
            say(f'resume {n} attempts, {valid}/128 effective, max depth ten')
            start(128, 384, 10)
        else:
            say(f'stop at {n} attempts, {valid} effective; budget, queue or extension gate')
            return
        time.sleep(10)


if __name__ == '__main__':
    main()
