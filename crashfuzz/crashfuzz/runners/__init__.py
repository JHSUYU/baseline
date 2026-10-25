"""Per-system runners of one original JUnit method under the CrashFuzz agent.

``python3 -m crashfuzz.runners <System> --case-id ... --test-class ...``
"""

from __future__ import annotations

import importlib

MODULES = {"HDFS": "hdfs", "HBase": "hbase", "Solr": "solr", "ZooKeeper": "zookeeper"}


def main(system: str, argv: list[str]) -> int:
    module = importlib.import_module(f"{__name__}.{MODULES[system]}")
    return module.main(argv)
