"""Reset a real HBase 2.6.6 cluster with HDFS and ZooKeeper in Docker."""

import os
from pathlib import Path
import shutil
import subprocess
import time
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
DEFAULT_DEPS = Path.home() / ".baseline-deps"
HBASE = Path(os.environ.get("ADHOCFUZZ_HBASE_DIST",
                            str(DEFAULT_DEPS / "hbase-2.6.6"))).resolve()
HADOOP = Path(os.environ.get("ADHOCFUZZ_HADOOP_DIST",
                             str(DEFAULT_DEPS / "hadoop-3.4.3"))).resolve()
AGENT = HERE.parent.parent / "agent" / "target" / "adhoc-crashfuzz-agent-0.1.0.jar"
AGENT_PROPERTIES = Path(os.environ.get(
    "ADHOCFUZZ_AGENT_PROPERTIES", str(HERE / "agent.properties"))).resolve()
DOCKER = ["sudo", "-n", "docker"]
IMAGE = os.environ.get("ADHOCFUZZ_JAVA17_IMAGE", "eclipse-temurin:17-jdk")
NETWORK = "adhocfuzz-hbase266"
PREFIX = "adhocfuzz-hbase266-"
JAVA_HOME = "/opt/java/openjdk"
HBASE_NODES = ("hm1", "hm2", "rs1", "rs2", "rs3")
ALL_NODES = ("nn", "dn", "zk") + HBASE_NODES


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
        property_node = ET.SubElement(root, "property")
        ET.SubElement(property_node, "name").text = name
        ET.SubElement(property_node, "value").text = str(value)
    ET.ElementTree(root).write(str(path), encoding="utf-8",
                               xml_declaration=True)


def base_args(name, conf, data=None):
    args = ["run", "-d", "--name", PREFIX + name,
            "--hostname", PREFIX + name, "--network", NETWORK,
            "--add-host=host.docker.internal:host-gateway",
            "-e", "JAVA_HOME=" + JAVA_HOME,
            "-v", str(conf) + ":/conf:ro"]
    if data is not None:
        args += ["-v", str(data) + ":/data"]
    return args


def hadoop_args(name, conf, data):
    return base_args(name, conf, data) + [
        "-e", "HADOOP_CONF_DIR=/conf", "-e", "HADOOP_LOG_DIR=/data/logs",
        "-e", "HADOOP_HOME=/opt/hadoop",
        "-v", str(HADOOP) + ":/opt/hadoop:ro",
        "--entrypoint", "/opt/hadoop/bin/hdfs", IMAGE]


def wait_for(predicate, description, seconds=75):
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
    if not (HBASE / "bin" / "hbase").is_file():
        raise RuntimeError("missing HBase 2.6.6 distribution: " + str(HBASE))
    if not (HADOOP / "bin" / "hdfs").is_file():
        raise RuntimeError("missing Hadoop 3.4.3 distribution: " + str(HADOOP))
    if not AGENT.is_file():
        raise RuntimeError("build the Java 8 probe first: " + str(AGENT))
    if not AGENT_PROPERTIES.is_file():
        raise RuntimeError("missing agent properties: " + str(AGENT_PROPERTIES))
    trace = run_dir / "traces"
    trace.mkdir(parents=True, exist_ok=True)
    conf = run_dir / "conf"
    shutil.copytree(str(HBASE / "conf"), str(conf))
    xml_config(conf / "core-site.xml", {
        "fs.defaultFS": "hdfs://" + PREFIX + "nn:9000",
        "hadoop.tmp.dir": "/data/tmp",
    })
    xml_config(conf / "hdfs-site.xml", {
        "dfs.namenode.rpc-address": PREFIX + "nn:9000",
        "dfs.namenode.http-address": PREFIX + "nn:9870",
        "dfs.namenode.name.dir": "file:///data/nn",
        "dfs.datanode.data.dir": "file:///data/dn",
        "dfs.replication": 1,
        "dfs.permissions.enabled": "false",
        "dfs.namenode.datanode.registration.ip-hostname-check": "false",
    })
    xml_config(conf / "hbase-site.xml", {
        "hbase.cluster.distributed": "true",
        "hbase.rootdir": "hdfs://" + PREFIX + "nn:9000/hbase",
        "hbase.zookeeper.quorum": PREFIX + "zk",
        "hbase.zookeeper.property.clientPort": 2181,
        "hbase.zookeeper.property.dataDir": "/data/zk",
        "hbase.client.registry.impl":
        "org.apache.hadoop.hbase.client.ZKConnectionRegistry",
        "zookeeper.session.timeout": int(os.environ.get(
            "ADHOCFUZZ_ZK_SESSION_TIMEOUT_MS", "90000")),
        "hbase.tmp.dir": "/data/tmp",
        "hbase.master.info.port": -1,
        "hbase.regionserver.info.port": -1,
        "hbase.unsafe.regionserver.hostname.disable.master.reversedns": "true",
        "hbase.master.wait.on.regionservers.mintostart": 1,
    })

    for name in ALL_NODES:
        docker("rm", "-f", PREFIX + name, check=False)
    if docker("network", "inspect", NETWORK, check=False).returncode:
        docker("network", "create", NETWORK)

    state = run_dir / "state"
    for name in ALL_NODES:
        (state / name).mkdir(parents=True)

    # Format a fresh NameNode in the same bind-mounted state used by its JVM.
    format_args = hadoop_args("nn-format", conf, state / "nn")
    format_args[1] = "--rm"  # replace detached mode for this one-shot command
    format_args += ["namenode", "-format", "-force"]
    docker(*format_args)
    docker(*(hadoop_args("nn", conf, state / "nn") + ["namenode"]))
    wait_for(lambda: (
        docker("exec", PREFIX + "nn", "/opt/hadoop/bin/hdfs",
               "dfsadmin", "-safemode", "get", check=False).returncode == 0,
        "NameNode RPC unavailable"), "NameNode")
    docker(*(hadoop_args("dn", conf, state / "dn") + ["datanode"]))

    def datanode_ready():
        result = docker("exec", PREFIX + "nn", "/opt/hadoop/bin/hdfs",
                        "dfsadmin", "-report", check=False)
        return "Live datanodes (1)" in result.stdout, result.stdout[-1000:]

    wait_for(datanode_ready, "one live DataNode")

    zk_args = base_args("zk", conf, state / "zk") + [
        "-e", "HBASE_CONF_DIR=/conf", "-e", "HBASE_MANAGES_ZK=false",
        "-v", str(HBASE) + ":/opt/hbase:ro",
        "--entrypoint", "/opt/hbase/bin/hbase", IMAGE, "zookeeper"]
    docker(*zk_args)
    wait_for(lambda: (
        docker("exec", PREFIX + "zk", "bash", "-c",
               "echo > /dev/tcp/127.0.0.1/2181", check=False).returncode == 0,
        "ZooKeeper port 2181 unavailable"), "ZooKeeper")

    for node in HBASE_NODES:
        role = "master" if node.startswith("hm") else "regionserver"
        args = base_args(node, conf, state / node) + [
            "-e", "HBASE_CONF_DIR=/conf",
            "-e", "HBASE_MANAGES_ZK=false",
            "-e", "HBASE_HEAPSIZE=1024",
            "-e", "HBASE_LOG_DIR=/data/logs",
            "-e", "HBASE_OPTS=-javaagent:/agent.jar=/agent.properties",
            "-e", "ADHOCFUZZ_NODE_ID=" + node,
            "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
            "-e", "ADHOCFUZZ_CONTROLLER_HOST=" +
            os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
            "-e", "ADHOCFUZZ_CONTROLLER_PORT=" +
            os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
            "-v", str(HBASE) + ":/opt/hbase:ro",
            "-v", str(trace) + ":/traces",
            "-v", str(AGENT) + ":/agent.jar:ro",
            "-v", str(AGENT_PROPERTIES) + ":/agent.properties:ro",
            "--entrypoint", "/opt/hbase/bin/hbase", IMAGE, role, "start"]
        docker(*args)
    ready_script = state / "hm1" / "ready.hbase"
    ready_script.write_text("status 'simple'\n", encoding="utf-8")

    def hbase_ready():
        result = docker("exec", "-e", "HBASE_OPTS=", PREFIX + "hm1",
                        "/opt/hbase/bin/hbase",
                        "shell", "-n", "/data/ready.hbase", check=False)
        return (result.returncode == 0 and "active master" in result.stdout,
                (result.stdout + result.stderr)[-1200:])

    try:
        wait_for(hbase_ready, "HBase active master", seconds=180)
    except RuntimeError:
        for node in HBASE_NODES:
            logs = docker("logs", "--tail", "200", PREFIX + node,
                          check=False)
            (run_dir / ("startup-" + node + ".log")).write_text(
                logs.stdout + logs.stderr, encoding="utf-8")
        raise
    print("started HDFS, ZooKeeper, 2 masters, and 3 RegionServers")


if __name__ == "__main__":
    main()
