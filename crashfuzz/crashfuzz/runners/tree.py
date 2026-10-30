"""One JUnit method of a built source tree (a checklist row's ``tree``).

The workload (``tree-workload.json``, written by ``crashfuzz.tree``) holds
the classpath the tree's own test run stated, minus GraphChecker and with the
neutral adapter, the test's JUnit flavour and the JVM properties of the row.
The JVM runs in a fresh scratch directory under the run's output, never in
the tree, which is only read.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .. import settings
from ..tree import GRAPHCHECKER_PACKAGE, holds_package
from .base import (JUNIT4_RUNNER, JUPITER_RUNNER, Request, agent_env, compile_runner, finish,
                   fresh_scratch, java, manifest, require_agent, require_selection, run_junit)


def _jupiter_launcher(classpath: list[str]) -> list[str]:
    """The JUnit Platform launcher matching the classpath's engine, when the build left it out."""
    if any("/junit-platform-launcher-" in entry for entry in classpath):
        return []
    engine = next((entry for entry in classpath if "/junit-platform-engine-" in entry), None)
    if engine is None:
        raise FileNotFoundError("a Jupiter test without junit-platform-engine on its classpath")
    version = Path(engine).name[len("junit-platform-engine-"):-len(".jar")]
    launcher = (settings.M2 / "org/junit/platform/junit-platform-launcher" / version /
                f"junit-platform-launcher-{version}.jar")
    if not launcher.is_file():
        subprocess.run([settings.MVN, "-q",
                        "org.apache.maven.plugins:maven-dependency-plugin:3.6.1:get",
                        "-Dtransitive=false",
                        f"-Dartifact=org.junit.platform:junit-platform-launcher:{version}",
                        "-Dmaven.repo.local=" + str(settings.M2)], check=True,
                       env={**os.environ, "JAVA_HOME": str(settings.JAVA_HOME)})
    return [str(launcher)]


def command(workload: dict[str, Any], request: Request, scratch: Path) -> list[str]:
    """The workload JVM's argv: the tree's classpath, the agent, the row's properties."""
    classpath = list(workload["classpath"])
    # The neutral adapter names GraphChecker's classes but holds none of its code.
    adapter = (workload.get("adapter") or {}).get("directory")
    if any(holds_package(Path(entry), GRAPHCHECKER_PACKAGE) for entry in classpath
           if entry != adapter):
        raise ValueError("a tree workload's classpath must not hold GraphChecker")
    launcher = JUPITER_RUNNER if workload["launcher"] == "jupiter" else JUNIT4_RUNNER
    if launcher == JUPITER_RUNNER:
        classpath += _jupiter_launcher(classpath)
    junit = [entry for entry in classpath if "junit" in Path(entry).name]
    build = settings.BUILD / "tree-junit" / hashlib.sha256(
        os.pathsep.join([launcher, *junit]).encode()).hexdigest()[:16]
    compile_runner(launcher, os.pathsep.join(classpath), build,
                   lock=build.parent / f".{build.name}.lock")
    places = {"tmp": str(scratch / "tmp"), "data": str(scratch / "data"),
              "scratch": str(scratch), "tree": workload["tree"],
              "test_classes": workload.get("test_classes") or "",
              "systems": str(settings.SYSTEM_FILES),
              # Concurrent runs on one node: each its own worker id (a ZooKeeper
              # test's PortAssignment takes its port range from it).
              "worker": os.environ.get("CRASHFUZZ_WORKER_ID", "1"),
              "workers": os.environ.get("CRASHFUZZ_WORKER_COUNT", "1")}
    properties = [value.format_map(places) for value in workload["jvm_properties"]]
    return [java("java"), "-ea", "-Xmx" + workload["heap"], "-Djava.awt.headless=true",
            "-Dsun.reflect.noInflation=true", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
            "-Djava.io.tmpdir=" + places["tmp"], *properties,
            "-javaagent:" + str(require_agent()),
            "-cp", os.pathsep.join([str(build), *classpath]), launcher,
            request.test_class, request.test_method]


def run(request: Request) -> int:
    require_selection(request)
    workload = json.loads(request.tree.read_text())
    scratch = fresh_scratch(request.output, "tmp", "data", "work")
    argv = command(workload, request, scratch)
    code, elapsed = run_junit(argv, scratch / "work", agent_env(request), request)
    finish(request, manifest(request, code, elapsed, tree=workload["tree"],
                             tree_commit=workload.get("commit"),
                             classpath_sha256=workload.get("classpath_sha256"),
                             neutral_adapter_classes=len(workload.get("adapter", {})
                                                         .get("classes", [])),
                             graphchecker_runtime=False), scratch)
    return code
