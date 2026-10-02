"""Start each DataNode with two DISK volumes for disk balancer plans."""

from __future__ import annotations

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_key"))
import prepare as base  # noqa: E402


original_xml_config = base.xml_config
original_hadoop_args = base.hadoop_args


def xml_config(path, values):
    if path.name == "hdfs-site.xml":
        values = dict(values)
        values["dfs.datanode.data.dir"] = (
            "[DISK]file:///data/disk-a,[DISK]file:///data/disk-b")
        values["dfs.disk.balancer.enabled"] = "true"
        values["dfs.blocksize"] = 1048576
        values["dfs.datanode.du.reserved"] = 0
        values[
            "dfs.datanode.round-robin-volume-choosing-policy.additional-available-space"
        ] = 0
    original_xml_config(path, values)


def hadoop_args(name, conf, data, trace, detached=True):
    args = original_hadoop_args(name, conf, data, trace, detached)
    if name.startswith("dn"):
        # Distinct filesystems make the DataNode report distinct volume
        # capacities and usage to DiskBalancer. The tmpfs mounts are scoped
        # to these experiment containers and vanish when they are removed.
        args[args.index("--entrypoint"):args.index("--entrypoint")] = [
            "--tmpfs", "/data/disk-a:size=256m",
            "--tmpfs", "/data/disk-b:size=512m",
        ]
    return args


def main():
    base.xml_config = xml_config
    base.hadoop_args = hadoop_args
    base.main()


if __name__ == "__main__":
    main()
