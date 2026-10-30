"""Where CrashFuzz finds its inputs and writes its results.

Every path can be overridden from the environment; the defaults are the
liftlab cluster's: ``/bigtemp/vnr3ne`` is NFS-mounted at the same path on
every lift (the home directory is NFS too, but under a quota, so nothing
bulky goes there; ``/localtmp`` is each lift's local disk).

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
import shutil
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]          # the crashfuzz/ directory
REPOSITORY = HOME.parent

DEPS = Path(os.environ.get("CRASHFUZZ_DEPS", "/bigtemp/vnr3ne/baseline-deps"))
SOURCES = Path(os.environ.get("CRASHFUZZ_SOURCES", str(DEPS / "sources")))
RESULTS = Path(os.environ.get("CRASHFUZZ_RESULTS", "/bigtemp/vnr3ne/crashfuzz-results"))
JAVA_HOME = Path(os.environ.get("CRASHFUZZ_JAVA_HOME", "/usr/lib/jvm/java-8-openjdk-amd64"))
JAVA_BIN = JAVA_HOME / "bin"
M2 = Path(os.environ.get("CRASHFUZZ_M2", "/bigtemp/vnr3ne/m2/crashfuzz"))
# The built source trees tree-mode rows name by a relative path (crashfuzz/tree.py).
TREES = Path(os.environ.get("CRASHFUZZ_TREES", "/bigtemp/vnr3ne/wt/bd-trees-1"))
# Maven: on PATH on some lifts, only under /usr/lib/maven on others.
MVN = os.environ.get("CRASHFUZZ_MVN") or shutil.which("mvn") or "/usr/lib/maven/bin/mvn"
# Generated runner classes (compiled launchers, unpacked test jars).
BUILD = Path(os.environ.get("CRASHFUZZ_BUILD", str(HOME / "build")))

AGENT_JAR = Path(os.environ.get(
    "CRASHFUZZ_RUNTIME_AGENT_JAR",
    str(HOME / "runtime-agent" / "target" / "crashfuzz-runtime-agent-0.1.0.jar")))
SELECTOR_DIR = HOME / "static-selection"
DATA = HOME / "data"
CHECKLIST = DATA / "checklist102.json"
SYSTEM_FILES = HOME / "systems"
