"""Add three JournalNodes so the sampled QuorumCall check is reachable."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_key"))
import prepare as base  # noqa: E402


JOURNALS = ("jn1", "jn2", "jn3")
original_xml_config = base.xml_config
original_hadoop_args = base.hadoop_args


def xml_config(path, values):
    if path.name == "hdfs-site.xml":
        values = dict(values)
        addresses = ";".join(base.PREFIX + node + ":8485"
                             for node in JOURNALS)
        values["dfs.namenode.edits.dir"] = (
            "qjournal://" + addresses + "/adhoc-baseline")
        values["dfs.journalnode.edits.dir"] = "/data/journal"
        values["dfs.journalnode.rpc-address"] = "0.0.0.0:8485"
        values["dfs.journalnode.http-address"] = "0.0.0.0:8480"
    original_xml_config(path, values)


def hadoop_args(name, conf, data, trace, detached=True):
    if name == "format":
        run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
        for journal in JOURNALS:
            base.docker("rm", "-f", base.PREFIX + journal, check=False)
            journal_state = run_dir / "state" / journal
            journal_state.mkdir(parents=True)
            command = original_hadoop_args(
                journal, conf, journal_state, trace) + ["journalnode"]
            base.docker(*command)
        time.sleep(5)
    return original_hadoop_args(name, conf, data, trace, detached)


def main():
    base.xml_config = xml_config
    base.hadoop_args = hadoop_args
    base.main()


if __name__ == "__main__":
    main()
