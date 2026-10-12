"""Run Mallory tests under their canonical namespace package names."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    names = [f"Mallory.{package}.{path.stem}"
             for package in ("core", "report")
             for path in sorted((root / package).glob("test_*.py"))]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner().run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
