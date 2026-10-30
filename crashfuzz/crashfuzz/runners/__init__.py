"""Per-system runners of one original JUnit method under the CrashFuzz agent.

A ``--tree`` workload (a built source tree) runs through ``tree`` instead.

``python3 -m crashfuzz.runners <System> --case-id ... --test-class ...``
"""

from __future__ import annotations

import importlib

MODULES = {"HDFS": "hdfs", "HBase": "hbase", "Solr": "solr", "ZooKeeper": "zookeeper"}


def main(system: str, argv: list[str]) -> int:
    if "--tree" in argv:
        # A built source tree's workload (crashfuzz.tree), whatever the system.
        from . import base, tree
        return tree.run(base.parse(argv, 300))   # the worker passes --timeout
    module = importlib.import_module(f"{__name__}.{MODULES[system]}")
    return module.main(argv)
