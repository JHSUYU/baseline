"""HDFS cluster variant with a RAM_DISK volume and local-read socket."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_key"))
import prepare as base  # noqa: E402


original_xml_config = base.xml_config
original_hadoop_args = base.hadoop_args
original_wait_for = base.wait_for


def xml_config(path, values):
    if path.name == "hdfs-site.xml":
        values = dict(values)
        values.update({
            "dfs.datanode.data.dir": (
                "[DISK]file:///data/dn,[RAM_DISK]file:///data/ramdisk"),
            "dfs.client.read.shortcircuit": "true",
            "dfs.domain.socket.path": "/run/shortcircuit._PORT",
        })
    original_xml_config(path, values)


def hadoop_args(name, conf, data, trace, detached=True):
    args = original_hadoop_args(name, conf, data, trace, detached)
    if name in ("dn1", "dn2", "dn3"):
        index = args.index("--entrypoint")
        args[index:index] = ["--tmpfs", "/data/ramdisk:rw,size=67108864"]
    return args


def wait_for(predicate, description, seconds=100):
    if description != "three DataNodes":
        return original_wait_for(predicate, description, seconds)
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    point_events = run_dir / "point-events.jsonl"

    def ready():
        result = base.docker(
            "exec", base.PREFIX + "nn", "/opt/hadoop/bin/hdfs",
            "dfsadmin", "-report", check=False)
        if "Live datanodes (3)" in result.stdout:
            return True, result.stdout[-1200:]
        matched = False
        if point_events.exists():
            for line in point_events.read_text().splitlines():
                try:
                    matched |= bool(json.loads(line).get("matched"))
                except json.JSONDecodeError:
                    continue
        if matched and "Live datanodes (2)" in result.stdout:
            return True, "matched startup crash; two DataNodes available"
        return False, result.stdout[-1200:]

    return original_wait_for(ready, description, seconds)


def main():
    base.xml_config = xml_config
    base.hadoop_args = hadoop_args
    base.wait_for = wait_for
    base.main()


if __name__ == "__main__":
    main()
