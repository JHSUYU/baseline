"""Wait for HBase, then exercise table, data, snapshot, and procedure paths."""

import os
from pathlib import Path
import subprocess
import time

from prepare import (AGENT, AGENT_PROPERTIES, DOCKER, HBASE, HERE,
                     IMAGE, JAVA_HOME, NETWORK)


def client(script, conf, timeout=90, trace=None):
    argv = DOCKER + [
        "run", "--rm", "--network", NETWORK,
        "-e", "JAVA_HOME=" + JAVA_HOME,
        "-e", "HBASE_CONF_DIR=/conf",
        "-e", "HBASE_MANAGES_ZK=false",
        "-v", str(HBASE) + ":/opt/hbase:ro",
        "-v", str(conf) + ":/conf:ro",
        "-v", str(script) + ":/workload.hbase:ro"]
    if trace is not None:
        argv += ["-e", "HBASE_OPTS=-javaagent:/agent.jar=/agent.properties",
                 "-e", "ADHOCFUZZ_NODE_ID=client",
                 "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
                 "-v", str(trace) + ":/traces",
                 "-v", str(AGENT) + ":/agent.jar:ro",
                 "-v", str(AGENT_PROPERTIES) + ":/agent.properties:ro"]
    argv += ["--entrypoint", "/opt/hbase/bin/hbase", IMAGE,
             "shell", "-n", "/workload.hbase"]
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def main():
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    conf = run_dir / "conf"
    ready_script = run_dir / "ready.hbase"
    ready_script.write_text("status 'simple'\n", encoding="utf-8")
    deadline = time.monotonic() + 240
    last = ""
    while time.monotonic() < deadline:
        try:
            result = client(ready_script, conf, timeout=35)
            last = result.stdout[-1500:] + result.stderr[-1500:]
            if result.returncode == 0 and "active master" in result.stdout:
                break
        except subprocess.TimeoutExpired as error:
            last = str(error)
        time.sleep(3)
    else:
        raise RuntimeError("HBase never became ready: " + last)

    result = client(HERE / "workload.hbase", conf, timeout=360,
                    trace=run_dir / "traces")
    (run_dir / "hbase-client.stdout").write_text(result.stdout,
                                                    encoding="utf-8")
    (run_dir / "hbase-client.stderr").write_text(result.stderr,
                                                    encoding="utf-8")
    (run_dir / "hbase-client.exit").write_text(str(result.returncode) + "\n",
                                                  encoding="utf-8")
    print(result.stdout[-3000:])
    if result.returncode:
        raise RuntimeError("HBase workload failed: " + result.stderr[-1500:])


if __name__ == "__main__":
    main()
