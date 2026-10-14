package edu.uva.liftlab.graphchecker.causynth;

import java.util.Arrays;
import java.util.Iterator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import soot.Body;
import soot.BooleanType;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Unit;
import soot.Value;
import soot.VoidType;
import soot.jimple.AssignStmt;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.IdentityStmt;
import soot.jimple.InvokeExpr;
import soot.jimple.Jimple;
import soot.jimple.ReturnStmt;
import soot.jimple.ReturnVoidStmt;
import soot.jimple.Stmt;

/** Exact ZooKeeper transport anchors for a source-built GraphChecker session. */
public final class NativeZooKeeperProtocolWeave {
    private static final Logger LOG = LoggerFactory.getLogger(
            NativeZooKeeperProtocolWeave.class);
    private static final String CLIENT =
            "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperClientTraceBridge";
    private static final String PROPOSAL =
            "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperProposalTraceBridge";
    private static final String HANDSHAKE =
            "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperHandshakeTraceBridge";
    private static final String QUORUM = "org.apache.zookeeper.server.quorum.";

    private NativeZooKeeperProtocolWeave() { }

    public static void apply(boolean clientEnabled, boolean proposalEnabled) {
        int client = clientEnabled ? clientHooks() : 0;
        int proposal = proposalEnabled ? proposalHooks() + handshakeHooks() : 0;
        if ((clientEnabled && client != 8)
                || (proposalEnabled && proposal != 14)) {
            throw new IllegalStateException("ZooKeeper native protocol hooks "
                    + "missing: client=" + client + ", proposal=" + proposal);
        }
        LOG.info("ZooKeeper native protocol hooks woven: client={}, quorum={}",
                clientEnabled, proposalEnabled);
    }

    private static int clientHooks() {
        SootClass client = required("org.apache.zookeeper.ClientCnxnSocketNIO");
        SootClass server = required("org.apache.zookeeper.server.NIOServerCnxn");
        int prepared = afterInstanceCall(client, "doIO", "createBB",
                hook(CLIENT, "clientPrepared", 2), true)
                + afterInstanceCall(client, "sendPacket", "createBB",
                hook(CLIENT, "clientPrepared", 2), true);
        int sent = afterInstanceCall(client, "doIO", "removeFirstOccurrence",
                hook(CLIENT, "clientSent", 2), false)
                + afterSocketWrite(client, "sendPacket",
                hook(CLIENT, "clientSent", 2));
        int received = beforeDispatch(server, "readConnectRequest",
                "processConnectRequest", hook(CLIENT, "serverRead", 2))
                + beforeDispatch(server, "readRequest", "processPacket",
                hook(CLIENT, "serverRead", 2));
        int exits = beforeReturns(server, "readConnectRequest",
                hook(CLIENT, "serverReadExited", 0))
                + beforeReturns(server, "readRequest",
                hook(CLIENT, "serverReadExited", 0));
        if (prepared != 2 || sent != 2 || received != 2 || exits != 2) {
            throw new IllegalStateException("native client anchors "
                    + prepared + "/" + sent + "/" + received + "/"
                    + exits);
        }
        return 8;
    }

    private static int proposalHooks() {
        SootClass handler = required(QUORUM + "LearnerHandler");
        SootClass learner = required(QUORUM + "Learner");
        SootClass follower = required(QUORUM + "Follower");
        SootClass observer = required(QUORUM + "ObserverMaster");
        int writes = afterCall(handler, "sendPackets", 368, "writeRecord",
                hook(PROPOSAL, "buffered", 2));
        int flushes = afterNoArgCall(handler, "sendPackets", "flush",
                hook(PROPOSAL, "flushed", 1));
        int reads = afterCall(learner, "readPacket", 228, "readRecord",
                hook(PROPOSAL, "learnerRead", 2));
        int exits = beforeReturns(follower, "processPacket",
                hook(PROPOSAL, "followerPacketProcessed", 0));
        int queued = afterCall(observer, "proposalReceived", 356, "add",
                hook(PROPOSAL, "proposalQueued", 2));
        int peeked = afterObserverPeek(observer,
                hook(PROPOSAL, "proposalPeeked", 2));
        int removed = afterObserverRemove(observer,
                hook(PROPOSAL, "proposalRemoved", 1));
        if (writes != 1 || flushes != 1 || reads != 1 || exits == 0
                || queued != 1 || peeked != 1 || removed != 1) {
            throw new IllegalStateException("native proposal anchors "
                    + writes + "/" + flushes + "/" + reads + "/"
                    + exits + "/" + queued + "/" + peeked + "/" + removed);
        }
        return 8;
    }

    /** FOLLOWERINFO and LEADERINFO are the two statically declared wire ports. */
    private static int handshakeHooks() {
        SootClass handler = required(QUORUM + "LearnerHandler");
        SootClass learner = required(QUORUM + "Learner");
        SootMethodRef followerPrepare = packetHook("followerPrepared");
        SootMethodRef followerSent = packetHook("followerFlushed");
        int followerEntries = packetMethodEntry(learner, "writePacketNow",
                followerPrepare);
        int followerWrites = beforeSuccessfulPacketReturns(learner,
                "writePacketNow", followerSent);
        int followerReads = afterCall(handler, "run", 472, "readRecord",
                hook(HANDSHAKE, "leaderReadFollower", 2));
        int leaderPrepare = beforeCall(handler, "run", 537, "writeRecord",
                hook(HANDSHAKE, "leaderPrepared", 2));
        int leaderWrites = afterFlushFollowingWrite(handler, "run", 537,
                539, hook(HANDSHAKE, "leaderFlushed", 2));
        int leaderReads = afterCall(learner, "readPacket", 228, "readRecord",
                hook(HANDSHAKE, "learnerReadLeader", 2));
        if (followerEntries != 1 || followerWrites != 1
                || followerReads != 1 || leaderPrepare != 1
                || leaderWrites != 1 || leaderReads != 1) {
            throw new IllegalStateException("native quorum handshake anchors "
                    + followerEntries + "/" + followerWrites + "/"
                    + followerReads + "/" + leaderPrepare + "/"
                    + leaderWrites + "/" + leaderReads);
        }
        return 6;
    }

    private static SootMethodRef packetHook(String name) {
        SootClass type = Scene.v().loadClassAndSupport(HANDSHAKE);
        return Scene.v().makeMethodRef(type, name,
                Arrays.asList(RefType.v("java.lang.Object"),
                        RefType.v("java.lang.Object"), BooleanType.v()),
                VoidType.v(), true);
    }

    private static SootClass required(String name) {
        SootClass type = Scene.v().getSootClassUnsafe(name);
        if (type == null || !type.isApplicationClass()) {
            throw new IllegalStateException("source class not materialized: " + name);
        }
        return type;
    }

    private static SootMethodRef hook(String owner, String name, int count) {
        SootClass type = Scene.v().loadClassAndSupport(owner);
        soot.Type[] args = new soot.Type[count];
        Arrays.fill(args, RefType.v("java.lang.Object"));
        return Scene.v().makeMethodRef(type, name, Arrays.asList(args),
                VoidType.v(), true);
    }

    private static int afterInstanceCall(SootClass type, String methodName,
                                         String calledName, SootMethodRef hook,
                                         boolean useBase) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                if (!calledName.equals(call.getMethodRef().name())
                        || !(call instanceof InstanceInvokeExpr)) continue;
                Value packet = useBase ? ((InstanceInvokeExpr) call).getBase()
                        : call.getArg(0);
                body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), packet)), unit);
                found++;
            }
        }
        return found;
    }

    private static int afterSocketWrite(SootClass type, String methodName,
                                        SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName())
                    || method.getParameterCount() != 1 || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr() || !"write".equals(
                        stmt.getInvokeExpr().getMethodRef().name())) continue;
                body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), body.getParameterLocal(0))), unit);
                found++;
            }
        }
        return found;
    }

    private static int beforeDispatch(SootClass type, String methodName,
                                      String calledName, SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                if (!calledName.equals(call.getMethodRef().name())
                        || call.getArgCount() != 2) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), call.getArg(1))), unit);
                found++;
            }
        }
        return found;
    }

    private static int beforeReturns(SootClass type, String methodName,
                                     SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof ReturnStmt) && !(unit instanceof ReturnVoidStmt)) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook)), unit);
                found++;
            }
        }
        return found;
    }

    private static int afterCall(SootClass type, String methodName,
                                 int sourceLine, String calledName,
                                 SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)
                        || unit.getJavaSourceStartLineNumber() != sourceLine) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                if (!calledName.equals(call.getMethodRef().name())
                        || call.getArgCount() == 0) continue;
                body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), call.getArg(0))), unit);
                found++;
            }
        }
        return found;
    }

    private static int beforeCall(SootClass type, String methodName,
                                  int sourceLine, String calledName,
                                  SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)
                        || unit.getJavaSourceStartLineNumber() != sourceLine) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                if (!calledName.equals(call.getMethodRef().name())
                        || call.getArgCount() == 0) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), call.getArg(0))), unit);
                found++;
            }
        }
        return found;
    }

    private static int afterFlushFollowingWrite(SootClass type,
                                                 String methodName,
                                                 int writeLine, int flushLine,
                                                 SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Value packet = null;
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                if (unit.getJavaSourceStartLineNumber() == writeLine
                        && "writeRecord".equals(call.getMethodRef().name())
                        && call.getArgCount() > 0) {
                    if (packet != null) throw new IllegalStateException(
                            "ambiguous LEADERINFO write");
                    packet = call.getArg(0);
                } else if (unit.getJavaSourceStartLineNumber() == flushLine
                        && "flush".equals(call.getMethodRef().name())) {
                    if (packet == null) throw new IllegalStateException(
                            "LEADERINFO flush has no preceding write");
                    body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                            Jimple.v().newStaticInvokeExpr(hook,
                                    body.getThisLocal(), packet)), unit);
                    packet = null;
                    found++;
                }
            }
        }
        return found;
    }

    private static int packetMethodEntry(SootClass type, String methodName,
                                         SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || method.getParameterCount() != 2
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Unit unit : body.getUnits()) {
                if (unit instanceof IdentityStmt) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook, body.getThisLocal(),
                                body.getParameterLocal(0), body.getParameterLocal(1))), unit);
                found++;
                break;
            }
        }
        return found;
    }

    private static int beforeSuccessfulPacketReturns(SootClass type,
                                                      String methodName,
                                                      SootMethodRef hook) {
        int methods = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || method.getParameterCount() != 2
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            int returns = 0;
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof ReturnVoidStmt)) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook, body.getThisLocal(),
                                body.getParameterLocal(0), body.getParameterLocal(1))), unit);
                returns++;
            }
            if (returns > 0) methods++;
        }
        return methods;
    }

    private static int afterNoArgCall(SootClass type, String methodName,
                                      String calledName, SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!methodName.equals(method.getName()) || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr() || !calledName.equals(
                        stmt.getInvokeExpr().getMethodRef().name())) continue;
                body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal())), unit);
                found++;
            }
        }
        return found;
    }

    private static int afterObserverPeek(SootClass type, SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!"removeProposedPacket".equals(method.getName())
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof AssignStmt)) continue;
                AssignStmt stmt = (AssignStmt) unit;
                if (!stmt.containsInvokeExpr() || !"peek".equals(
                        stmt.getInvokeExpr().getMethodRef().name())) continue;
                body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), stmt.getLeftOp())), unit);
                found++;
            }
        }
        return found;
    }

    private static int afterObserverRemove(SootClass type, SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!"removeProposedPacket".equals(method.getName())
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Value peeked = null;
            for (Iterator<Unit> it = body.getUnits().snapshotIterator(); it.hasNext();) {
                Unit unit = it.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                String called = stmt.getInvokeExpr().getMethodRef().name();
                if ("peek".equals(called) && stmt instanceof AssignStmt) {
                    peeked = ((AssignStmt) stmt).getLeftOp();
                } else if ("remove".equals(called) && peeked != null) {
                    body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                            Jimple.v().newStaticInvokeExpr(hook, peeked)), unit);
                    found++;
                }
            }
        }
        return found;
    }
}
