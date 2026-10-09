#!/usr/bin/env python3
"""Patch a separate ZooKeeper overlay to keep tracker regions on the peer epoch.

The existing lane2 overlay and its campaign remain immutable. Apply this only
to a fresh copy of that overlay, then compile and attest it as a new version.
"""

import argparse
from pathlib import Path

from install import replace_once


SERVER = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server")
REGISTER = "MalloryZkHooks.registerTracker(this, serverId);"
CLIENT_SCOPE = "MalloryZkHooks.clientRequestScope(getServerId(), cnxn.getSessionId(), h.getXid(), h.getType())"
READ_ONLY_REGISTER = "MalloryZkHooks.registerPeerReceiver(this, self.getMyId());"


def install_epoch_fix(root: Path) -> None:
    hooks = root / SERVER / "quorum/MalloryZkHooks.java"
    tracker = root / SERVER / "SessionTrackerImpl.java"
    server = root / SERVER / "ZooKeeperServer.java"
    read_only = root / SERVER / "quorum/ReadOnlyZooKeeperServer.java"
    if not hooks.is_file() or not tracker.is_file() or not server.is_file() or not read_only.is_file():
        raise RuntimeError("Apply the epoch fix only to a ZooKeeper Mallory overlay")
    hook_text = hooks.read_text(encoding="utf-8")
    tracker_text = tracker.read_text(encoding="utf-8")
    already_hooked = "public static void registerTracker(Object tracker, long sid)" in hook_text
    already_registered = REGISTER in tracker_text
    if already_hooked != already_registered:
        raise RuntimeError("Partial tracker epoch patch")
    if not already_hooked:
        replace_once(
            hooks,
            "    static long masterId(LearnerMaster master) {",
            "    /** Bind a tracker receiver to its peer's actual lifecycle epoch. */\n"
            "    public static void registerTracker(Object tracker, long sid) {\n"
            "        if (tracker == null || sid < 0) return;\n"
            "        AtomicInteger epoch = EPOCHS.get(sid);\n"
            "        call(\"registerNode\",\n"
            "             new Class<?>[] {Object.class, String.class, int.class},\n"
            "             tracker, \"zk\" + sid, epoch == null ? 0 : epoch.get());\n"
            "    }\n\n"
            "    static long masterId(LearnerMaster master) {",
        )
        replace_once(
            tracker,
            "        this.malloryServerId = serverId;",
            "        this.malloryServerId = serverId;\n"
            "        org.apache.zookeeper.server.quorum.MalloryZkHooks.registerTracker(this, serverId);",
        )

    hook_text = hooks.read_text(encoding="utf-8")
    client_hooked = "public static Scope clientRequestScope(" in hook_text
    client_scoped = CLIENT_SCOPE in server.read_text(encoding="utf-8")
    if client_hooked != client_scoped:
        raise RuntimeError("Partial client-request scope patch")
    if not client_hooked:
        replace_once(
            hooks,
            '    private static final String READ_DOOR = "zookeeper.quorum.archive.readRecord";',
            '    private static final String READ_DOOR = "zookeeper.quorum.archive.readRecord";\n'
            '    private static final String CLIENT_READ_DOOR = "zookeeper.client.request.read";',
        )
        replace_once(
            hooks,
            "    private static final AtomicLong NEXT_TASK = new AtomicLong();",
            "    private static final AtomicLong NEXT_TASK = new AtomicLong();\n"
            "    private static final AtomicLong NEXT_CLIENT = new AtomicLong();",
        )
        replace_once(
            hooks,
            "    public static void submit(Request request, long sid, String site) {",
            "    /** Keep the parsed client packet's identity until its request is queued. */\n"
            "    public static Scope clientRequestScope(long sid, long sessionId, int xid, int opcode) "
            "throws IOException {\n"
            "        node(sid);\n"
            "        String token = \"zk-client:\" + sid + \":\" + Long.toHexString(sessionId) + \":\"\n"
            "                       + xid + \":\" + NEXT_CLIENT.incrementAndGet();\n"
            "        Object context = invoke(\"receiveScope\",\n"
            "            new Class<?>[] {String.class, String.class, String.class, String.class},\n"
            "            \"zookeeper-client\", token, \"opcode:\" + opcode, CLIENT_READ_DOOR);\n"
            "        Scope scope = new Scope(context instanceof AutoCloseable ? (AutoCloseable) context : null);\n"
            "        try {\n"
            "            beforeDoor(CLIENT_READ_DOOR);\n"
            "            return scope;\n"
            "        } catch (IOException | RuntimeException | Error failure) {\n"
            "            scope.close();\n"
            "            throw failure;\n"
            "        }\n"
            "    }\n\n"
            "    public static void submit(Request request, long sid, String site) {",
        )
        replace_once(
            server,
            '        h.deserialize(bia, "header");',
            '        h.deserialize(bia, "header");\n'
            "        try (org.apache.zookeeper.server.quorum.MalloryZkHooks.Scope malloryClientScope =\n"
            "                 org.apache.zookeeper.server.quorum.MalloryZkHooks.clientRequestScope("
            "getServerId(), cnxn.getSessionId(), h.getXid(), h.getType())) {",
        )
        replace_once(
            server,
            "                submitRequest(si);\n            }\n        }\n    }\n\n"
            "    private static boolean isSaslSuperUser(String id) {",
            "                submitRequest(si);\n            }\n        }\n"
            "        } // Mallory client-request scope\n    }\n\n"
            "    private static boolean isSaslSuperUser(String id) {",
        )

    peer_hooked = "public static void registerPeerReceiver(Object receiver, long sid)" in \
        hooks.read_text(encoding="utf-8")
    peer_registered = READ_ONLY_REGISTER in read_only.read_text(encoding="utf-8")
    if peer_hooked != peer_registered:
        raise RuntimeError("Partial read-only server epoch patch")
    if not peer_hooked:
        replace_once(
            hooks,
            "    static long masterId(LearnerMaster master) {",
            "    public static void registerPeerReceiver(Object receiver, long sid) {\n"
            "        registerTracker(receiver, sid);\n"
            "    }\n\n"
            "    static long masterId(LearnerMaster master) {",
        )
        replace_once(
            read_only,
            "        this.self = self;",
            "        this.self = self;\n"
            "        MalloryZkHooks.registerPeerReceiver(this, self.getMyId());",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install_epoch_fix(args.source_root.resolve())
