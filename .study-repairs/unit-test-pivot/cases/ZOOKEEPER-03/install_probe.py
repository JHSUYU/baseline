#!/usr/bin/env python3
"""Install an exact setOwner target probe in a case-local ZooKeeper copy."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path("/users/ZhenyuLi/zk03-unit")
SOURCE = ROOT / "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
CLASSES = Path("/users/ZhenyuLi/zk03-target-classes")
EMPTY_SOURCEPATH = Path("/users/ZhenyuLi/zk03-case/empty-sourcepath")
RECORDER = Path("/users/ZhenyuLi/zk03-runtime.jar")
REPORT = (ROOT / "zookeeper-server/target/surefire-reports/"
          "TEST-org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest.xml")

ORIGINAL = """    public synchronized void setOwner(long id, Object owner) throws SessionExpiredException {
        SessionImpl session = sessionsById.get(id);
        if (session == null || session.isClosing()) {
            throw new KeeperException.SessionExpiredException();
        }
        session.owner = owner;
    }
"""

PROBED = """    public synchronized void setOwner(long id, Object owner) throws SessionExpiredException {
        final String method = "<org.apache.zookeeper.server.SessionTrackerImpl: void setOwner(long,java.lang.Object)>";
        long callId = edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.enterMethod(method, this, "");
        SessionImpl session = sessionsById.get(id);
        boolean missing = session == null;
        edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.recordBranch(
                callId, method, 11, "session == null", missing);
        boolean fatal = missing || session.isClosing();
        edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.recordBranch(
                callId, method, 12, "session == null || session.isClosing()", fatal);
        if (fatal) {
            KeeperException.SessionExpiredException error = new KeeperException.SessionExpiredException();
            edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.recordExplicitThrow(
                    callId, method, 13, error);
            edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.throwActiveMethod(error);
            throw error;
        }
        session.owner = owner;
        edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder.exitActiveMethod(null, "void");
    }
"""


def main() -> None:
    source = SOURCE.read_text()
    if PROBED in source:
        pass
    elif source.count(ORIGINAL) == 1:
        SOURCE.write_text(source.replace(ORIGINAL, PROBED))
    else:
        raise RuntimeError("Expected exact upstream setOwner method not found")
    props = ET.parse(REPORT).getroot().findall("./properties/property")
    cp = next(p.get("value", "") for p in props
              if p.get("name") == "java.class.path")
    cp = cp.replace("/users/ZhenyuLi/zk01-unit/source", str(ROOT))
    CLASSES.mkdir(parents=True, exist_ok=True)
    EMPTY_SOURCEPATH.mkdir(parents=True, exist_ok=True)
    command = ["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac", "-source", "8",
               "-target", "8", "-sourcepath", str(EMPTY_SOURCEPATH), "-cp",
               os.pathsep.join((str(RECORDER), cp)), "-d", str(CLASSES),
               str(SOURCE)]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
