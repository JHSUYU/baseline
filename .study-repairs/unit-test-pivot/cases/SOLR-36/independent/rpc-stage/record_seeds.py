#!/usr/bin/env python3
"""Record two independent healthy executions of the original split JUnit."""

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from run import run  # noqa: E402
sys.path.insert(0, str(HERE))
from seed_audit import main as audit  # noqa: E402


def main() -> None:
    agent = HERE / 'solrsubshard-rpc-agent.jar'
    for number in (1, 2):
        out = HERE / f'healthy-sender-{number:02d}'
        if not (out / 'run.json').is_file():
            code = run(out, agent_path=agent)
            if code:
                raise RuntimeError(f'healthy JUnit {number} exited {code}')
    audit()


if __name__ == '__main__':
    main()
