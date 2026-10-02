"""Reset two real Docker JVMs for one target-guided trial."""

import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
AGENT = HERE.parent.parent / "agent" / "target" / "adhoc-crashfuzz-agent-0.1.0.jar"
BUILD = HERE / "build"
DOCKER = ["sudo", "-n", "docker"]
NETWORK = "adhocfuzz-tiny"
IMAGE = os.environ.get("ADHOCFUZZ_JAVA8_IMAGE",
                       "causynth-openjdk8-build:ubuntu18")


def command(*args, check=True):
    return subprocess.run(DOCKER + list(args), check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    host = os.environ["ADHOCFUZZ_CONTROLLER_HOST"]
    port = os.environ["ADHOCFUZZ_CONTROLLER_PORT"]
    trace = run_dir / "traces"
    trace.mkdir(parents=True, exist_ok=True)
    if not AGENT.is_file():
        raise RuntimeError("build the Java agent first: " + str(AGENT))
    BUILD.mkdir(exist_ok=True)
    subprocess.run(["javac", "-source", "8", "-target", "8", "-cp",
                    str(AGENT), "-d", str(BUILD), str(HERE / "Node.java")],
                   check=True)

    for node in ("a", "b"):
        command("rm", "-f", "adhocfuzz-tiny-" + node, check=False)
    if command("network", "inspect", NETWORK, check=False).returncode:
        command("network", "create", NETWORK)
    for node in ("a", "b"):
        name = "adhocfuzz-tiny-" + node
        args = ["run", "-d", "--name", name, "--network", NETWORK,
                "--add-host=host.docker.internal:host-gateway",
                "-e", "ADHOCFUZZ_NODE_ID=" + node,
                "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
                "-e", "ADHOCFUZZ_CONTROLLER_HOST=" + host,
                "-e", "ADHOCFUZZ_CONTROLLER_PORT=" + port,
                "-v", str(trace) + ":/traces",
                "-v", str(BUILD) + ":/classes:ro",
                "-v", str(AGENT) + ":/agent.jar:ro",
                "-v", str(HERE / "agent.properties") + ":/agent.properties:ro"]
        if node == "b":
            args.extend(["-p", "127.0.0.1::5052"])
        args.extend(["--entrypoint", "java", IMAGE,
                     "-javaagent:/agent.jar=/agent.properties",
                     "-cp", "/classes:/agent.jar", "example.tiny.Node",
                     node.upper()])
        command(*args)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        ready = ["READY " + node.upper() in command(
            "logs", "adhocfuzz-tiny-" + node).stdout
            for node in ("a", "b")]
        if all(ready):
            print("A and B ready")
            return
        time.sleep(0.2)
    for node in ("a", "b"):
        result = command("logs", "adhocfuzz-tiny-" + node, check=False)
        print(node, result.stdout, result.stderr)
    raise RuntimeError("tiny cluster did not become ready")


if __name__ == "__main__":
    main()
