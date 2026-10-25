"""One unchanged ZooKeeper 3.8.7 JUnit Jupiter method in a built source tree.

The test classpath is the one Surefire recorded when the tree's
``QuorumRestartTest`` ran once (``scripts/setup-deps.sh`` builds the tree
and runs it).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from .. import settings
from .base import (JUPITER_RUNNER, Request, agent_env, compile_runner, finish, fresh_scratch,
                   java, manifest, parse, require_agent, require_selection, run_junit)

SOURCE = settings.SOURCES / "zookeeper-3.8.7"
REPORT = (SOURCE / "zookeeper-server/target/surefire-reports/"
          "TEST-org.apache.zookeeper.test.QuorumRestartTest.xml")
BUILD = settings.BUILD / "zookeeper-junit"


def _test_classpath() -> str:
    properties = ET.parse(REPORT).getroot().findall("./properties/property")
    classpath = next(row.get("value") for row in properties
                     if row.get("name") == "java.class.path")
    first = classpath.split(os.pathsep, 1)[0]
    marker = "/zookeeper-server/target/test-classes"
    if marker not in first:
        raise ValueError("Surefire classpath lacks ZooKeeper test classes")
    # The report may come from a tree built elsewhere: re-root it here.
    return classpath.replace(first.split(marker, 1)[0], str(SOURCE))


def run(request: Request) -> int:
    require_selection(request)
    worker_id = (request.worker_id if request.worker_id is not None else
                 int(request.case_id.rsplit("-", 1)[1]) % request.worker_count)
    scratch = fresh_scratch(request.output, "temp")
    agent = require_agent()
    classpath = os.pathsep.join([str(BUILD), _test_classpath()])
    compile_runner(JUPITER_RUNNER, classpath, BUILD)
    command = [java("java"), "-ea", "-Xmx1g", "-Djava.awt.headless=true",
               "-Dsun.reflect.noInflation=true",
               "-Djava.io.tmpdir=" + str(scratch / "temp"),
               "-Dbuild.test.dir=" + str(scratch / "test-data"),
               "-Dtest.junit.threads=" + str(request.worker_count),
               "-Dzookeeper.junit.threadid=" + str(worker_id),
               "-javaagent:" + str(agent), "-cp", classpath, JUPITER_RUNNER,
               request.test_class, request.test_method]
    code, elapsed = run_junit(command, SOURCE / "zookeeper-server", agent_env(request), request)
    finish(request, manifest(request, code, elapsed), scratch)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(parse(argv, 180))
