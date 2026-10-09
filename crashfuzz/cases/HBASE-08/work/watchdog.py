#!/usr/bin/env python3
"""End this case's trial after both original mini-cluster masters have aborted."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
LOG = HERE / 'logs/watchdog.log'


def campaign_alive():
    return subprocess.run(['tmux', 'has-session', '-t', 'hbase08_fuzz'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def own_java_pid(suffix):
    token = (HERE / ('data-' + suffix) / 'tmp').as_posix().encode()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / 'cmdline').read_bytes()
        except (OSError, PermissionError):
            continue
        parts = cmd.split(b'\0')
        if parts and parts[0].endswith(b'/java') and token in cmd and b'NativeJUnit' in parts:
            yield int(proc.name)


def main():
    handled = set()
    while campaign_alive():
        inflight_path = HERE / 'inflight.json'
        if inflight_path.exists():
            try:
                inflight = json.loads(inflight_path.read_text())
                suffix = inflight['id']
                trace = (HERE / 'logs' / (suffix + '.log')).read_text(errors='replace')
                aborted = set(re.findall(r'\*\*\*\*\* ABORTING master ([^: ]+)', trace))
                faults = trace.count('HBASE08 FAULT_APPLIED')
                if suffix not in handled and faults == len(inflight['plan']) and len(aborted) >= 2:
                    pids = list(own_java_pid(suffix))
                    if pids:
                        with LOG.open('a') as f:
                            f.write(f'{time.time():.3f} {suffix} both_masters_aborted '
                                    f'faults={faults} pids={pids}\n')
                        for pid in pids:
                            os.kill(pid, signal.SIGTERM)
                        handled.add(suffix)
            except (OSError, ValueError, KeyError):
                pass
        time.sleep(2)


if __name__ == '__main__':
    main()
