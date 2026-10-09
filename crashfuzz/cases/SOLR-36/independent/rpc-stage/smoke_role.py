#!/usr/bin/env python3
"""Run no-cluster identity assertions against the compiled case-local probe."""

from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    cp = ':'.join((str(HERE / 'agent-classes'), original_classpath()))
    subprocess.run((str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(HERE / 'agent-classes'),
                    str(HERE / 'RoleIdentitySmoke.java')), check=True)
    subprocess.run((str(JAVA8 / 'java'), '-cp', cp,
                    'research.solrsubshard.RoleIdentitySmoke'), check=True)


if __name__ == '__main__':
    main()
