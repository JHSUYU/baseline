"""Where Mallory's inputs and outputs live; every value can be overridden from the environment.

Each system runs on its own GraphChecker checkout at ``MALLORY_GC_<SYSTEM>``:
GraphChecker's ``system/<system>-buggy-detect`` (liftlab) with this baseline's
patches (``graphchecker/apply.sh``, see README), against the system tree its cases
name, under ``TREES`` (GraphChecker's ``GC_TREES``): for the baseline bugs the fork's
``baseline/mallory`` branch (``graphchecker/trees.sh``), for the old bugs the
buggy-detect branches' own tree set. ``/bigtemp/vnr3ne`` is NFS-shared by every lift.
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
    checkout: Path       # the patched GraphChecker checkout (graphchecker/apply.sh)
    image: Path          # the concolic VM image (only GraphChecker's preflight reads it)
    # Every door family of the system's transports in GraphChecker's library
    # catalog, as scope entries: woven whatever the case's own scope reaches.
    doors: tuple[str, ...] = ()

    @property
    def jar(self) -> Path:
        return self.checkout / "target/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar"


SYSTEMS = {
    "hdfs": System("hdfs", Path(_env("MALLORY_GC_HDFS", "/bigtemp/vnr3ne/wt/gc-mallory-hdfs")),
                   Path(_env("MALLORY_IMAGE_HDFS", "/bigtemp/vnr3ne/vm-force12/j2sdk-image")),
                   ("common:org/apache/hadoop/ipc/Client",
                    "client:org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient",
                    "client:org/apache/hadoop/hdfs/protocol/datatransfer/Sender")),
    "hbase": System("hbase", Path(_env("MALLORY_GC_HBASE", "/bigtemp/vnr3ne/wt/gc-mallory-hbase")),
                    Path(_env("MALLORY_IMAGE_HBASE", "/bigtemp/vnr3ne/vm-force12/j2sdk-image")),
                    ("client:org/apache/hadoop/hbase/ipc/AbstractRpcClient",
                     "client:org/apache/hadoop/hbase/ipc/RpcConnection")),
    "solr": System("solr", Path(_env("MALLORY_GC_SOLR", "/bigtemp/vnr3ne/wt/gc-mallory-solr")),
                   Path(_env("MALLORY_IMAGE_SOLR", "/bigtemp/vnr3ne/vm-force10/j2sdk-image")),
                   ("solrj:org/apache/solr/client/solrj/impl/HttpSolrClient",
                    "solrj:org/apache/solr/client/solrj/impl/Http2SolrClient")),
    "zk": System("zk", Path(_env("MALLORY_GC_ZK", "/bigtemp/vnr3ne/wt/gc-mallory-zookeeper")),
                 Path(_env("MALLORY_IMAGE_ZK", "/bigtemp/vnr3ne/vm-force13/j2sdk-image")),
                 ("server:org/apache/zookeeper/ZooKeeper",)),
}

WORK = Path(_env("MALLORY_WORK", "/bigtemp/vnr3ne/mallory-work"))
# The system trees and their Maven repositories: GraphChecker's GC_TREES and GC_M2 on every call
TREES = Path(_env("MALLORY_GC_TREES", "/bigtemp/vnr3ne/wt/mallory-trees-1"))
M2 = Path(_env("MALLORY_GC_M2", "/bigtemp/vnr3ne/m2/mallory-1"))
# liftlab's workers (lift11 is the control host; lift07 and lift15 are out of use)
NODES = _env("MALLORY_NODES",
             "lift02 lift03 lift04 lift05 lift06 lift08 lift09 lift10 lift12 lift13 lift14").split()
JAVA = _env("MALLORY_JAVA", "/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
LOCAL_SCRATCH = _env("MALLORY_LOCAL_SCRATCH", "/localtmp/{user}/mallory")
# GraphChecker sizes a workload JVM's heap at half this (CAUSYNTH_HEAP_BASIS_MB); empty keeps its default
HEAP_BASIS_MB = _env("MALLORY_HEAP_BASIS_MB", "")


def system_of(case_id: str) -> System:
    prefix = case_id.split("-", 1)[0]
    if prefix not in SYSTEMS:
        raise ValueError(f"no system for case {case_id}")
    return SYSTEMS[prefix]
