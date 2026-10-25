"""Where Mallory's inputs and outputs live; every value can be overridden from the environment.

Each system runs on its own GraphChecker branch ``baseline/mallory-<system>``
(``system/<system>-cloudlab`` plus native plant runs, see README) checked out
at ``MALLORY_GC_<SYSTEM>``, against the system tree its cases name (the fork's
``graphchecker/*-checks`` branch, built under ``GC_TREES``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class System:
    name: str
    checkout: Path       # the GraphChecker baseline/mallory-<name> checkout
    image: Path          # the concolic VM image (only GraphChecker's preflight reads it)

    @property
    def jar(self) -> Path:
        return self.checkout / "target/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar"


SYSTEMS = {
    "hdfs": System("hdfs", Path(_env("MALLORY_GC_HDFS", "/bulk/wt/gc-mallory-hdfs")),
                   Path(_env("MALLORY_IMAGE_HDFS", "/bulk/vm/hbase/j2sdk-image"))),
    "hbase": System("hbase", Path(_env("MALLORY_GC_HBASE", "/bulk/wt/gc-mallory-hbase")),
                    Path(_env("MALLORY_IMAGE_HBASE", "/bulk/vm/hbase/j2sdk-image"))),
    "solr": System("solr", Path(_env("MALLORY_GC_SOLR", "/bulk/wt/gc-mallory-solr")),
                   Path(_env("MALLORY_IMAGE_SOLR", "/bulk/vm/solr/j2sdk-image"))),
}

WORK = Path(_env("MALLORY_WORK", "/bulk/mallory-work"))
NODES = _env("MALLORY_NODES", "node0 node1 node2 node3 node4").split()
JAVA = _env("MALLORY_JAVA", "/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
LOCAL_SCRATCH = _env("MALLORY_LOCAL_SCRATCH", "/localtmp/{user}/mallory")


def system_of(case_id: str) -> System:
    prefix = case_id.split("-", 1)[0]
    if prefix not in SYSTEMS:
        raise ValueError(f"no system for case {case_id}")
    return SYSTEMS[prefix]
