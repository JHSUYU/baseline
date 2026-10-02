"""Reset a three-DataNode HDFS 3.4.3 cluster with encrypted transfer."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
HADOOP = Path(os.environ.get("ADHOCFUZZ_HADOOP_DIST",
                             str(Path.home() / ".baseline-deps/hadoop-3.4.3"))).resolve()
AGENT = HERE.parent.parent / "agent/target/adhoc-crashfuzz-agent-0.1.0.jar"
PROPERTIES = Path(os.environ.get("ADHOCFUZZ_AGENT_PROPERTIES",
                                 str(HERE / "agent.properties"))).resolve()
DOCKER = ["sudo", "-n", "docker"]
IMAGE = os.environ.get("ADHOCFUZZ_JAVA17_IMAGE", "eclipse-temurin:17-jdk")
NETWORK = "adhocfuzz-hdfs-key"
PREFIX = NETWORK + "-"
NODES = ("nn", "dn1", "dn2", "dn3")
JAVA_HOME = "/opt/java/openjdk"
JAVA_OPTIONS = (("-ea " if os.environ.get("ADHOCFUZZ_ENABLE_ASSERTIONS") == "1"
                 else "") + "-javaagent:/agent.jar=/agent.properties")


def docker(*args, check=True):
    result = subprocess.run(DOCKER + list(args), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError("docker {} failed: {} {}".format(
            " ".join(args), result.stdout.strip(), result.stderr.strip()))
    return result


def xml_config(path, values):
    root = ET.Element("configuration")
    for name, value in values.items():
        item = ET.SubElement(root, "property")
        ET.SubElement(item, "name").text = name
        ET.SubElement(item, "value").text = str(value)
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def hadoop_args(name, conf, data, trace, detached=True):
    args = ["run", "-d" if detached else "--rm", "--name", PREFIX + name,
            "--hostname", PREFIX + name, "--network", NETWORK,
            "--add-host=host.docker.internal:host-gateway",
            "-e", "JAVA_HOME=" + JAVA_HOME,
            "-e", "HADOOP_HOME=/opt/hadoop", "-e", "HADOOP_CONF_DIR=/conf",
            "-e", "HADOOP_LOG_DIR=/data/logs",
            "-e", "HADOOP_OPTS=" + JAVA_OPTIONS,
            "-e", "ADHOCFUZZ_NODE_ID=" + name,
            "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
            "-e", "ADHOCFUZZ_CONTROLLER_HOST=" +
                  os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
            "-e", "ADHOCFUZZ_CONTROLLER_PORT=" +
                  os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
            "-v", str(HADOOP) + ":/opt/hadoop:ro",
            "-v", str(conf) + ":/conf:ro",
            "-v", str(data) + ":/data",
            "-v", str(trace) + ":/traces",
            "-v", str(AGENT) + ":/agent.jar:ro",
            "-v", str(PROPERTIES) + ":/agent.properties:ro",
            "--entrypoint", "/opt/hadoop/bin/hdfs", IMAGE]
    return args


def wait_for(predicate, description, seconds=100):
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        try:
            good, last = predicate()
            if good:
                return
        except (RuntimeError, OSError) as error:
            last = str(error)
        time.sleep(1)
    raise RuntimeError("timed out waiting for {}: {}".format(description, last))


def main():
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    if not (HADOOP / "bin/hdfs").is_file():
        raise RuntimeError("missing Hadoop distribution: " + str(HADOOP))
    if not AGENT.is_file():
        raise RuntimeError("build the Java agent first: " + str(AGENT))
    if not PROPERTIES.is_file():
        raise RuntimeError("missing agent properties: " + str(PROPERTIES))
    trace = run_dir / "traces"
    trace.mkdir(parents=True, exist_ok=True)
    conf = run_dir / "conf"
    shutil.copytree(HADOOP / "etc/hadoop", conf)
    xml_config(conf / "core-site.xml", {
        "fs.defaultFS": "hdfs://" + PREFIX + "nn:9000",
        "hadoop.tmp.dir": "/data/tmp",
    })
    hdfs_values = {
        "dfs.namenode.rpc-address": PREFIX + "nn:9000",
        "dfs.namenode.http-address": PREFIX + "nn:9870",
        "dfs.namenode.name.dir": "file:///data/nn",
        "dfs.datanode.data.dir": "file:///data/dn",
        "dfs.replication": 3,
        "dfs.permissions.enabled": "false",
        "dfs.namenode.datanode.registration.ip-hostname-check": "false",
        "dfs.encrypt.data.transfer": "true",
        "dfs.block.access.token.enable": "true",
        "dfs.block.access.key.update.interval": 1,
        "dfs.block.access.token.lifetime": 1,
        "dfs.namenode.heartbeat.recheck-interval": 1000,
        "dfs.heartbeat.interval": 1,
    }
    hdfs_values.update(json.loads(os.environ.get(
        "ADHOCFUZZ_HDFS_SITE_EXTRAS", "{}")))
    xml_config(conf / "hdfs-site.xml", hdfs_values)
    for node in NODES:
        docker("rm", "-f", PREFIX + node, check=False)
    if docker("network", "inspect", NETWORK, check=False).returncode:
        docker("network", "create", NETWORK)
    state = run_dir / "state"
    for node in NODES:
        (state / node).mkdir(parents=True)
    fmt = hadoop_args("format", conf, state / "nn", trace, detached=False)
    fmt += ["namenode", "-format", "-force"]
    docker(*fmt)
    docker(*(hadoop_args("nn", conf, state / "nn", trace) + ["namenode"]))
    wait_for(lambda: (
        docker("exec", PREFIX + "nn", "/opt/hadoop/bin/hdfs",
               "dfsadmin", "-safemode", "get", check=False).returncode == 0,
        "NameNode RPC unavailable"), "NameNode")
    for node in NODES[1:]:
        docker(*(hadoop_args(node, conf, state / node, trace) + ["datanode"]))

    def datanodes_ready():
        result = docker("exec", PREFIX + "nn", "/opt/hadoop/bin/hdfs",
                        "dfsadmin", "-report", check=False)
        return "Live datanodes (3)" in result.stdout, result.stdout[-1200:]

    wait_for(datanodes_ready, "three DataNodes", seconds=120)
    print("started encrypted HDFS: NameNode and three DataNodes")


if __name__ == "__main__":
    main()
