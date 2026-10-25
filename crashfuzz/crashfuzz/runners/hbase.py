"""One unchanged HBase 2.6.6 embedded-cluster JUnit Jupiter method."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import settings
from .base import (JUPITER_RUNNER, Request, agent_env, compile_runner, finish, fresh_scratch,
                   java, manifest, parse, require_agent, require_selection, run_junit)

HBASE = settings.DEPS / "hbase-2.6.6"
HADOOP = settings.DEPS / "hadoop-2.10.0"
BUILD = settings.BUILD / "hbase-junit"
SSL_UTILITY = (Path(__file__).resolve().parent /
               "hbase-support/src/org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.java")
# The binary distribution holds both 1.0.0-M20 and 2.1.7 Apache Directory API
# jars; MiniKdc in HBase's security tests needs M20, and wildcard order could
# otherwise mix Oid 2.1.7 with I18n M20.
DIRECTORY_API = ("lib/api-asn1-api-1.0.0-M20.jar", "lib/api-i18n-1.0.0-M20.jar")
MINI_KDC_CRYPTO = tuple(f"org/bouncycastle/{module}-jdk15on/1.60/{module}-jdk15on-1.60.jar"
                        for module in ("bcprov", "bcpkix"))


def _launcher() -> Path:
    vendor = settings.HOME / "vendor"
    return next(vendor.glob("*junit-platform-launcher-1.13.4.jar"),
                vendor / "junit-platform-launcher-1.13.4.jar")


def run(request: Request) -> int:
    require_selection(request)
    scratch = fresh_scratch(request.output, "tmp")
    launcher = _launcher()
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    agent = require_agent()
    pinned = ([HBASE / path for path in DIRECTORY_API] +
              [settings.M2 / path for path in MINI_KDC_CRYPTO])
    if any(not jar.is_file() for jar in pinned):
        raise FileNotFoundError("HBase MiniKdc test dependencies are missing")
    ssl_classes = scratch / "test-classes"
    classpath = os.pathsep.join([
        str(ssl_classes), str(BUILD), str(launcher), str(HBASE / "conf"),
        *(str(jar) for jar in pinned), str(HBASE / "lib/*"),
        str(HBASE / "lib/client-facing-thirdparty/*"),
        str(HADOOP / "share/hadoop/common/hadoop-common-2.10.0-tests.jar"),
        str(HADOOP / "share/hadoop/common/lib/*")])
    if request.test_class.endswith(".TestGenerateDelegationToken"):
        # Its Kerberos cluster needs the test-only SSL utility HBase's
        # binary distribution leaves out.
        ssl_classes.mkdir(parents=True)
        subprocess.run([java("javac"), "-cp", classpath, "-d", str(ssl_classes),
                        str(SSL_UTILITY)], check=True)
    compile_runner(JUPITER_RUNNER, classpath, BUILD, lock=settings.BUILD / ".hbase-junit.lock")
    command = [java("java"), "-ea", "-Xmx4g",
               "-Djava.library.path=" + str(HADOOP / "lib/native"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dtest.build.data.basedirectory=" + str(scratch),
               "-javaagent:" + str(agent), "-cp", classpath, JUPITER_RUNNER,
               request.test_class, request.test_method]
    env = agent_env(request)
    env["HBASE_HOME"] = str(HBASE)
    code, elapsed = run_junit(command, scratch, env, request)
    finish(request, manifest(request, code, elapsed), scratch)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(parse(argv, 300))
