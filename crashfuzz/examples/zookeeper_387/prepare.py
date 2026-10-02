"""Start three independent ZooKeeper 3.8.7 JVMs in an isolated Docker network."""

import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
DIST = Path(os.environ.get("ADHOCFUZZ_ZK_DIST", str(
    Path.home() / ".baseline-deps/apache-zookeeper-3.8.7-bin"))).resolve()
AGENT = HERE.parents[1] / "agent/target/adhoc-crashfuzz-agent-0.1.0.jar"
PROPERTIES = Path(os.environ.get("ADHOCFUZZ_AGENT_PROPERTIES",
                                 str(HERE / "agent.properties"))).resolve()
DOCKER = ["sudo", "-n", "docker"]
IMAGE = "eclipse-temurin:17-jdk"
JAVA_HOME = "/opt/java/openjdk"
NETWORK = "adhocfuzz-zk387"
NODES = ("zk1", "zk2", "zk3")


def docker(*args, check=True, timeout=45):
    result = subprocess.run(DOCKER + list(args), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("docker " + " ".join(args) + ": "
                           + (result.stderr or result.stdout)[-1200:])
    return result


def main() -> None:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    if not (DIST / "bin/zkServer.sh").is_file() or not AGENT.is_file():
        raise RuntimeError("ZooKeeper distribution or agent is missing")
    if not PROPERTIES.is_file():
        raise RuntimeError("missing agent properties: " + str(PROPERTIES))
    trace = run_dir / "traces"
    trace.mkdir(parents=True, exist_ok=True)
    peers = "\n".join("server.{}={}-{}:2888:3888".format(
        number, NETWORK, name) for number, name in enumerate(NODES, 1))
    for number, name in enumerate(NODES, 1):
        conf = run_dir / "conf" / name
        conf.mkdir(parents=True)
        (conf / "zoo.cfg").write_text(
            "tickTime=1000\ninitLimit=20\nsyncLimit=10\n"
            "dataDir=/data/zk\nclientPort=2181\n"
            "admin.enableServer=false\n"
            "4lw.commands.whitelist=ruok,stat,mntr\n" + peers + "\n")
        data = run_dir / "state" / name / "zk"
        data.mkdir(parents=True)
        (data / "myid").write_text(str(number) + "\n")
    for name in NODES:
        docker("rm", "-f", NETWORK + "-" + name, check=False)
    if docker("network", "inspect", NETWORK, check=False).returncode:
        docker("network", "create", NETWORK)
    for name in NODES:
        docker("run", "-d", "--name", NETWORK + "-" + name,
               "--hostname", NETWORK + "-" + name,
               "--network", NETWORK,
               "--add-host=host.docker.internal:host-gateway",
               "-e", "JAVA_HOME=" + JAVA_HOME,
               "-e", "SERVER_JVMFLAGS=-Xmx512m -javaagent:/agent.jar=/agent.properties",
               "-e", "ADHOCFUZZ_NODE_ID=" + name,
               "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
               "-e", "ADHOCFUZZ_CONTROLLER_HOST="
               + os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
               "-e", "ADHOCFUZZ_CONTROLLER_PORT="
               + os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
               "-v", str(DIST) + ":/opt/zk:ro",
               "-v", str(run_dir / "conf" / name) + ":/conf:ro",
               "-v", str(run_dir / "state" / name) + ":/data",
               "-v", str(trace) + ":/traces",
               "-v", str(AGENT) + ":/agent.jar:ro",
               "-v", str(PROPERTIES) + ":/agent.properties:ro",
               "--entrypoint", "/opt/zk/bin/zkServer.sh", IMAGE,
               "--config", "/conf", "start-foreground")
    deadline = time.monotonic() + 90
    last = ""
    while time.monotonic() < deadline:
        statuses = [docker("exec", name, "/opt/zk/bin/zkServer.sh",
                           "--config", "/conf", "status", check=False,
                           timeout=15)
                    for name in (NETWORK + "-" + node for node in NODES)]
        last = "\n".join((row.stdout + row.stderr)[-200:] for row in statuses)
        if all(row.returncode == 0 and "Mode:" in row.stdout
               for row in statuses):
            print("ZooKeeper quorum ready: 3 nodes")
            return
        time.sleep(2)
    raise RuntimeError("ZooKeeper quorum did not become ready: " + last)


if __name__ == "__main__":
    main()
