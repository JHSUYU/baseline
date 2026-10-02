"""Start DataNodes with enough cache capacity for pending-cache decisions."""

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
        values["dfs.datanode.max.locked.memory"] = 67108864
    original_xml_config(path, values)


def hadoop_args(name, conf, data, trace, detached=True):
    args = original_hadoop_args(name, conf, data, trace, detached)
    if name in ("dn1", "dn2", "dn3"):
        index = args.index("--entrypoint")
        args[index:index] = ["--ulimit", "memlock=67108864:67108864"]
    return args


def main():
    base.xml_config = xml_config
    base.hadoop_args = hadoop_args
    base.main()


if __name__ == "__main__":
    main()
