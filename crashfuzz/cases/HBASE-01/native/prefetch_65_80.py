#!/usr/bin/env python3
"""Run the added checkpoint's independent JVMs ahead of ordered ledger merge."""
from pathlib import Path
import subprocess

from campaign import HERE, RUN, extra_plans_to_80, plan_string


def main():
    for index, plan in enumerate(extra_plans_to_80(), 65):
        name = 'r%03d' % index
        exit_path = HERE / (name + '.exit')
        if exit_path.exists():
            continue
        log_path = HERE / (name + '.log')
        with log_path.open('w') as output:
            p = subprocess.run(['bash', str(RUN), 'run', name, plan_string(plan)],
                               stdout=output, stderr=subprocess.STDOUT)
        exit_path.write_text(str(p.returncode) + '\n')
        print('%s exit=%s plan=%s' % (name, p.returncode, plan_string(plan)), flush=True)


if __name__ == '__main__':
    main()
