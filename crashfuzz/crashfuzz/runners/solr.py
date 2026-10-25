"""One unchanged Solr 8.11.4 cluster JUnit 4 method, compiled from its source."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .. import settings
from .base import (JAVA_SOURCES, JUNIT4_RUNNER, Request, agent_env, finish, fresh_scratch,
                   java, manifest, parse, require_agent, require_selection, run_junit)

SOURCE = settings.SOURCES / "solr-8.11.4"
DIST = settings.DEPS / "solr-8.11.4"
TEST_ROOTS = ("solr/core/src/test", "solr/solrj/src/test")
SEED = "F0993D5343E20BA4"


def _classpath(classes: Path) -> str:
    dist = DIST / "dist"
    paths = [classes, SOURCE / "solr/core/src/test-files",
             dist / "solr-test-framework-8.11.4.jar", dist / "solr-core-8.11.4.jar",
             dist / "solr-solrj-8.11.4.jar", dist / "solr-analysis-extras-8.11.4.jar",
             SOURCE / "solr/solrj/src/test-files"]
    for group in (dist / "test-framework/lib", dist / "test-framework/lucene-libs",
                  DIST / "server/solr-webapp/webapp/WEB-INF/lib", DIST / "server/lib",
                  DIST / "server/lib/ext", DIST / "contrib/analysis-extras/lib",
                  DIST / "contrib/analysis-extras/lucene-libs"):
        paths.extend(sorted(group.glob("*.jar")))
    return os.pathsep.join(str(path) for path in paths if path.exists())


def _config_plugins() -> list[Path]:
    """Test classes the test configs name as plugins; they load reflectively."""
    by_name: dict[str, list[Path]] = {}
    for candidate in (SOURCE / "solr/core/src/test").rglob("*.java"):
        by_name.setdefault(candidate.stem, []).append(candidate)
    names = {"MockExchangeRateProvider", "NvlValueSourceParser"}
    for config_file in (SOURCE / "solr/core/src/test-files/solr/collection1/conf").glob("*.xml"):
        text = config_file.read_text(encoding="utf-8", errors="replace")
        for clazz in re.findall(r'class\s*=\s*[\'\"]([^\'\"]+)', text):
            if clazz.startswith(("solr.", "org.apache.solr.")):
                names.add(clazz.split("$", 1)[0].rsplit(".", 1)[-1])
    return sorted({item for name in names for item in by_name.get(name, [])})


def run(request: Request) -> int:
    require_selection(request)
    classes = request.classes_dir or request.output / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    scratch = fresh_scratch(request.output)
    relative = Path(*request.test_class.split(".")).with_suffix(".java")
    test_path = next((SOURCE / root / relative for root in TEST_ROOTS
                      if (SOURCE / root / relative).is_file()), None)
    if test_path is None:
        raise FileNotFoundError(f"original Solr JUnit source: {relative}")
    agent = require_agent()
    classpath = _classpath(classes)
    runner = JAVA_SOURCES / (JUNIT4_RUNNER + ".java")
    test_class = classes / Path(*request.test_class.split(".")).with_suffix(".class")
    runner_class = classes / (JUNIT4_RUNNER + ".class")
    if (not test_class.is_file() or not runner_class.is_file() or
            runner_class.stat().st_mtime_ns < runner.stat().st_mtime_ns):
        subprocess.run([java("javac"), "-cp", classpath, "-sourcepath",
                        os.pathsep.join(str(SOURCE / root) for root in TEST_ROOTS),
                        "-d", str(classes), str(test_path), str(runner),
                        *(str(path) for path in _config_plugins())], check=True)
    nightly = bool(re.search(r"^\s*@Nightly\b", test_path.read_text(errors="replace"), re.M))
    command = [java("java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
               "-Dtests.seed=" + SEED,
               "-Dtests.src.home=" + str(SOURCE / "solr/core"),
               "-Dcommon.dir=" + str(SOURCE / "lucene"),
               "-Dtests.asserts=true", "-Dtests.slow=true",
               "-Dtests.nightly=" + str(nightly).lower(),
               "-Dtests.awaitsfix=true", "-Dtests.badapples=true",
               "-Dsolr.disableConfigSetsCreateAuthChecks=true",
               "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
               "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
               "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
               "-Djdk.map.althashing.threshold=0",
               "-Djava.security.egd=file:/dev/./urandom",
               "-javaagent:" + str(agent), "-cp", classpath, JUNIT4_RUNNER,
               request.test_class, request.test_method]
    code, elapsed = run_junit(command, SOURCE, agent_env(request), request)
    finish(request, manifest(request, code, elapsed, nightly_enabled=nightly), scratch)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(parse(argv, 600))
