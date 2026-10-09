#!/usr/bin/env python3
"""Precompute a disjoint late block; the campaign admits it in order."""
import subprocess
import sys

from campaign import HERE, RUN, plans, plan_string


def main():
    all_plans = list(plans())
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 55
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 65
    assert 1 <= first < end <= 65
    for index in range(first, end):
        name = 'r%03d' % index
        exit_path = HERE / (name + '.exit')
        if exit_path.exists():
            continue
        plan = plan_string(all_plans[index - 1])
        with (HERE / (name + '.log')).open('w') as output:
            p = subprocess.run(['bash', str(RUN), 'run', name, plan],
                               stdout=output, stderr=subprocess.STDOUT)
        exit_path.write_text(str(p.returncode) + '\n')
        print('%s exit=%s plan=%s' % (name, p.returncode, plan), flush=True)


if __name__ == '__main__':
    main()
