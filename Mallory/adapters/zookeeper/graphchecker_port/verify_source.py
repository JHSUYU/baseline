#!/usr/bin/env python3
"""Fail closed if the ZooKeeper 3.8.7 protocol anchors have moved.

This is a read-only preflight for the Soot weave and original JUnit source.
The weave itself still checks the number of matching Jimple sites.
"""

import argparse
from pathlib import Path


def require_line(lines: list[str], number: int, fragment: str, source: Path) -> None:
    actual = lines[number - 1] if len(lines) >= number else "<missing>"
    if fragment not in actual:
        raise RuntimeError(
            f"{source}:{number}: expected {fragment!r}; got {actual.strip()!r}"
        )


def require_order(text: str, fragments: list[str], source: Path) -> None:
    cursor = 0
    for fragment in fragments:
        position = text.find(fragment, cursor)
        if position < 0:
            raise RuntimeError(f"{source}: missing ordered anchor {fragment!r}")
        cursor = position + len(fragment)


def verify(root: Path) -> None:
    quorum = root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum"
    handler = quorum / "LearnerHandler.java"
    learner = quorum / "Learner.java"
    peer = quorum / "QuorumPeer.java"
    test = root / "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java"
    for source in (handler, learner, peer, test):
        if not source.is_file():
            raise RuntimeError(f"missing original ZooKeeper source: {source}")

    handler_lines = handler.read_text(encoding="utf-8").splitlines()
    learner_lines = learner.read_text(encoding="utf-8").splitlines()
    peer_text = peer.read_text(encoding="utf-8")
    require_line(handler_lines, 537, 'oa.writeRecord(newEpochPacket, "packet")', handler)
    require_line(handler_lines, 539, "bufferedOutput.flush()", handler)
    require_line(handler_lines, 541, 'ia.readRecord(ackEpochPacket, "packet")', handler)
    require_line(learner_lines, 228, 'leaderIs.readRecord(pp, "packet")', learner)
    require_order(
        learner.read_text(encoding="utf-8"),
        ["void writePacketNow(QuorumPacket pp, boolean flush)",
         'leaderOs.writeRecord(pp, "packet")',
         "if (flush) {", "bufferedOutput.flush()"], learner,
    )
    require_order(peer_text,
                  ["private long readLongFromFile(String name)",
                   "return Long.parseLong(line)",
                   "void writeLongToFile(String name, final long value)",
                   "new AtomicFileWritingIdiom(file"], peer)
    if "void testRollingRestart(" not in test.read_text(encoding="utf-8"):
        raise RuntimeError(f"{test}: original testRollingRestart workload absent")
    print("ZooKeeper 3.8.7 quorum, epoch-file and original JUnit anchors verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    verify(args.source_root.resolve())


if __name__ == "__main__":
    main()
