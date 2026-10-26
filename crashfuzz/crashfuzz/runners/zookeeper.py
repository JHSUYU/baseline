"""One unchanged ZooKeeper 3.8.7 JUnit Jupiter method in a built source tree.

The test classpath is the one Surefire recorded when a test of the test's
module ran once: the test's own report when there is one (a recipe module's
test), else ``QuorumRestartTest``'s, which every zookeeper-server test shares
(``scripts/setup-deps.sh`` builds the tree and runs it).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import settings
from .base import (JUPITER_RUNNER, Request, agent_env, compile_runner, finish, fresh_scratch,
                   java, manifest, parse, require_agent, require_selection, run_junit)

SOURCE = settings.SOURCES / "zookeeper-3.8.7"
REPORT = (SOURCE / "zookeeper-server/target/surefire-reports/"
          "TEST-org.apache.zookeeper.test.QuorumRestartTest.xml")
BUILD = settings.BUILD / "zookeeper-junit"


def _module(test_class: str) -> Path:
    """The tree module whose tests hold ``test_class`` (zookeeper-server if none)."""
    relative = Path(*test_class.split(".")).with_suffix(".java")
    for tests in sorted(SOURCE.glob("**/src/test/java")):
        if (tests / relative).is_file():
            return tests.parents[2]
    return SOURCE / "zookeeper-server"


def _test_classpath(test_class: str) -> tuple[str, Path]:
    module = _module(test_class)
    report = module / "target/surefire-reports" / f"TEST-{test_class}.xml"
    if not report.is_file():
        report = REPORT
    properties = ET.parse(report).getroot().findall("./properties/property")
    classpath = next(row.get("value") for row in properties
                     if row.get("name") == "java.class.path")
    first = classpath.split(os.pathsep, 1)[0]
    marker = "/" + str(report.parents[2].relative_to(SOURCE)) + "/target/test-classes"
    if marker not in first:
        raise ValueError("Surefire classpath lacks the module's test classes")
    # The report may come from a tree built elsewhere: re-root it here.
    classpath = classpath.replace(first.split(marker, 1)[0], str(SOURCE))
    return classpath + _launcher(classpath), report.parents[2]


def _launcher(classpath: str) -> str:
    """The JUnit Platform launcher of the classpath's engine, when Surefire left it out.

    Surefire brings its own launcher, so a module's recorded classpath may lack
    one; the Jupiter runner needs the version matching junit-platform-engine.
    """
    jars = classpath.split(os.pathsep)
    if any("/junit-platform-launcher-" in jar for jar in jars):
        return ""
    engine = next((jar for jar in jars if "/junit-platform-engine-" in jar), None)
    if engine is None:
        return ""
    version = engine.rsplit("junit-platform-engine-", 1)[1][:-len(".jar")]
    launcher = (settings.M2 / "org/junit/platform/junit-platform-launcher" / version /
                f"junit-platform-launcher-{version}.jar")
    if not launcher.is_file():
        raise FileNotFoundError(f"JUnit Platform launcher {version} (scripts/setup-deps.sh): {launcher}")
    return os.pathsep + str(launcher)


def run(request: Request) -> int:
    require_selection(request)
    suffix = request.case_id.rsplit("-", 1)[-1]
    worker_id = (request.worker_id if request.worker_id is not None else
                 int(suffix) % request.worker_count if suffix.isdigit() else 0)
    scratch = fresh_scratch(request.output, "temp")
    agent = require_agent()
    test_classpath, module = _test_classpath(request.test_class)
    classpath = os.pathsep.join([str(BUILD), test_classpath])
    compile_runner(JUPITER_RUNNER, classpath, BUILD)
    command = [java("java"), "-ea", "-Xmx1g", "-Djava.awt.headless=true",
               "-Dsun.reflect.noInflation=true",
               "-Djava.io.tmpdir=" + str(scratch / "temp"),
               "-Dbuild.test.dir=" + str(scratch / "test-data"),
               "-Dtest.junit.threads=" + str(request.worker_count),
               "-Dzookeeper.junit.threadid=" + str(worker_id),
               "-javaagent:" + str(agent), "-cp", classpath, JUPITER_RUNNER,
               request.test_class, request.test_method]
    code, elapsed = run_junit(command, module, agent_env(request), request)
    finish(request, manifest(request, code, elapsed), scratch)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(parse(argv, 180))
