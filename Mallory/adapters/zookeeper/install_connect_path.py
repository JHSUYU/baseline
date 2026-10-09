#!/usr/bin/env python3
"""Add a scoped connect-packet door to a separate request-path overlay.

Session creation reaches SessionTrackerImpl.setOwner before ZooKeeper receives
an ordinary client request.  The connect door preserves that earlier client
input through the existing request/task and quorum-packet hooks.
"""

import argparse
from pathlib import Path

from install import replace_once


SERVER = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server")


def install(root: Path) -> None:
    hooks = root / SERVER / "quorum/MalloryZkHooks.java"
    server = root / SERVER / "ZooKeeperServer.java"
    if not hooks.is_file() or not server.is_file():
        raise RuntimeError("A separate request-path ZooKeeper overlay is required")
    helper = hooks.read_text(encoding="utf-8")
    source = server.read_text(encoding="utf-8")
    hooked = "public static Scope connectRequestScope(" in helper
    scoped = "MalloryZkHooks.connectRequestScope(getServerId(), sessionId)" in source
    if hooked != scoped:
        raise RuntimeError("Partial connect-path overlay")
    if hooked:
        return
    if "public static Scope clientRequestScope(" not in helper or \
            "public static Scope quorumRequestScope(" not in helper:
        raise RuntimeError("Install the request-path overlay first")

    replace_once(
        hooks,
        '    private static final String CLIENT_READ_DOOR = "zookeeper.client.request.read";',
        '    private static final String CLIENT_READ_DOOR = "zookeeper.client.request.read";\n'
        '    private static final String CLIENT_CONNECT_DOOR = "zookeeper.client.connect.read";',
    )
    replace_once(
        hooks,
        "    public static Scope clientRequestScope(long sid, long sessionId, int xid, int opcode) ",
        "    /** Correlate a decoded ConnectRequest with its queued create-session request. */\n"
        "    public static Scope connectRequestScope(long sid, long sessionId) throws IOException {\n"
        "        node(sid);\n"
        '        String token = "zk-connect:" + sid + ":" + Long.toHexString(sessionId) + ":"\n'
        "                       + NEXT_CLIENT.incrementAndGet();\n"
        "        Object context = invoke(\"receiveScope\",\n"
        "            new Class<?>[] {String.class, String.class, String.class, String.class},\n"
        '            "zookeeper-client", token, sessionId == 0 ? "new-session" : "renew-session",\n'
        "            CLIENT_CONNECT_DOOR);\n"
        "        Scope scope = new Scope(context instanceof AutoCloseable ? (AutoCloseable) context : null);\n"
        "        try {\n"
        "            beforeDoor(CLIENT_CONNECT_DOOR);\n"
        "            return scope;\n"
        "        } catch (IOException | RuntimeException | Error failure) {\n"
        "            scope.close();\n"
        "            throw failure;\n"
        "        }\n"
        "    }\n\n"
        "    public static Scope clientRequestScope(long sid, long sessionId, int xid, int opcode) ",
    )
    replace_once(
        server,
        "        long sessionId = connReq.getSessionId();\n        int tokensNeeded = 1;",
        "        long sessionId = connReq.getSessionId();\n"
        "        try (org.apache.zookeeper.server.quorum.MalloryZkHooks.Scope malloryConnectScope =\n"
        "                 org.apache.zookeeper.server.quorum.MalloryZkHooks.connectRequestScope(\n"
        "                     getServerId(), sessionId)) {\n"
        "        int tokensNeeded = 1;",
    )
    replace_once(
        server,
        "            ServerMetrics.getMetrics().CONNECTION_REVALIDATE_COUNT.add(1);\n\n"
        "        }\n    }\n\n    /**\n     * Validate if a particular session can be reestablished.",
        "            ServerMetrics.getMetrics().CONNECTION_REVALIDATE_COUNT.add(1);\n\n"
        "        }\n"
        "        } // Mallory connect-request scope\n"
        "    }\n\n    /**\n     * Validate if a particular session can be reestablished.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
