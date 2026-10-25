"""One unchanged Hadoop 3.4.3 MiniDFSCluster JUnit 4 method.

Without a static selection the run is a JaCoCo coverage calibration;
with one, the CrashFuzz agent observes (and in a trial injects) faults.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from .. import settings
from .base import (JUNIT4_RUNNER, Request, agent_env, compile_runner, finish, fresh_scratch,
                   java, parse, require_agent, run_junit)

HADOOP = settings.DEPS / "hadoop-3.4.3"
TESTS_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
TEST_RESOURCES = settings.SOURCES / "hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources"
BUILD = settings.BUILD / "hdfs-junit"
TEST_CLASSES = settings.BUILD / "hdfs-test-classes"
JACOCO = settings.M2 / "org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar"
M2_EXTRAS = ("org/apache/hadoop/hadoop-minikdc/3.4.3/hadoop-minikdc-3.4.3.jar",
             "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
             "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
             "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
             "org/objenesis/objenesis/3.3/objenesis-3.3.jar")


def _unpack_test_classes() -> None:
    """Some tests call KeyStoreTestUtil.getClasspathDir(), which needs a
    ``file:`` class resource, so the tests jar is also unpacked."""
    stamp = f"{TESTS_JAR.stat().st_size}:{TESTS_JAR.stat().st_mtime_ns}"
    marker = TEST_CLASSES / ".source-jar"
    settings.BUILD.mkdir(parents=True, exist_ok=True)
    with (settings.BUILD / ".hdfs-test-classes.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not marker.exists() or marker.read_text() != stamp:
            shutil.rmtree(TEST_CLASSES, ignore_errors=True)
            TEST_CLASSES.mkdir(parents=True)
            with zipfile.ZipFile(TESTS_JAR) as archive:
                archive.extractall(TEST_CLASSES)
            marker.write_text(stamp)


def _classpath(env: dict[str, str]) -> str:
    hadoop = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                     env=env, text=True).strip()
    kerby = sorted(path for path in (settings.M2 / "org/apache/kerby").glob("*/2.0.3/*.jar")
                   if path.name == path.parent.parent.name + "-2.0.3.jar")
    classpath = os.pathsep.join([
        str(BUILD), str(TEST_CLASSES), str(TEST_RESOURCES), str(TESTS_JAR),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"), hadoop,
        *(str(settings.M2 / extra) for extra in M2_EXTRAS), *(str(path) for path in kerby),
        *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])
    assert not any(("graphchecker" in part.lower() or "causynth" in part.lower()) and
                   part.lower().endswith(".jar") for part in classpath.split(os.pathsep))
    return classpath


def run(request: Request) -> int:
    compile_runner(JUNIT4_RUNNER, str(HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"), BUILD)
    _unpack_test_classes()
    scratch = fresh_scratch(request.output, "data", "tmp", "logs")
    env = agent_env(request)
    classpath = _classpath(env)
    command = [java("java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Dtest.cache.data=" + str(TEST_RESOURCES),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs")]
    if request.static_selection:
        command.append("-javaagent:" + str(require_agent()))
    else:
        command.append("-javaagent:" + str(JACOCO) + "=destfile=" +
                       str(request.output / "jacoco.exec") +
                       ",includes=org.apache.hadoop.hdfs.*,dumponexit=true,append=false")
    command += ["-cp", classpath, JUNIT4_RUNNER, request.test_class, request.test_method]
    code, elapsed = run_junit(command, scratch, env, request)
    finish(request, {
        "case_id": request.case_id,
        "cluster_test": request.test_class + "#" + request.test_method,
        "returncode": code, "elapsed_seconds": elapsed,
        "classpath_sha256": hashlib.sha256(classpath.encode()).hexdigest(),
        "original_test_jar_sha256": hashlib.sha256(TESTS_JAR.read_bytes()).hexdigest(),
        "jacoco_exec": None if request.static_selection else str(request.output / "jacoco.exec"),
        "junit_log": str(request.output / "junit.log"),
        "graphchecker_runtime": False,
        "target_probe": bool(request.static_selection),
        "trace": (str(request.output / "runtime_trace.jsonl")
                  if request.static_selection else None)}, scratch)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(parse(argv, 180))
