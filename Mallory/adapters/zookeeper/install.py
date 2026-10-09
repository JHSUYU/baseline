#!/usr/bin/env python3
"""Install bounded ZooKeeper 3.8.7 quorum hooks into an isolated source tree.

The script refuses source drift and can be rerun without duplicate hooks.
It never edits the original ZooKeeper checkout or other systems.
"""

import argparse
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
RELATIVE = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum")
SERVER = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server")


def replace_once(source: Path, old: str, new: str) -> None:
    text = source.read_text(encoding="utf-8")
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one unmodified anchor in {source}: {old!r}, got {text.count(old)}")
    source.write_text(text.replace(old, new, 1), encoding="utf-8")


def install(root: Path) -> None:
    src = root / RELATIVE
    if not (src / "QuorumPeer.java").is_file():
        raise RuntimeError(f"Not a ZooKeeper source root: {root}")
    hooks = HERE / "src/org/apache/zookeeper/server/quorum/MalloryZkHooks.java"
    shutil.copyfile(hooks, src / hooks.name)

    replace_once(src / "QuorumPeer.java",
                 "    public void run() {\n        updateThreadName();",
                 "    public void run() {\n        updateThreadName();\n        MalloryZkHooks.startPeer(this);")
    replace_once(src / "Follower.java",
                 "    void followLeader() throws InterruptedException {",
                 "    void followLeader() throws InterruptedException {\n        MalloryZkHooks.node(self.getMyId());")
    replace_once(src / "Learner.java",
                 "public class Learner {",
                 "public class Learner {\n"
                 "    public long malloryServerId() {\n"
                 "        return self == null ? -1 : self.getMyId();\n"
                 "    }")
    replace_once(src / "Leader.java",
                 "    void lead() throws IOException, InterruptedException {",
                 "    void lead() throws IOException, InterruptedException {\n        MalloryZkHooks.node(self.getMyId());")
    replace_once(src / "Leader.java",
                 "public class Leader extends LearnerMaster {",
                 "public class Leader extends LearnerMaster {\n"
                 "    public long malloryServerId() {\n"
                 "        return self == null ? -1 : self.getMyId();\n"
                 "    }")
    replace_once(src / "Observer.java",
                 "    void observeLeader() throws Exception {",
                 "    void observeLeader() throws Exception {\n        MalloryZkHooks.node(self.getMyId());")
    replace_once(src / "ObserverMaster.java",
                 "    public void run() {\n        ServerSocket ss;",
                 "    public void run() {\n        MalloryZkHooks.node(self.getMyId());\n        ServerSocket ss;")
    replace_once(src / "ObserverMaster.java",
                 "public class ObserverMaster extends LearnerMaster implements Runnable {",
                 "public class ObserverMaster extends LearnerMaster implements Runnable {\n"
                 "    public long malloryServerId() {\n"
                 "        return self == null ? -1 : self.getMyId();\n"
                 "    }")

    replace_once(src / "Learner.java",
                 "leaderIs = BinaryInputArchive.getArchive(new BufferedInputStream(sock.getInputStream()));",
                 "leaderIs = MalloryZkHooks.input(new BufferedInputStream(sock.getInputStream()), sock, self.getMyId());")
    replace_once(src / "Learner.java",
                 "leaderOs = BinaryOutputArchive.getArchive(bufferedOutput);",
                 "leaderOs = MalloryZkHooks.output(bufferedOutput, sock, self.getMyId());")
    replace_once(src / "LearnerHandler.java",
                 "ia = BinaryInputArchive.getArchive(bufferedInput);",
                 "ia = MalloryZkHooks.input(bufferedInput, sock, MalloryZkHooks.masterId(learnerMaster));")
    replace_once(src / "LearnerHandler.java",
                 "oa = BinaryOutputArchive.getArchive(bufferedOutput);",
                 "oa = MalloryZkHooks.output(bufferedOutput, sock, MalloryZkHooks.masterId(learnerMaster));")

    # SessionTrackerImpl is shared by many request processors. Bind its own
    # constructor's serverId, not the creating or invoking thread's last peer.
    tracker = root / SERVER / "SessionTrackerImpl.java"
    replace_once(tracker,
                 "    private final SessionExpirer expirer;",
                 "    private final SessionExpirer expirer;\n    private final long malloryServerId;")
    replace_once(tracker,
                 "        this.expirer = expirer;",
                 "        this.expirer = expirer;\n        this.malloryServerId = serverId;")
    replace_once(tracker,
                 "    public synchronized void checkSession(long sessionId, Object owner) throws KeeperException.SessionExpiredException, KeeperException.SessionMovedException, KeeperException.UnknownSessionException {",
                 "    public synchronized void checkSession(long sessionId, Object owner) throws KeeperException.SessionExpiredException, KeeperException.SessionMovedException, KeeperException.UnknownSessionException {\n        org.apache.zookeeper.server.quorum.MalloryZkHooks.node(malloryServerId);")
    replace_once(tracker,
                 "    public synchronized void setOwner(long id, Object owner) throws SessionExpiredException {",
                 "    public synchronized void setOwner(long id, Object owner) throws SessionExpiredException {\n        org.apache.zookeeper.server.quorum.MalloryZkHooks.node(malloryServerId);")

    prep = root / SERVER / "PrepRequestProcessor.java"
    replace_once(prep,
                 "                pRequest(request);",
                 "                try (org.apache.zookeeper.server.quorum.MalloryZkHooks.Scope malloryScope = "
                 "org.apache.zookeeper.server.quorum.MalloryZkHooks.claim(request, zks.getServerId(), "
                 "\"PrepRequestProcessor#take\")) {\n"
                 "                    pRequest(request);\n"
                 "                }")
    replace_once(prep,
                 "        submittedRequests.add(request);",
                 "        org.apache.zookeeper.server.quorum.MalloryZkHooks.submit(request, zks.getServerId(), "
                 "\"PrepRequestProcessor#add\");\n"
                 "        submittedRequests.add(request);")

    throttler = root / SERVER / "RequestThrottler.java"
    replace_once(throttler,
                 "            submittedRequests.add(request);",
                 "            org.apache.zookeeper.server.quorum.MalloryZkHooks.submit(request, zks.getServerId(), "
                 "\"RequestThrottler#add\");\n"
                 "            submittedRequests.add(request);")
    replace_once(throttler,
                 "                    zks.submitRequestNow(request);",
                 "                    try (org.apache.zookeeper.server.quorum.MalloryZkHooks.Scope malloryScope = "
                 "org.apache.zookeeper.server.quorum.MalloryZkHooks.claim(request, zks.getServerId(), "
                 "\"RequestThrottler#take\")) {\n"
                 "                        zks.submitRequestNow(request);\n"
                 "                    }")

    # ZooKeeper overrides Surefire argLine to load JMockit. -DargLine is ignored.
    # Keep the existing agent and add an opt-in Mallory option, empty by default.
    pom = root / "zookeeper-server/pom.xml"
    replace_once(pom,
                 "  <artifactId>zookeeper</artifactId>\n  <packaging>jar</packaging>",
                 "  <artifactId>zookeeper</artifactId>\n"
                 "  <properties><mallory.agent.arg></mallory.agent.arg></properties>\n"
                 "  <packaging>jar</packaging>")
    replace_once(pom,
                 "-javaagent:${org.jmockit:jmockit:jar}</argLine>",
                 "-javaagent:${org.jmockit:jmockit:jar} ${mallory.agent.arg}</argLine>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    arguments = parser.parse_args()
    install(arguments.source_root.resolve())
