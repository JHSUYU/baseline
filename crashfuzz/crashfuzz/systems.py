"""The four systems under test: their release, analysis jars and JUnit runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import settings


@dataclass(frozen=True)
class SystemSpec:
    name: str                       # the checklist's system prefix
    source_dir: str                 # under settings.SOURCES
    timeout: int                    # one JUnit run, seconds
    analysis_jars: tuple[str, ...]  # under settings.DEPS
    rpc_mappings: tuple[str, ...] = field(default=())   # under settings.SYSTEM_FILES

    @property
    def source(self) -> Path:
        return settings.SOURCES / self.source_dir

    def analysis(self) -> dict[str, Any]:
        """The Soot selector's input for this system's binaries."""
        jars = [settings.DEPS / jar for jar in self.analysis_jars]
        if self.name == "HBase":
            # Not every module is part of every 2.6 release.
            jars = [jar for jar in jars if jar.is_file()]
        if not jars or any(not jar.is_file() for jar in jars):
            raise FileNotFoundError(f"missing distribution jars for {self.name}: {jars}")
        return {"process_dirs": [str(jar) for jar in jars], "classpath": [],
                "rpc_mapping_files": [str(settings.SYSTEM_FILES / path)
                                      for path in self.rpc_mappings],
                "max_methods": 400, "post_call_rpc_enabled": True}


_HADOOP = "hadoop-3.4.3/share/hadoop"
SYSTEMS = {
    "HDFS": SystemSpec(
        "HDFS", "hadoop-3.4.3", 240,
        (f"{_HADOOP}/hdfs/hadoop-hdfs-3.4.3.jar", f"{_HADOOP}/hdfs/hadoop-hdfs-client-3.4.3.jar",
         f"{_HADOOP}/common/hadoop-common-3.4.3.jar"),
        ("hdfs/communication-mappings.jsonl",)),
    "HBase": SystemSpec(
        "HBase", "hbase-2.6.6", 300,
        tuple(f"hbase-2.6.6/lib/hbase-{module}-2.6.6.jar" for module in
              ("client", "server", "common", "procedure", "zookeeper", "protocol",
               "protocol-shaded", "replication", "master", "regionserver"))),
    "Solr": SystemSpec(
        "Solr", "solr-8.11.4", 600,
        ("solr-8.11.4/dist/solr-core-8.11.4.jar", "solr-8.11.4/dist/solr-solrj-8.11.4.jar")),
    "ZooKeeper": SystemSpec(
        "ZooKeeper", "zookeeper-3.8.7", 180,
        ("apache-zookeeper-3.8.7-bin/lib/zookeeper-3.8.7.jar",)),
}


def system_of(name: str) -> SystemSpec:
    """The spec for a checklist system label such as ``"HBase 2.6.6"``."""
    for prefix, spec in SYSTEMS.items():
        if name.startswith(prefix):
            return spec
    raise ValueError(f"unknown system: {name}")
