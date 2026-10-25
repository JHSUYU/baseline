"""Where CrashFuzz finds its inputs and writes its results.

Every path can be overridden from the environment; the defaults are the
CloudLab cluster's (``/bulk`` is NFS-shared by every node).

``CRASHFUZZ_DEPS`` holds the Apache release binaries the original JUnit tests
run on and their sources (``scripts/setup-deps.sh`` makes it)::

    $CRASHFUZZ_DEPS/hadoop-3.4.3/            $CRASHFUZZ_DEPS/sources/hadoop-3.4.3/
    $CRASHFUZZ_DEPS/hadoop-2.10.0/           $CRASHFUZZ_DEPS/sources/hbase-2.6.6/
    $CRASHFUZZ_DEPS/hbase-2.6.6/             $CRASHFUZZ_DEPS/sources/solr-8.11.4/
    $CRASHFUZZ_DEPS/solr-8.11.4/             $CRASHFUZZ_DEPS/sources/zookeeper-3.8.7/
    $CRASHFUZZ_DEPS/apache-zookeeper-3.8.7-bin/
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]          # the crashfuzz/ directory
REPOSITORY = HOME.parent

DEPS = Path(os.environ.get("CRASHFUZZ_DEPS", "/bulk/baseline-deps"))
SOURCES = Path(os.environ.get("CRASHFUZZ_SOURCES", str(DEPS / "sources")))
RESULTS = Path(os.environ.get("CRASHFUZZ_RESULTS", "/bulk/crashfuzz-results"))
JAVA_HOME = Path(os.environ.get("CRASHFUZZ_JAVA_HOME", "/usr/lib/jvm/java-8-openjdk-amd64"))
JAVA_BIN = JAVA_HOME / "bin"
M2 = Path(os.environ.get("CRASHFUZZ_M2", str(Path.home() / ".m2" / "repository")))
# Generated runner classes (compiled launchers, unpacked test jars).
BUILD = Path(os.environ.get("CRASHFUZZ_BUILD", str(HOME / "build")))

AGENT_JAR = Path(os.environ.get(
    "CRASHFUZZ_RUNTIME_AGENT_JAR",
    str(HOME / "runtime-agent" / "target" / "crashfuzz-runtime-agent-0.1.0.jar")))
SELECTOR_DIR = HOME / "static-selection"
DATA = HOME / "data"
CHECKLIST = DATA / "checklist102.json"
SYSTEM_FILES = HOME / "systems"
