#!/usr/bin/env python3
"""Add a bounded same-peer FOLLOWING retry handoff to an isolated ZK overlay."""

import argparse
from pathlib import Path


QUORUM = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum")


def replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(before) != 1:
        raise ValueError(f"expected one source anchor in {path}: {before[:80]!r}")
    path.write_text(text.replace(before, after, 1), encoding="utf-8")


def install(root: Path) -> None:
    hooks = root / QUORUM / "MalloryZkHooks.java"
    peer = root / QUORUM / "QuorumPeer.java"
    follower = root / QUORUM / "Follower.java"
    observer = root / QUORUM / "Observer.java"
    if not all(path.is_file() for path in (hooks, peer, follower, observer)):
        raise FileNotFoundError("the isolated ZooKeeper overlay is incomplete")
    if "followingRetrySubmit(QuorumPeer peer)" in hooks.read_text(encoding="utf-8"):
        legacy_identity = '            + Thread.currentThread().getId() + ":" + System.identityHashCode(peer) + ":"\n'
        if legacy_identity in hooks.read_text(encoding="utf-8"):
            replace_once(hooks, legacy_identity,
                         '            + Thread.currentThread().getId() + ":"\n'
                         '            + Integer.toUnsignedString(System.identityHashCode(peer)) + ":"\n')
        if "MalloryZkHooks.followingRetrySubmit(this);" not in peer.read_text():
            raise ValueError("partial FOLLOWING retry overlay")
        return

    replace_once(hooks,
                 "import java.util.ArrayDeque;\n",
                 "import java.util.ArrayDeque;\nimport java.util.IdentityHashMap;\n")
    replace_once(hooks,
                 "    private static final AtomicLong NEXT_CLIENT = new AtomicLong();\n",
                 "    private static final AtomicLong NEXT_CLIENT = new AtomicLong();\n"
                 "    private static final AtomicLong NEXT_FOLLOWING_RETRY = new AtomicLong();\n"
                 "    private static final Map<QuorumPeer, Integer> PEER_EPOCHS = new IdentityHashMap<>();\n"
                 "    private static final Map<QuorumPeer, FollowingRetry> FOLLOWING_RETRIES = new IdentityHashMap<>();\n"
                 '    private static final String FOLLOWING_REGION = "zookeeper.peer.following";\n'
                 '    private static final String FOLLOWING_RETRY_SITE = "zookeeper.peer.following.retry";\n')
    replace_once(hooks,
                 "    static void startPeer(QuorumPeer peer) {\n",
                 "    private static final class FollowingRetry {\n"
                 "        final QuorumPeer peer;\n"
                 "        final Thread thread;\n"
                 "        final long sid;\n"
                 "        final int epoch;\n"
                 "        final String token;\n"
                 "        FollowingRetry(QuorumPeer peer, Thread thread, long sid, int epoch, String token) {\n"
                 "            this.peer = peer;\n"
                 "            this.thread = thread;\n"
                 "            this.sid = sid;\n"
                 "            this.epoch = epoch;\n"
                 "            this.token = token;\n"
                 "        }\n"
                 "    }\n\n"
                 "    static void startPeer(QuorumPeer peer) {\n")
    replace_once(hooks,
                 "    static void startPeer(QuorumPeer peer) {\n"
                 "        EPOCHS.computeIfAbsent(peer.getMyId(), ignored -> new AtomicInteger(-1)).incrementAndGet();\n"
                 "        node(peer.getMyId());\n"
                 "    }\n",
                 "    static void startPeer(QuorumPeer peer) {\n"
                 "        int epoch = EPOCHS.computeIfAbsent(peer.getMyId(),\n"
                 "            ignored -> new AtomicInteger(-1)).incrementAndGet();\n"
                 "        synchronized (PEER_EPOCHS) { PEER_EPOCHS.put(peer, epoch); }\n"
                 "        nodePeer(peer);\n"
                 "    }\n")
    replace_once(hooks,
                 "    public static void registerPeerReceiver(Object receiver, long sid) {\n"
                 "        registerTracker(receiver, sid);\n"
                 "    }\n",
                 "    public static void registerPeerReceiver(Object receiver, long sid) {\n"
                 "        registerTracker(receiver, sid);\n"
                 "    }\n\n"
                 "    private static Integer lifecycleEpoch(QuorumPeer peer) {\n"
                 "        synchronized (PEER_EPOCHS) { return PEER_EPOCHS.get(peer); }\n"
                 "    }\n\n"
                 "    /** Bind from the exact QuorumPeer run, even if another peer has the same sid. */\n"
                 "    public static void nodePeer(QuorumPeer peer) {\n"
                 "        if (peer == null) return;\n"
                 "        Integer epoch = lifecycleEpoch(peer);\n"
                 "        if (epoch != null) call(\"setNode\",\n"
                 "            new Class<?>[] {String.class, int.class}, \"zk\" + peer.getMyId(), epoch);\n"
                 "    }\n\n"
                 "    public static void registerPeerReceiver(Object receiver, QuorumPeer peer) {\n"
                 "        if (receiver == null || peer == null) return;\n"
                 "        Integer epoch = lifecycleEpoch(peer);\n"
                 "        if (epoch != null) call(\"registerNode\",\n"
                 "            new Class<?>[] {Object.class, String.class, int.class},\n"
                 "            receiver, \"zk\" + peer.getMyId(), epoch);\n"
                 "    }\n\n"
                 "    /** Enter one concrete FOLLOWING attempt before its follower is constructed. */\n"
                 "    public static Scope followingScope(QuorumPeer peer) {\n"
                 "        if (peer == null || Thread.currentThread() != peer)\n"
                 '            throw new IllegalStateException("FOLLOWING hook must run on its exact QuorumPeer thread");\n'
                 "        long sid = peer.getMyId();\n"
                 "        Integer epoch = lifecycleEpoch(peer);\n"
                 '        if (epoch == null) throw new IllegalStateException("QuorumPeer lifecycle epoch is not registered");\n'
                 "        nodePeer(peer);\n"
                 "        FollowingRetry retry;\n"
                 "        synchronized (FOLLOWING_RETRIES) { retry = FOLLOWING_RETRIES.remove(peer); }\n"
                 "        call(\"regionEnter\", new Class<?>[] {String.class}, FOLLOWING_REGION);\n"
                 "        try {\n"
                 "            if (retry != null && retry.peer == peer && retry.thread == Thread.currentThread()\n"
                 "                && retry.sid == sid && retry.epoch == epoch) {\n"
                 "                call(\"taskObserve\", new Class<?>[] {String.class, String.class},\n"
                 "                     retry.token, FOLLOWING_RETRY_SITE);\n"
                 "            }\n"
                 "            return new Scope(null, FOLLOWING_REGION);\n"
                 "        } catch (RuntimeException | Error failure) {\n"
                 "            call(\"regionExit\", new Class<?>[] {String.class}, FOLLOWING_REGION);\n"
                 "            throw failure;\n"
                 "        }\n"
                 "    }\n\n"
                 "    /** Submit only a caught exception's successor on this exact peer/thread/epoch. */\n"
                 "    public static void followingRetrySubmit(QuorumPeer peer) {\n"
                 "        if (peer == null || Thread.currentThread() != peer) return;\n"
                 "        long sid = peer.getMyId();\n"
                 "        Integer epoch = lifecycleEpoch(peer);\n"
                 "        if (epoch == null) return;\n"
                 "        nodePeer(peer);\n"
                 '        String token = "zk-following-retry:" + sid + ":" + epoch + ":"\n'
                 '            + Thread.currentThread().getId() + ":"\n'
                 '            + Integer.toUnsignedString(System.identityHashCode(peer)) + ":"\n'
                 "            + NEXT_FOLLOWING_RETRY.incrementAndGet();\n"
                 "        synchronized (FOLLOWING_RETRIES) {\n"
                 "            FOLLOWING_RETRIES.put(peer, new FollowingRetry(peer, Thread.currentThread(),\n"
                 "                                                  sid, epoch, token));\n"
                 "        }\n"
                 "        call(\"taskSubmit\", new Class<?>[] {String.class, String.class},\n"
                 "             token, FOLLOWING_RETRY_SITE);\n"
                 "    }\n\n"
                 "    public static void clearFollowingRetry(QuorumPeer peer) {\n"
                 "        synchronized (FOLLOWING_RETRIES) { FOLLOWING_RETRIES.remove(peer); }\n"
                 "        synchronized (PEER_EPOCHS) { PEER_EPOCHS.remove(peer); }\n"
                 "    }\n")

    replace_once(follower,
                 "        this.fzk = Objects.requireNonNull(zk);\n"
                 "        this.zk = zk;\n",
                 "        this.fzk = Objects.requireNonNull(zk);\n"
                 "        this.zk = zk;\n"
                 "        MalloryZkHooks.registerPeerReceiver(this, self);\n")
    replace_once(observer,
                 "        this.self = self;\n"
                 "        this.zk = observerZooKeeperServer;\n",
                 "        this.self = self;\n"
                 "        this.zk = observerZooKeeperServer;\n"
                 "        MalloryZkHooks.registerPeerReceiver(this, self);\n")
    replace_once(follower,
                 "        MalloryZkHooks.node(self.getMyId());\n",
                 "        MalloryZkHooks.nodePeer(self);\n")
    replace_once(observer,
                 "        MalloryZkHooks.node(self.getMyId());\n",
                 "        MalloryZkHooks.nodePeer(self);\n")
    replace_once(peer,
                 "                case FOLLOWING:\n"
                 "                    try {\n"
                 '                        LOG.info("FOLLOWING");\n'
                 "                        setFollower(makeFollower(logFactory));\n"
                 "                        follower.followLeader();\n"
                 "                    } catch (Exception e) {\n"
                 '                        LOG.warn("Unexpected exception", e);\n'
                 "                    } finally {\n"
                 "                        follower.shutdown();\n"
                 "                        setFollower(null);\n"
                 "                        updateServerState();\n"
                 "                    }\n"
                 "                    break;\n",
                 "                case FOLLOWING:\n"
                 "                    try (MalloryZkHooks.Scope malloryFollowing = MalloryZkHooks.followingScope(this)) {\n"
                 "                        try {\n"
                 '                            LOG.info("FOLLOWING");\n'
                 "                            setFollower(makeFollower(logFactory));\n"
                 "                            follower.followLeader();\n"
                 "                        } catch (Exception e) {\n"
                 "                            MalloryZkHooks.followingRetrySubmit(this);\n"
                 '                            LOG.warn("Unexpected exception", e);\n'
                 "                        } finally {\n"
                 "                            follower.shutdown();\n"
                 "                            setFollower(null);\n"
                 "                            updateServerState();\n"
                 "                        }\n"
                 "                    }\n"
                 "                    break;\n")
    replace_once(peer,
                 "        } finally {\n"
                 '            LOG.warn("QuorumPeer main thread exited");\n',
                 "        } finally {\n"
                 "            MalloryZkHooks.clearFollowingRetry(this);\n"
                 '            LOG.warn("QuorumPeer main thread exited");\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    install(args.source_root.resolve())
