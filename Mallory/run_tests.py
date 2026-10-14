"""Run Mallory's native GraphChecker contract tests by default.

The archived custom-graph tests remain available with --legacy. This
entrypoint does not start a distributed-system campaign or rebuild the pinned
GraphChecker engine; build the source port before running native tests.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import unittest
from pathlib import Path


NATIVE_PACKAGES = (
    "native_graphchecker_feedback",
    "native_graphchecker_campaign",
    "native_graphchecker_dispatch",
    "native_graphchecker_queue",
    "native_fault_adapter",
)
NATIVE_ADAPTER_TEST_DIRS = (
    "adapters/hdfs/graphchecker_port/native_original",
    "adapters/hbase/native_graphchecker_port",
    "adapters/solr/native_graphchecker_port",
)
LEGACY_PACKAGES = ("core", "report")


def _suite(root: Path, packages: tuple[str, ...]) -> unittest.TestSuite:
    names = [f"Mallory.{package}.{path.stem}"
             for package in packages
             for path in sorted((root / package).glob("test_*.py"))]
    return unittest.defaultTestLoader.loadTestsFromNames(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", action="store_true",
                        help="run archived custom-graph core and report tests")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    packages = LEGACY_PACKAGES if args.legacy else NATIVE_PACKAGES
    result = unittest.TextTestRunner(verbosity=1).run(_suite(root, packages))
    passed = result.wasSuccessful()
    if not args.legacy:
        # These adapter tests import adjacent scripts by bare module name.
        # Isolate directories so similarly named modules cannot collide.
        for relative in NATIVE_ADAPTER_TEST_DIRS:
            directory = root / relative
            print(f"\nNative adapter tests: {relative}", file=sys.stderr,
                  flush=True)
            finished = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s",
                 str(directory), "-p", "test_*.py"],
                cwd=root.parent, check=False)
            passed = finished.returncode == 0 and passed
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
