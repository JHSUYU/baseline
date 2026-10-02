"""Give the isolated HDFS cluster a shared local JCEKS key provider."""

from __future__ import annotations

import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_key"))
import prepare as base  # noqa: E402


original_xml_config = base.xml_config
original_hadoop_args = base.hadoop_args


def xml_config(path, values):
    if path.name == "core-site.xml":
        values = dict(values)
        values["hadoop.security.key.provider.path"] = (
            "jceks://file/keys/adhoc.jceks")
    original_xml_config(path, values)


def hadoop_args(name, conf, data, trace, detached=True):
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    keys = run_dir / "keys"
    keys.mkdir(exist_ok=True)
    if name == "format":
        create = original_hadoop_args("key-init", conf, data, trace,
                                      detached=False)
        create[create.index("--entrypoint") + 1] = "/opt/hadoop/bin/hadoop"
        create[create.index("--entrypoint"):create.index("--entrypoint")] = [
            "-v", str(keys) + ":/keys"]
        base.docker(*(create + ["key", "create", "adhoc-key", "-size", "128"]))
    args = original_hadoop_args(name, conf, data, trace, detached)
    args[args.index("--entrypoint"):args.index("--entrypoint")] = [
        "-v", str(keys) + ":/keys"]
    return args


def main():
    base.xml_config = xml_config
    base.hadoop_args = hadoop_args
    base.main()


if __name__ == "__main__":
    main()
