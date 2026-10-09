#!/usr/bin/env python3
"""Extend an epoch-fixed ZooKeeper overlay with an exact follower-to-leader request path."""

import argparse
from pathlib import Path

from install import replace_once


SERVER = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server")
QUORUM = SERVER / "quorum"


def install(root: Path) -> None:
    hooks = root / QUORUM / "MalloryZkHooks.java"
    follower = root / QUORUM / "FollowerRequestProcessor.java"
    handler = root / QUORUM / "LearnerHandler.java"
    if not all(path.is_file() for path in (hooks, follower, handler)):
        raise RuntimeError("Apply only to a separate epoch-fixed ZooKeeper overlay")
    helper = hooks.read_text(encoding="utf-8")
    if "public static Scope quorumRequestScope(" in helper:
        if "MalloryZkHooks.quorumRequestScope(qp," not in handler.read_text(encoding="utf-8"):
            raise RuntimeError("Partial request-path overlay")
        return
    if "public static Scope clientRequestScope(" not in helper:
        raise RuntimeError("Client request scope must be installed first")

    replace_once(
        follower,
        "                Request request = queuedRequests.take();",
        "                Request request = queuedRequests.take();\n"
        "                try (MalloryZkHooks.Scope malloryRequestScope =\n"
        "                         MalloryZkHooks.claim(request, zks.getServerId(),\n"
        '                             "FollowerRequestProcessor#take")) {',
    )
    replace_once(
        follower,
        "                }\n            }\n        } catch (RuntimeException e) { // spotbugs require explicit catch of RuntimeException",
        "                }\n"
        "                } // Mallory request scope\n"
        "            }\n"
        "        } catch (RuntimeException e) { // spotbugs require explicit catch of RuntimeException",
    )
    replace_once(
        follower,
        "                    queuedRequests.add(upgradeRequest);",
        "                    MalloryZkHooks.submit(upgradeRequest, zks.getServerId(),\n"
        '                        "FollowerRequestProcessor#upgradeAdd");\n'
        "                    queuedRequests.add(upgradeRequest);",
    )
    replace_once(
        follower,
        "            queuedRequests.add(request);",
        "            MalloryZkHooks.submit(request, zks.getServerId(),\n"
        '                "FollowerRequestProcessor#add");\n'
        "            queuedRequests.add(request);",
    )

    replace_once(
        hooks,
        "import java.net.Socket;",
        "import java.net.Socket;\n"
        "import java.security.MessageDigest;\n"
        "import java.security.NoSuchAlgorithmException;",
    )
    replace_once(
        hooks,
        "    private static final AtomicLong NEXT_CLIENT = new AtomicLong();",
        "    private static final AtomicLong NEXT_CLIENT = new AtomicLong();\n"
        "    private static final ThreadLocal<ReceivedPacket> LAST_RECEIVED = new ThreadLocal<>();",
    )
    replace_once(
        hooks,
        "    private static final class Counts {",
        "    private static final class ReceivedPacket {\n"
        "        final QuorumPacket packet;\n"
        "        final String correlation;\n"
        "        ReceivedPacket(QuorumPacket packet, String correlation) {\n"
        "            this.packet = packet;\n"
        "            this.correlation = correlation;\n"
        "        }\n"
        "    }\n\n"
        "    private static final class Counts {",
    )
    replace_once(
        hooks,
        "    private static void packet(Socket socket, long sid, Record record, boolean sending) {",
        "    private static String requestDigest(byte[] bytes) {\n"
        "        try {\n"
        '            byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);\n'
        '            final char[] alphabet = "0123456789abcdef".toCharArray();\n'
        "            char[] hex = new char[digest.length * 2];\n"
        "            for (int i = 0; i < digest.length; i++) {\n"
        "                hex[2 * i] = alphabet[(digest[i] >>> 4) & 15];\n"
        "                hex[2 * i + 1] = alphabet[digest[i] & 15];\n"
        "            }\n"
        "            return new String(hex);\n"
        "        } catch (NoSuchAlgorithmException impossible) {\n"
        "            throw new IllegalStateException(impossible);\n"
        "        }\n"
        "    }\n\n"
        "    private static void packet(Socket socket, long sid, Record record, boolean sending) {",
    )
    replace_once(
        hooks,
        '        String port = packet.getType() + ":" + packet.getZxid();',
        '        String port = packet.getType() == Leader.REQUEST\n'
        '            ? "REQUEST:" + requestDigest(packet.getData())\n'
        '            : packet.getType() + ":" + packet.getZxid();\n'
        "        if (!sending) {\n"
        "            if (packet.getType() == Leader.REQUEST)\n"
        "                LAST_RECEIVED.set(new ReceivedPacket(packet, correlation));\n"
        "            else LAST_RECEIVED.remove();\n"
        "        }",
    )
    replace_once(
        hooks,
        "    private static void beforeDoor(String site) throws IOException {",
        "    /** Continue from the exact QuorumPacket read into the leader's request queue. */\n"
        "    public static Scope quorumRequestScope(QuorumPacket packet, long sid) {\n"
        "        node(sid);\n"
        "        ReceivedPacket received = LAST_RECEIVED.get();\n"
        "        LAST_RECEIVED.remove();\n"
        "        if (received == null || received.packet != packet) return new Scope(null);\n"
        "        Object context = invoke(\"withCausalContext\",\n"
        "            new Class<?>[] {String.class}, received.correlation);\n"
        "        AutoCloseable scope = context instanceof AutoCloseable ? (AutoCloseable) context : null;\n"
        '        String region = "zookeeper.leader.request";\n'
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
        "    private static void beforeDoor(String site) throws IOException {",
    )
    replace_once(
        hooks,
        "        private final AutoCloseable context;\n"
        "        private Scope(AutoCloseable context) { this.context = context; }\n"
        "        @Override public void close() {\n"
        "            if (context == null) return;\n"
        "            try { context.close(); }\n"
        '            catch (Exception failure) { throw new IllegalStateException("Mallory task scope", failure); }\n'
        "        }",
        "        private final AutoCloseable context;\n"
        "        private final String region;\n"
        "        private Scope(AutoCloseable context) { this(context, null); }\n"
        "        private Scope(AutoCloseable context, String region) {\n"
        "            this.context = context;\n"
        "            this.region = region;\n"
        "        }\n"
        "        @Override public void close() {\n"
        "            try {\n"
        "                if (region != null) call(\"regionExit\", new Class<?>[] {String.class}, region);\n"
        "            } finally {\n"
        "                if (context != null) {\n"
        "                    try { context.close(); }\n"
        '                    catch (Exception failure) { throw new IllegalStateException("Mallory scope", failure); }\n'
        "                }\n"
        "            }\n"
        "        }",
    )
    replace_once(
        handler,
        "                    learnerMaster.submitLearnerRequest(si);",
        "                    try (MalloryZkHooks.Scope malloryRequestScope =\n"
        "                             MalloryZkHooks.quorumRequestScope(qp,\n"
        "                                 MalloryZkHooks.masterId(learnerMaster))) {\n"
        "                        learnerMaster.submitLearnerRequest(si);\n"
        "                    }",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
