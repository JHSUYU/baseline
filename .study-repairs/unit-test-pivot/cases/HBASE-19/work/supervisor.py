#!/usr/bin/env python3
"""Restart the isolated campaign after interruption; extend only for late novelty."""
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


def start(trials, faults):
    command = ('cd /users/ZhenyuLi/baseline && '
               f'HBASE1920_MAX_TRIALS={trials} HBASE1920_MAX_FAULTS={faults} '
               'python3 .study-repairs/unit-test-pivot/cases/HBASE-19/work/campaign.py '
               '>> .study-repairs/unit-test-pivot/cases/HBASE-19/work/logs/campaign.log 2>&1; '
               'echo $? > .study-repairs/unit-test-pivot/cases/HBASE-19/work/logs/campaign.exit')
    subprocess.run(['tmux', 'new-session', '-d', '-s', 'hbase1920_fuzz', command], check=True)


def families(path):
    lines = path.read_text(errors='replace')
    return {x.split('~', 1)[0]
            for x in re.findall(r'HBASE1920 IO seq=\d+ selector=(\S+)', lines)}


def late_novelty(state):
    seen = families(HERE / 'logs/healthy3.log')
    trials = state['trials']
    for trial in trials[:-16]:
        if trial['strict'] and (trial['post19'] or trial['post20']):
            seen.update(families(CASE / trial['log']))
    for trial in trials[-16:]:
        if not (trial['strict'] and (trial['post19'] or trial['post20'])):
            continue
        current = families(CASE / trial['log'])
        novel_family = bool(current - seen)
        seen.update(current)
        if trial.get('new_production_methods', 0) + trial.get('new_production_branches', 0) > 0 \
                or novel_family:
            return True
    return False


def main():
    while True:
        if running('hbase1920_fuzz'):
            time.sleep(10)
            continue
        try:
            state = json.loads((HERE / 'checkpoint.json').read_text())
            result = json.loads((CASE / 'result.json').read_text())
        except (OSError, ValueError):
            time.sleep(10)
            continue
        n = len(state['trials'])
        if result['status'] == 'candidate_review':
            say(f'candidate at {n}; source review required')
            return
        if n < 80 and state['queue']:
            say(f'resume {n}/80, max depth eight')
            start(80, 8)
        elif n == 80 and state['queue'] and late_novelty(state):
            say('late production coverage or stable I/O family; extend 128/10')
            start(128, 10)
        elif 80 < n < 128 and state['queue'] and state.get('depth_expanded_to') == 10:
            say(f'resume {n}/128, max depth ten')
            start(128, 10)
        else:
            say(f'stop at {n}; budget, queue, or extension gate complete')
            return
        time.sleep(10)


if __name__ == '__main__':
    main()
