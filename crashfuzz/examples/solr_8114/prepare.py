"""Start an isolated Solr 8.11.4 cloud with two JVMs and ZooKeeper."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlencode


HERE = Path(__file__).resolve().parent
DEPS = Path.home() / ".baseline-deps"
SOLR = Path(os.environ.get("ADHOCFUZZ_SOLR_DIST", str(DEPS / "solr-8.11.4"))).resolve()
ZK = Path(os.environ.get("ADHOCFUZZ_ZK_DIST", str(
    DEPS / "apache-zookeeper-3.8.7-bin"))).resolve()
AGENT = HERE.parents[1] / "agent/target/adhoc-crashfuzz-agent-0.1.0.jar"
PROPERTIES = Path(os.environ.get("ADHOCFUZZ_AGENT_PROPERTIES",
                                 str(HERE / "agent.properties"))).resolve()
DOCKER = ["sudo", "-n", "docker"]
IMAGE = "eclipse-temurin:17-jdk"
NETWORK = "adhocfuzz-solr8114"
PREFIX = NETWORK + "-"
NODES = ("solr1", "solr2")
ZK_HOST = PREFIX + "zk:2181"


def docker(*args, check=True, timeout=60):
    result = subprocess.run(DOCKER + list(args), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("docker " + " ".join(args[:5]) + ": "
                           + (result.stdout + result.stderr)[-1500:])
    return result


def request(path, *, node="solr1", method="GET", data=None, timeout=45,
            correlation=None):
    """Use the uninstrumented ZooKeeper container as an HTTP client."""
    url = "http://{}:8983/solr{}".format(PREFIX + node, path)
    args = ["exec", PREFIX + "zk", "curl", "-fsS", "--max-time", str(timeout)]
    if method != "GET":
        args += ["-X", method]
    if correlation:
        args += ["-H", "X-Adhoc-Request-ID: " + correlation]
    if data is not None:
        args += ["-H", "Content-Type: application/json", "--data-binary", data]
    row = docker(*(args + [url]), check=False, timeout=timeout + 10)
    if row.returncode:
        raise RuntimeError("Solr HTTP " + path + ": " + row.stderr[-500:])
    return json.loads(row.stdout)


def wait_for(check, description, seconds=90):
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        try:
            good, last = check()
            if good:
                return
        except (RuntimeError, ValueError, KeyError) as error:
            last = str(error)
        time.sleep(2)
    raise RuntimeError("timed out waiting for " + description + ": " + last)


def main():
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    for required in (SOLR / "bin/solr", ZK / "bin/zkServer.sh", AGENT,
                     PROPERTIES):
        if not required.is_file():
            raise RuntimeError("missing Solr adapter input: " + str(required))
    trace = run_dir / "traces"
    trace.mkdir(parents=True, exist_ok=True)
    state = run_dir / "state"
    for name in ("zk",) + NODES:
        (state / name).mkdir(parents=True)
    zkconf = run_dir / "zkconf"
    zkconf.mkdir()
    (zkconf / "zoo.cfg").write_text(
        "tickTime=1000\ndataDir=/data/zk\nclientPort=2181\n"
        "admin.enableServer=false\n")
    (state / "zk" / "zk").mkdir()
    for name in NODES:
        home = state / name / "solr"
        home.mkdir()
        shutil.copy2(SOLR / "server/solr/solr.xml", home / "solr.xml")
        for subdir in ("logs", "pids", "tmp"):
            (state / name / subdir).mkdir()
    for name in ("zk",) + NODES:
        docker("rm", "-f", PREFIX + name, check=False)
    if docker("network", "inspect", NETWORK, check=False).returncode:
        docker("network", "create", NETWORK)
    docker("run", "-d", "--name", PREFIX + "zk", "--hostname", PREFIX + "zk",
           "--network", NETWORK,
           "-v", str(ZK) + ":/opt/zk:ro",
           "-v", str(zkconf) + ":/conf:ro",
           "-v", str(state / "zk") + ":/data",
           "--entrypoint", "/opt/zk/bin/zkServer.sh", IMAGE,
           "--config", "/conf", "start-foreground")
    wait_for(lambda: (
        docker("exec", PREFIX + "zk", "bash", "-c",
               "echo > /dev/tcp/127.0.0.1/2181", check=False).returncode == 0,
        "ZooKeeper port unavailable"), "ZooKeeper")
    for name in NODES:
        docker("run", "-d", "--name", PREFIX + name,
               "--hostname", PREFIX + name, "--network", NETWORK,
               "--add-host=host.docker.internal:host-gateway",
               "-e", "JAVA_HOME=/opt/java/openjdk",
               "-e", "SOLR_HEAP=768m",
               "-e", "SOLR_LOGS_DIR=/data/logs",
               "-e", "SOLR_PID_DIR=/data/pids",
               "-e", "SOLR_OPTS=-javaagent:/agent.jar=/agent.properties",
               "-e", "ADHOCFUZZ_NODE_ID=" + name,
               "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
               "-e", "ADHOCFUZZ_CONTROLLER_HOST="
               + os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
               "-e", "ADHOCFUZZ_CONTROLLER_PORT="
               + os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
               "-v", str(SOLR) + ":/opt/solr:ro",
               "-v", str(state / name) + ":/data",
               "-v", str(trace) + ":/traces",
               "-v", str(AGENT) + ":/agent.jar:ro",
               "-v", str(PROPERTIES) + ":/agent.properties:ro",
               "--entrypoint", "/opt/solr/bin/solr", IMAGE,
               "-f", "-force", "-c", "-z", ZK_HOST,
               "-h", PREFIX + name, "-p", "8983", "-s", "/data/solr")
    def live_nodes():
        rows = request("/admin/collections?" + urlencode({
            "action": "CLUSTERSTATUS", "wt": "json"}))
        live = rows["cluster"]["live_nodes"]
        return len(live) == 2, str(live)
    wait_for(live_nodes, "two SolrCloud nodes", seconds=150)
    docker("exec", PREFIX + "solr1", "/opt/solr/bin/solr", "zk",
           "upconfig", "-n", "adhocconf", "-d",
           "/opt/solr/server/solr/configsets/_default/conf", "-z", ZK_HOST,
           timeout=90)
    created = request("/admin/collections?" + urlencode({
        "action": "CREATE", "name": "adhoc8114", "numShards": 1,
        "replicationFactor": 2, "maxShardsPerNode": 1,
        "collection.configName": "adhocconf", "wt": "json"}), timeout=90)
    if created.get("responseHeader", {}).get("status") != 0:
        raise RuntimeError("collection creation failed: " + str(created))
    def collection_ready():
        rows = request("/admin/collections?" + urlencode({
            "action": "CLUSTERSTATUS", "collection": "adhoc8114", "wt": "json"}))
        replicas = rows["cluster"]["collections"]["adhoc8114"]["shards"]["shard1"]["replicas"]
        states = [row["state"] for row in replicas.values()]
        return len(states) == 2 and all(x == "active" for x in states), str(states)
    wait_for(collection_ready, "two active Solr replicas", seconds=90)
    print("SolrCloud ready: two nodes, one shard, two replicas")


if __name__ == "__main__":
    main()
