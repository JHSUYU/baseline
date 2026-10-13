package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.mallory.nativebinding.NativeZooKeeperActorBridge;

/** Checks actor attribution under an inherited JUnit client request. */
public final class NativeZooKeeperActorBridgeSmoke {
    public static final class Peer {
        private final long id;
        public Peer(long id) { this.id = id; }
        public long getMyId() { return id; }
    }

    public static final class Learner {
        Object self;
        Learner(Object self) { this.self = self; }
    }

    private NativeZooKeeperActorBridgeSmoke() { }

    public static void main(String[] args) {
        String opened = ConcolicRegionRuntime.openWorkloadSession();
        if (!opened.isEmpty()) throw new AssertionError(opened);
        Object driver = new Object();
        RuntimeTraceContext.registerSource(driver,
                new SourceRef("SYSTEM", "CLIENT", "native-junit", 0));
        RecordingWindow.open();
        long request = RuntimeTraceContext.beginRequest(driver, "originalJUnit");
        try {
            Peer first = new Peer(7);
            Learner learner = new Learner(first);
            NativeZooKeeperActorBridge.peerStartEntered(first);
            check(first, "zk-peer-7#epoch0");
            NativeZooKeeperActorBridge.peerStartExited();
            NativeZooKeeperActorBridge.peerRunEntered(first);
            NativeZooKeeperActorBridge.learnerEntered(learner);
            check(learner, "zk-peer-7#epoch0");
            if (!Identity.contextHere().render().contains("PEER_RUN")) {
                throw new AssertionError("actor root turn was not opened");
            }
            NativeZooKeeperActorBridge.peerRunExited();
            Peer replacement = new Peer(7);
            NativeZooKeeperActorBridge.peerRunEntered(replacement);
            check(replacement, "zk-peer-7#epoch1");
            NativeZooKeeperActorBridge.peerRunExited();
        } finally {
            RuntimeTraceContext.endRequest(request);
            RecordingWindow.close();
            String closed = ConcolicRegionRuntime.closeWorkloadSession();
            if (!closed.isEmpty()) throw new AssertionError(closed);
            RowRuntime.closeSession();
        }
        System.out.println("NATIVE_ZK_ACTOR_BRIDGE_SMOKE_OK");
    }

    private static void check(Object receiver, String expected) {
        String actual = RuntimeTraceContext.activationSource(receiver).key();
        if (!expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}
