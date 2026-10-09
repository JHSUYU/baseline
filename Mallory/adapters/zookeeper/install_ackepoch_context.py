#!/usr/bin/env python3
"""Carry an exact ACKEPOCH packet receive into Leader.waitForEpochAck."""

import argparse
from pathlib import Path


QUORUM = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum")


def replace_once(path: Path, old: str, new: str) -> None:
    contents = path.read_text(encoding="utf-8")
    if contents.count(old) != 1:
        raise ValueError(f"expected one source anchor in {path}: {old[:72]!r}")
    path.write_text(contents.replace(old, new, 1), encoding="utf-8")


def install(root: Path) -> None:
    hooks = root / QUORUM / "MalloryZkHooks.java"
    handler = root / QUORUM / "LearnerHandler.java"
    if not hooks.is_file() or not handler.is_file():
        raise FileNotFoundError("ZooKeeper quorum overlay source is absent")
    before = hooks.read_text(encoding="utf-8")
    if "public static Scope quorumAckEpochScope(" in before:
        if "MalloryZkHooks.quorumAckEpochScope(ackEpochPacket," not in handler.read_text():
            raise ValueError("partial ACKEPOCH source overlay")
        return
    if "public static Scope quorumRequestScope(" not in before:
        raise ValueError("exact packet-object request context prerequisite is absent")

    replace_once(
        hooks,
        "            if (packet.getType() == Leader.REQUEST)\n"
        "                LAST_RECEIVED.set(new ReceivedPacket(packet, correlation));",
        "            if (packet.getType() == Leader.REQUEST\n"
        "                || packet.getType() == Leader.ACKEPOCH)\n"
        "                LAST_RECEIVED.set(new ReceivedPacket(packet, correlation));",
    )
    replace_once(
        hooks,
        "    /** Continue from the exact QuorumPacket read into the leader's request queue. */",
        "    /** Continue only from the exact ACKEPOCH object read on this thread. */\n"
        "    public static Scope quorumAckEpochScope(QuorumPacket packet, long masterId) {\n"
        "        node(masterId);\n"
        "        ReceivedPacket received = LAST_RECEIVED.get();\n"
        "        LAST_RECEIVED.remove();\n"
        "        if (packet.getType() != Leader.ACKEPOCH || received == null\n"
        "            || received.packet != packet) return new Scope(null);\n"
        "        Object context = invoke(\"withCausalContext\",\n"
        "            new Class<?>[] {String.class}, received.correlation);\n"
        "        AutoCloseable scope = context instanceof AutoCloseable ? (AutoCloseable) context : null;\n"
        '        String region = "zookeeper.leader.ackepoch";\n'
        "        try {\n"
        "            call(\"regionEnter\", new Class<?>[] {String.class}, region);\n"
        "            return new Scope(scope, region);\n"
        "        } catch (RuntimeException | Error failure) {\n"
        "            if (scope != null) {\n"
        "                try { scope.close(); } catch (Exception closeFailure) { failure.addSuppressed(closeFailure); }\n"
        "            }\n"
        "            throw failure;\n"
        "        }\n"
        "    }\n\n"
        "    /** Continue from the exact QuorumPacket read into the leader's request queue. */",
    )
    replace_once(
        handler,
        "                learnerMaster.waitForEpochAck(this.getSid(), ss);\n"
        "            }\n"
        "            peerLastZxid = ss.getLastZxid();",
        "                try (MalloryZkHooks.Scope malloryAckScope =\n"
        "                         MalloryZkHooks.quorumAckEpochScope(ackEpochPacket,\n"
        "                             MalloryZkHooks.masterId(learnerMaster))) {\n"
        "                    learnerMaster.waitForEpochAck(this.getSid(), ss);\n"
        "                }\n"
        "            }\n"
        "            peerLastZxid = ss.getLastZxid();",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
