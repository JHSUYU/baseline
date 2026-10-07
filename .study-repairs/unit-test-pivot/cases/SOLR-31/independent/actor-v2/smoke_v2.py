#!/usr/bin/env python3
"""Run receiver/path rejection and release-bytecode transform checks on node2."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    if not socket.gethostname().startswith('node2'):
        raise RuntimeError('node2 required')
    cp = str(HERE / 'classes') + ':' + original_classpath()
    results = []
    for assertions in ('-ea', '-da'):
        for name in ('OfflineSmoke', 'TransformSmoke'):
            trace = HERE / f'smoke-{assertions[1:]}-{name}.jsonl'
            command = [str(JAVA8 / 'java'), assertions,
                       '-Dsolrforce.trace.file=' + str(trace), '-cp', cp,
                       'research.solrforcev2.' + name]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            row = {'assertions': assertions, 'class': name,
                   'exit_code': result.returncode, 'stdout': result.stdout.strip(),
                   'stderr': result.stderr.strip()}
            results.append(row)
            if result.returncode != 0 or 'passed=' not in result.stdout:
                raise RuntimeError(json.dumps(row))
    receipt = {'hostname': socket.gethostname(), 'results': results}
    (HERE / 'offline-smoke-v2.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
