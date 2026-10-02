"""Exercise ZooKeeper reads, writes, and a final durable value."""

import os
from pathlib import Path
import subprocess
import sys
import time

from prepare import AGENT, DIST, DOCKER, IMAGE, JAVA_HOME, NETWORK, NODES, PROPERTIES


SERVERS = ",".join(NETWORK + "-" + node + ":2181" for node in NODES)


def client(commands: str, trace: Path | None = None,
           timeout: int = 120) -> subprocess.CompletedProcess:
    argv = DOCKER + ["run", "--rm", "-i", "--network", NETWORK,
                     "--add-host=host.docker.internal:host-gateway",
                     "-e", "JAVA_HOME=" + JAVA_HOME,
                     "-v", str(DIST) + ":/opt/zk:ro"]
    if trace is not None:
        argv += ["-e", "CLIENT_JVMFLAGS=-Xmx256m -javaagent:/agent.jar=/agent.properties",
                 "-e", "ADHOCFUZZ_NODE_ID=client",
                 "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
                 "-e", "ADHOCFUZZ_CONTROLLER_HOST=host.docker.internal",
                 "-e", "ADHOCFUZZ_CONTROLLER_PORT="
                 + os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
                 "-v", str(trace) + ":/traces",
                 "-v", str(AGENT) + ":/agent.jar:ro",
                 "-v", str(PROPERTIES) + ":/agent.properties:ro"]
    argv += ["--entrypoint", "/opt/zk/bin/zkCli.sh", IMAGE,
             "-server", SERVERS]
    return subprocess.run(argv, input=commands, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout)


def main() -> int:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    # Establish the persistent parent before any get. If the first create
    # loses its reply during failover, retry until success or NodeExists.
    create_deadline = time.monotonic() + 90
    created = False
    attempt = 0
    while time.monotonic() < create_deadline:
        attempt += 1
        setup = client("create /adhoc387 first\nquit\n",
                       run_dir / "traces", timeout=45)
        (run_dir / ("zk-create-{:02d}.stdout".format(attempt))).write_text(
            setup.stdout)
        (run_dir / ("zk-create-{:02d}.stderr".format(attempt))).write_text(
            setup.stderr)
        if ("Created /adhoc387" in setup.stdout
                or "Node already exists: /adhoc387" in setup.stderr):
            created = True
            break
        time.sleep(2)
    if not created:
        print("ZooKeeper could not create the persistent workload node")
        return 1
    commands = ("get /adhoc387\n"
                "set /adhoc387 second\n"
                "get /adhoc387\n"
                "create /adhoc387/child child\n"
                "ls /adhoc387\n"
                "delete /adhoc387/child\n"
                "set /adhoc387 sentinel387\n"
                "get /adhoc387\nquit\n")
    result = client(commands, run_dir / "traces")
    (run_dir / "zk-client.stdout").write_text(result.stdout)
    (run_dir / "zk-client.stderr").write_text(result.stderr)
    (run_dir / "zk-client.exit").write_text(str(result.returncode) + "\n")
    print(result.stdout[-1000:])
    # Retry the final write after failover. The parent was established before
    # the first read, so a later NoNode is no longer an expected test-script
    # artifact. A separate checker verifies the value after injection closes.
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        probe = client("get /adhoc387\nquit\n", timeout=35)
        if probe.returncode == 0 and "sentinel387" in probe.stdout:
            print("ZooKeeper workload verified sentinel387")
            return 0
        repair = client("set /adhoc387 sentinel387\n"
                        "get /adhoc387\nquit\n",
                        run_dir / "traces", timeout=45)
        (run_dir / "zk-repair.stdout").write_text(repair.stdout)
        (run_dir / "zk-repair.stderr").write_text(repair.stderr)
        time.sleep(2)
    print("ZooKeeper workload could not restore sentinel387")
    return 1


if __name__ == "__main__":
    sys.exit(main())
