"""Exercise the NameNode bad-block report path on a separate probe file."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    path = "/adhoc-random/bad-block-probe"
    put = workload.hdfs("dfs", ["-put", "/work/input.bin", path], run_dir)
    if put["returncode"]:
        raise RuntimeError("probe file upload failed: " + put["stderr"])
    classes = run_dir / "classes"
    classes.mkdir()
    jars = sorted((workload.HADOOP / "share/hadoop").rglob("*.jar"))
    classpath = ":".join(str(jar) for jar in jars)
    source = HERE / "fixtures/ReportOneBadBlock.java"
    compiled = subprocess.run([
        "javac", "-cp", classpath, "-d", str(classes), str(source)],
        capture_output=True, text=True, timeout=90)
    if compiled.returncode:
        raise RuntimeError("probe helper compilation failed: " + compiled.stderr)
    command = workload.DOCKER + [
        "run", "--rm", "--network", workload.NETWORK,
        "--add-host=host.docker.internal:host-gateway",
        "-e", "JAVA_HOME=" + workload.JAVA_HOME,
        "-e", "HADOOP_HOME=/opt/hadoop", "-e", "HADOOP_CONF_DIR=/conf",
        "-e", "HADOOP_OPTS=" + workload.JAVA_OPTIONS,
        "-e", "HADOOP_CLASSPATH=/work/classes",
        "-e", "ADHOCFUZZ_NODE_ID=client",
        "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
        "-e", "ADHOCFUZZ_CONTROLLER_HOST=" +
              os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
        "-e", "ADHOCFUZZ_CONTROLLER_PORT=" +
              os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
        "-v", str(workload.HADOOP) + ":/opt/hadoop:ro",
        "-v", str(run_dir / "conf") + ":/conf:ro",
        "-v", str(run_dir / "traces") + ":/traces",
        "-v", str(run_dir) + ":/work",
        "-v", str(workload.AGENT) + ":/agent.jar:ro",
        "-v", str(workload.PROPERTIES) + ":/agent.properties:ro",
        "--entrypoint", "/opt/hadoop/bin/hdfs", workload.IMAGE,
        "org.greygraph.baseline.ReportOneBadBlock", path,
    ]
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=120)
    (run_dir / "bad-block-report.json").write_text(json.dumps({
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:],
    }, indent=2) + "\n")
    if result.returncode:
        raise RuntimeError("bad-block report failed: " + result.stderr[-1000:])


if __name__ == "__main__":
    main()
