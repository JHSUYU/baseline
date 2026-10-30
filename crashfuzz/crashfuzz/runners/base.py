"""What every system's JUnit runner shares.

A runner executes exactly one unchanged JUnit method of a system's release,
with the CrashFuzz agent attached, in a fresh scratch directory under its
output directory, and writes ``<output>/manifest.json``. The agent reads
``CRASHFUZZ_STATIC_SELECTION`` (what to observe) and, in a fault trial,
``CAUSYNTH_FAULT_TRIAL`` (what to inject), and writes
``<output>/runtime_trace.jsonl``.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import settings

JAVA_SOURCES = Path(__file__).resolve().parent / "java"
JUNIT4_RUNNER = "RunJUnit4Method"
JUPITER_RUNNER = "RunJupiterMethod"


@dataclass
class Request:
    case_id: str
    test_class: str
    test_method: str
    output: Path
    static_selection: Path | None
    fault_trial: Path | None
    timeout: int
    classes_dir: Path | None = None
    worker_id: int | None = None
    worker_count: int = 8
    tree: Path | None = None        # a tree workload (crashfuzz.tree), else the release


def parse(argv: list[str] | None, default_timeout: int) -> Request:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--test-class", required=True)
    parser.add_argument("--test-method", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--static-selection", type=Path)
    parser.add_argument("--fault-trial", type=Path)
    parser.add_argument("--timeout", type=int, default=default_timeout)
    parser.add_argument("--classes-dir", type=Path)
    parser.add_argument("--worker-id", type=int)
    parser.add_argument("--worker-count", type=int, default=8)
    parser.add_argument("--tree", type=Path, help="a tree-workload.json to run instead")
    args = parser.parse_args(argv)
    return Request(args.case_id, args.test_class, args.test_method, args.output.resolve(),
                   args.static_selection, args.fault_trial, args.timeout,
                   args.classes_dir.resolve() if args.classes_dir else None,
                   args.worker_id, args.worker_count,
                   args.tree.resolve() if args.tree else None)


def java(tool: str) -> str:
    return str(settings.JAVA_BIN / tool)


def require_selection(request: Request) -> None:
    """Every runner but HDFS's calibration needs the agent's selection."""
    if request.static_selection is None:
        raise SystemExit("--static-selection is required")


def require_agent() -> Path:
    if not settings.AGENT_JAR.is_file():
        raise FileNotFoundError(f"build the runtime agent first: {settings.AGENT_JAR}")
    return settings.AGENT_JAR


def fresh_scratch(output: Path, *subdirectories: str) -> Path:
    """A new empty ``<output>/scratch`` (with subdirectories)."""
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()
    for name in subdirectories:
        (scratch / name).mkdir(parents=True, exist_ok=True)
    return scratch


def compile_runner(source: str, classpath: str, destination: Path,
                   lock: Path | None = None) -> None:
    """Compile a launcher into ``destination`` unless its class is current.

    Runners on several nodes share ``settings.BUILD``, so the compile is
    locked (``lock``, by default beside ``destination``).
    """
    path = JAVA_SOURCES / (source + ".java")
    target = destination / (source + ".class")

    def compile_if_stale() -> None:
        if not target.is_file() or target.stat().st_mtime_ns < path.stat().st_mtime_ns:
            destination.mkdir(parents=True, exist_ok=True)
            subprocess.run([java("javac"), "-cp", classpath, "-d", str(destination), str(path)],
                           check=True)

    if lock is None:
        lock = destination.parent / f".{destination.name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        compile_if_stale()


def agent_env(request: Request, env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment telling the agent what to observe, inject and where to write."""
    env = dict(env if env is not None else os.environ, JAVA_HOME=str(settings.JAVA_HOME))
    if request.static_selection:
        env["CRASHFUZZ_STATIC_SELECTION"] = str(request.static_selection.resolve(strict=True))
        env["CAUSYNTH_TRACE_OUTPUT_DIR"] = str(request.output)
        if request.fault_trial:
            env["CAUSYNTH_FAULT_TRIAL"] = str(request.fault_trial.resolve(strict=True))
    return env


def run_junit(command: list[str], cwd: Path, env: dict[str, str], request: Request) -> tuple[int, float]:
    """Run the JVM with its output in ``junit.log``; 124 on timeout."""
    started = time.monotonic()
    with (request.output / "junit.log").open("w") as log:
        try:
            code = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=request.timeout,
                                  check=False).returncode
        except subprocess.TimeoutExpired:
            code = 124
    return code, round(time.monotonic() - started, 3)


def finish(request: Request, record: dict[str, Any], scratch: Path) -> None:
    """Publish the manifest atomically, drop the scratch tree, echo the manifest."""
    temporary = request.output / "manifest.json.tmp"
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(request.output / "manifest.json")
    shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(record), flush=True)


def manifest(request: Request, code: int, elapsed: float, **extra: Any) -> dict[str, Any]:
    return {"case_id": request.case_id,
            "cluster_test": request.test_class + "#" + request.test_method,
            **extra, "returncode": code, "elapsed_seconds": elapsed,
            "trace": str(request.output / "runtime_trace.jsonl"),
            "junit_log": str(request.output / "junit.log")}
