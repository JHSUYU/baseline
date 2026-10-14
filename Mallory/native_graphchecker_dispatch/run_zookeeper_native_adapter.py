"""Invoke the pinned adapter from a queue attempt's isolated cwd."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Mallory.native_graphchecker_dispatch.zookeeper_native_adapter import main  # noqa: E402


if __name__ == "__main__":
    main()
