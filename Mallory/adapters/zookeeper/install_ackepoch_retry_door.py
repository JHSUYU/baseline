#!/usr/bin/env python3
"""Add one follower-side ACKEPOCH door after acceptedEpoch is persisted."""

import argparse
from pathlib import Path

from install import replace_once


QUORUM = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum")
SITE = "zookeeper.quorum.ackepoch.write"


def install(root: Path) -> None:
    hooks = root / QUORUM / "MalloryZkHooks.java"
    learner = root / QUORUM / "Learner.java"
    if not hooks.is_file() or not learner.is_file():
        raise FileNotFoundError("isolated ACKEPOCH retry overlay is absent")
    if "public static void ackEpochWriteDoor(" in hooks.read_text(encoding="utf-8"):
        if "MalloryZkHooks.ackEpochWriteDoor(ackNewEpoch, self)" not in learner.read_text(encoding="utf-8"):
            raise ValueError("partial ACKEPOCH write door")
        return
    if ("public static Scope followingScope(" not in hooks.read_text(encoding="utf-8")
            or "public static Scope quorumAckEpochScope(" not in hooks.read_text(encoding="utf-8")):
        raise ValueError("exact retry and packet correlation prerequisites are absent")
    replace_once(
        hooks,
        '    private static final String WRITE_DOOR = "zookeeper.quorum.archive.writeRecord";',
        '    private static final String WRITE_DOOR = "zookeeper.quorum.archive.writeRecord";\n'
        f'    private static final String ACK_EPOCH_WRITE_DOOR = "{SITE}";',
    )
    replace_once(
        hooks,
        "    private static void beforeDoor(String site) throws IOException {",
        "    /** The persisted acceptedEpoch may be reused on the next FOLLOWING attempt. */\n"
        "    public static void ackEpochWriteDoor(QuorumPacket packet, QuorumPeer peer)\n"
        "            throws IOException {\n"
        "        if (packet == null || packet.getType() != Leader.ACKEPOCH\n"
        "                || peer == null || Thread.currentThread() != peer) {\n"
        '            throw new IllegalStateException("ACKEPOCH write door requires exact peer thread");\n'
        "        }\n"
        "        nodePeer(peer);\n"
        "        beforeDoor(ACK_EPOCH_WRITE_DOOR);\n"
        "    }\n\n"
        "    private static void beforeDoor(String site) throws IOException {",
    )
    replace_once(
        learner,
        "            QuorumPacket ackNewEpoch = new QuorumPacket(Leader.ACKEPOCH, lastLoggedZxid, epochBytes, null);\n"
        "            writePacket(ackNewEpoch, true);",
        "            QuorumPacket ackNewEpoch = new QuorumPacket(Leader.ACKEPOCH, lastLoggedZxid, epochBytes, null);\n"
        "            MalloryZkHooks.ackEpochWriteDoor(ackNewEpoch, self);\n"
        "            writePacket(ackNewEpoch, true);",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
