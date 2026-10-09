#!/usr/bin/env python3
"""Scope the actual leader REQUEST receive to its matched packet token."""

import argparse
from pathlib import Path

from install import replace_once


HOOK = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java")


def install(root: Path) -> None:
    source = root / HOOK
    body = source.read_text(encoding="utf-8")
    if "Mallory scoped REQUEST receive" in body:
        return
    if "public static Scope quorumRequestScope(QuorumPacket packet, long sid)" not in body:
        raise ValueError("exact packet-object request handoff must be installed first")
    old = """        call(sending ? "send" : "receive",
             new Class<?>[] {String.class, String.class, String.class, String.class},
             TRANSPORT, correlation, port, sending ? WRITE_DOOR : READ_DOOR);
"""
    new = """        if (!sending && packet.getType() == Leader.REQUEST) {
            // Mallory scoped REQUEST receive: retain the physical packet's
            // correlation for this RECV only, then restore the prior context.
            Object context = invoke("withCausalContext",
                new Class<?>[] {String.class}, correlation);
            try (Scope receiveScope = new Scope(
                    context instanceof AutoCloseable ? (AutoCloseable) context : null)) {
                call("receive",
                     new Class<?>[] {String.class, String.class, String.class, String.class},
                     TRANSPORT, correlation, port, READ_DOOR);
            }
        } else {
            call(sending ? "send" : "receive",
                 new Class<?>[] {String.class, String.class, String.class, String.class},
                 TRANSPORT, correlation, port, sending ? WRITE_DOOR : READ_DOOR);
        }
"""
    replace_once(source, old, new)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
