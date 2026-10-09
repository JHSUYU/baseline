#!/usr/bin/env python3
"""Install the ZooKeeper hooks with a separate Surefire lane on node2.

This is deliberately separate from install.py: the first ZooKeeper overlay
and its completed ZOOKEEPER-01 evidence remain pinned to their original
source and port configuration.
"""

import argparse
from pathlib import Path

from install import install, replace_once


def install_lane2(root: Path) -> None:
    pom = root / "zookeeper-server/pom.xml"
    existing = pom.read_text(encoding="utf-8")
    if "<mallory.test.dir>" in existing:
        expected = (
            "-Dtest.junit.threads=8 -Dzookeeper.junit.threadid=8",
            "<build.test.dir>${mallory.test.dir}</build.test.dir>",
            "${mallory.agent.arg}",
        )
        if not all(fragment in existing for fragment in expected):
            raise RuntimeError("Incomplete ZooKeeper lane2 Surefire configuration")
        if not (root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java").is_file():
            raise RuntimeError("Lane2 Surefire configuration exists without quorum hooks")
        return
    install(root)
    default_test_dir = root / "mallory-test-data"
    replace_once(
        pom,
        "<properties><mallory.agent.arg></mallory.agent.arg></properties>",
        "<properties><mallory.agent.arg></mallory.agent.arg>"
        f"<mallory.test.dir>{default_test_dir}</mallory.test.dir></properties>",
    )
    replace_once(
        pom,
        "-Dtest.junit.threads=${surefire-forkcount} "
        "-Dzookeeper.junit.threadid=${surefire.forkNumber}",
        "-Dtest.junit.threads=8 -Dzookeeper.junit.threadid=8",
    )
    replace_once(
        pom,
        "<build.test.dir>${project.build.directory}/surefire</build.test.dir>",
        "<build.test.dir>${mallory.test.dir}</build.test.dir>",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install_lane2(args.source_root.resolve())
