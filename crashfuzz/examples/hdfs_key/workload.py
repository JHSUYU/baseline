"""Exercise encrypted HDFS pipeline writes and reads with three replicas."""

import hashlib
import os
from pathlib import Path
import subprocess
import time

from prepare import AGENT, DOCKER, HADOOP, IMAGE, JAVA_HOME, JAVA_OPTIONS, NETWORK, PROPERTIES


def client(command, run_dir):
    args = DOCKER + [
        "run", "--rm", "--network", NETWORK,
        "--add-host=host.docker.internal:host-gateway",
        "-e", "JAVA_HOME=" + JAVA_HOME,
        "-e", "HADOOP_HOME=/opt/hadoop",
        "-e", "HADOOP_CONF_DIR=/conf",
        "-e", "HADOOP_OPTS=" + JAVA_OPTIONS,
        "-e", "ADHOCFUZZ_NODE_ID=client",
        "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
        "-e", "ADHOCFUZZ_CONTROLLER_HOST=" +
              os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
        "-e", "ADHOCFUZZ_CONTROLLER_PORT=" +
              os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
        "-v", str(HADOOP) + ":/opt/hadoop:ro",
        "-v", str(run_dir / "conf") + ":/conf:ro",
        "-v", str(run_dir / "traces") + ":/traces",
        "-v", str(run_dir) + ":/work",
        "-v", str(AGENT) + ":/agent.jar:ro",
        "-v", str(PROPERTIES) + ":/agent.properties:ro",
        "--entrypoint", "/opt/hadoop/bin/hdfs", IMAGE, "dfs",
    ] + list(command)
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=180)
    return result


def main():
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    source = run_dir / "input.bin"
    destination = run_dir / "output.bin"
    source.write_bytes(bytes(range(256)) * 32768)
    steps = [
        ("mkdir", ["-mkdir", "-p", "/adhoc-key"]),
        ("put", ["-put", "-f", "/work/input.bin", "/adhoc-key/blob"]),
        ("get", ["-get", "-f", "/adhoc-key/blob", "/work/output.bin"]),
    ]
    for name, argv in steps:
        if name == "get":
            pause = int(os.environ.get("ADHOCFUZZ_KEY_WAIT_S", "0"))
            if pause:
                time.sleep(pause)
        result = client(argv, run_dir)
        (run_dir / (name + ".stdout")).write_text(result.stdout,
                                                    encoding="utf-8")
        (run_dir / (name + ".stderr")).write_text(result.stderr,
                                                    encoding="utf-8")
        (run_dir / (name + ".exit")).write_text(str(result.returncode) + "\n",
                                                  encoding="utf-8")
        if result.returncode:
            raise RuntimeError("HDFS {} failed: {}".format(
                name, result.stderr[-1500:]))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    destination_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    (run_dir / "hashes.txt").write_text(source_hash + "\n" +
                                         destination_hash + "\n",
                                         encoding="utf-8")
    if source_hash != destination_hash:
        raise RuntimeError("HDFS read differs from written bytes")
    print("encrypted HDFS put/get verified sha256=" + source_hash)


if __name__ == "__main__":
    main()
