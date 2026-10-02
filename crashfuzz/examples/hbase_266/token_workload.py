"""Request a delegation token to diagnose reachability of retrievePassword."""

import os
from pathlib import Path
import subprocess
import sys

from prepare import (AGENT, AGENT_PROPERTIES, DOCKER, HBASE, HERE,
                     IMAGE, NETWORK)


def main() -> int:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    conf = run_dir / "conf"
    java = HERE / "TokenProbe.java"
    compiled = run_dir / "token-classes"
    compiled.mkdir()
    subprocess.run(["javac", "-cp", str(HBASE / "lib/*"), "-d",
                    str(compiled), str(java)], check=True)
    argv = DOCKER + ["run", "--rm", "--network", NETWORK,
                     "--add-host=host.docker.internal:host-gateway",
                     "-e", "HBASE_CONF_DIR=/conf",
                     "-e", "ADHOCFUZZ_NODE_ID=client",
                     "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
                     "-e", "ADHOCFUZZ_CONTROLLER_HOST=host.docker.internal",
                     "-e", "ADHOCFUZZ_CONTROLLER_PORT="
                     + os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
                     "-v", str(HBASE) + ":/opt/hbase:ro",
                     "-v", str(conf) + ":/conf:ro",
                     "-v", str(compiled) + ":/probe:ro",
                     "-v", str(run_dir / "traces") + ":/traces",
                     "-v", str(AGENT) + ":/agent.jar:ro",
                     "-v", str(AGENT_PROPERTIES) + ":/agent.properties:ro",
                     "--entrypoint", "/opt/java/openjdk/bin/java", IMAGE,
                     "-javaagent:/agent.jar=/agent.properties",
                     "-cp", ("/probe:/conf:/opt/hbase/lib/shaded-clients/*:"
                             "/opt/hbase/lib/client-facing-thirdparty/*"),
                     "TokenProbe"]
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120)
    (run_dir / "token-probe.stdout").write_text(result.stdout)
    (run_dir / "token-probe.stderr").write_text(result.stderr)
    print(result.stdout[-500:])
    if result.returncode:
        print(result.stderr[-1000:])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
