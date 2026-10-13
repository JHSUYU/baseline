package edu.uva.liftlab.mallory.graphchecker.causynth;

import soot.Body;
import soot.ArrayType;
import soot.BooleanType;
import soot.LongType;
import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Unit;
import soot.Value;
import soot.VoidType;
import soot.Type;
import soot.jimple.IdentityStmt;
import soot.jimple.InvokeExpr;
import soot.jimple.Jimple;
import soot.jimple.ReturnStmt;
import soot.jimple.ReturnVoidStmt;
import soot.jimple.Stmt;
import soot.jimple.StringConstant;

import java.util.Arrays;
import java.util.ArrayList;
import java.util.Iterator;

/** The quorum metadata hooks in ZooKeeper's production classes. */
public final class ZooKeeperWeave {
    private static final String PREFIX = "org.apache.zookeeper.server.quorum.";
    private static final String BRIDGE =
            "edu.uva.liftlab.mallory.graphchecker.runtime.ZooKeeperTraceBridge";
    private static final String FILE_BRIDGE =
            "edu.uva.liftlab.mallory.graphchecker.runtime.PersistentFileTraceBridge";

    private ZooKeeperWeave() {
    }

    /** The exact THROW method read from a generated static target manifest. */
    public static final class TargetMethod {
        public final String clazz;
        public final String method;
        public final String descriptor;

        public TargetMethod(String clazz, String method, String descriptor) {
            this.clazz = clazz;
            this.method = method;
            this.descriptor = descriptor;
        }

        boolean is(String owner, String name) {
            return (PREFIX + owner).equals(clazz) && name.equals(method);
        }
    }

    public static void apply() {
        SootClass peer = application(PREFIX + "QuorumPeer");
        if (peer == null) return;
        SootMethodRef peerRunEntered = bridge("peerRunEntered", 1);
        SootMethodRef peerRunExited = bridge("peerRunExited", 0);
        SootMethodRef registerActor = bridge("registerActor", 2);
        SootMethodRef prepareLeader = bridge("leaderInfoPrepared", 2);
        SootMethodRef sent = bridge("leaderInfoFlushed", 2);
        SootMethodRef received = bridge("learnerPacketRead", 2);
        SootMethodRef ackSent = Scene.v().makeMethodRef(
                Scene.v().loadClassAndSupport(BRIDGE), "learnerAckFlushed",
                Arrays.asList(RefType.v("java.lang.Object"),
                        RefType.v("java.lang.Object"), BooleanType.v()),
                VoidType.v(), true);
        SootMethodRef prepareAck = Scene.v().makeMethodRef(
                Scene.v().loadClassAndSupport(BRIDGE), "learnerAckPrepared",
                Arrays.asList(RefType.v("java.lang.Object"),
                        RefType.v("java.lang.Object"), BooleanType.v()),
                VoidType.v(), true);
        SootMethodRef ackReceived = bridge("leaderAckRead", 2);

        int peerEntries = entry(peer, "run", 0, peerRunEntered, false);
        int peerExits = beforeReturns(peer, "run", peerRunExited);
        int peerFailures = afterUncaught(peer, "run", 0, peerRunExited);
        int followers = entry(peer, "setFollower", 1, registerActor, true);
        int leaders = entry(peer, "setLeader", 1, registerActor, true);
        int leaderPrepared = beforeCall(application(PREFIX + "LearnerHandler"),
                "run", 537, "writeRecord", prepareLeader);
        int writes = afterFlushFollowingWrite(
                application(PREFIX + "LearnerHandler"), "run", 537, 539,
                sent);
        int reads = afterCall(application(PREFIX + "Learner"),
                "readPacket", 228, "readRecord", received);
        int ackPrepared = packetMethodEntry(
                application(PREFIX + "Learner"), "writePacketNow",
                prepareAck);
        int ackWrites = beforeSuccessfulPacketReturns(
                application(PREFIX + "Learner"), "writePacketNow", ackSent);
        int ackReads = afterCall(application(PREFIX + "LearnerHandler"),
                "run", 541, "readRecord", ackReceived);
        SootClass fileBridgeType = Scene.v().loadClassAndSupport(FILE_BRIDGE);
        SootMethodRef epochReadHook = Scene.v().makeMethodRef(fileBridgeType,
                "zooKeeperEpochRead", Arrays.asList(
                        RefType.v("java.lang.Object"),
                        RefType.v("java.lang.Object"), LongType.v()),
                VoidType.v(), true);
        SootMethodRef epochWriteHook = Scene.v().makeMethodRef(fileBridgeType,
                "zooKeeperEpochWrite", Arrays.asList(
                        RefType.v("java.lang.Object"),
                        RefType.v("java.lang.Object"), LongType.v()),
                VoidType.v(), true);
        int epochReads = beforeSuccessfulEpochReturns(peer,
                "readLongFromFile", false, epochReadHook);
        int epochWrites = beforeSuccessfulEpochReturns(peer,
                "writeLongToFile", true, epochWriteHook);
        int directWrites = afterSuccessfulFileUtilsWrites();
        if (peerEntries != 1 || peerExits == 0 || peerFailures != 1
                || followers != 1 || leaders != 1
                || leaderPrepared != 1 || writes != 1 || reads != 1
                || ackPrepared != 1 || ackWrites != 1 || ackReads != 1
                || epochReads != 1 || epochWrites != 1) {
            throw new IllegalStateException("ZOOKEEPER_BRIDGE_SITE_MISSING: "
                    + "QuorumPeer.run=" + peerEntries
                    + ", run exits=" + peerExits
                    + ", setFollower=" + followers
                    + ", setLeader=" + leaders
                    + ", LearnerHandler.LEADERINFO.prepare/flush="
                    + leaderPrepared + "/" + writes
                    + ", Learner.readPacket.readRecord=" + reads
                    + ", Learner.writePacketNow prepare/return="
                    + ackPrepared + "/" + ackWrites
                    + ", LearnerHandler.ACKEPOCH.readRecord=" + ackReads
                    + ", epoch file reads/writes=" + epochReads + "/"
                    + epochWrites);
        }
        // A missing direct FileUtils call is legal for workloads that never
        // use that helper; the epoch method hooks above are mandatory.
    }

    /**
     * Protocol turns are system-wide.  A selected target outside these turns
     * gets another scope from its generated manifest.  This post-pass leaves
     * the generic weaver's original unit indices and site IDs unchanged.
     */
    public static void applyRuntimeTargetScope(TargetMethod target) {
        SootClass peer = application(PREFIX + "QuorumPeer");
        SootClass follower = application(PREFIX + "Follower");
        SootClass learner = application(PREFIX + "Learner");
        SootClass handler = application(PREFIX + "LearnerHandler");
        if (peer == null || follower == null || learner == null
                || handler == null) return;
        int peerStartEntries = entry(peer, "start", 0,
                bridge("peerStartEntered", 1), false);
        int peerStartExits = beforeReturns(peer, "start",
                bridge("peerStartExited", 0));
        int followerEntries = entry(follower, "followLeader", 0,
                bridge("followerEntered", 1), false);
        int followerExits = beforeReturns(follower, "followLeader",
                bridge("followerExited", 0));
        int registrationEntries = entry(learner, "registerWithLeader", 1,
                bridge("targetEntered", 1), false);
        int registrationExits = beforeReturns(learner, "registerWithLeader",
                bridge("targetExited", 0));
        int handlerEntries = entry(handler, "run", 0,
                bridge("handlerEntered", 1), false);
        int handlerExits = beforeReturns(handler, "run",
                bridge("handlerExited", 0));
        int peerStartFailures = afterUncaught(peer, "start", 0,
                bridge("peerStartExited", 0));
        int followerFailures = afterUncaught(follower, "followLeader", 0,
                bridge("followerExited", 0));
        int registrationFailures = afterUncaught(learner, "registerWithLeader", 1,
                bridge("targetExited", 0));
        int handlerFailures = afterUncaught(handler, "run", 0,
                bridge("handlerExited", 0));
        if (peerStartEntries != 1 || peerStartExits == 0
                || followerEntries != 1 || followerExits == 0
                || registrationEntries != 1 || registrationExits == 0
                || handlerEntries != 1 || handlerExits == 0
                || peerStartFailures != 1 || followerFailures != 1
                || registrationFailures != 1 || handlerFailures != 1) {
            throw new IllegalStateException("ZOOKEEPER_TARGET_SCOPE_MISSING: "
                    + "peer start=" + peerStartEntries + "/" + peerStartExits
                    + ", follower=" + followerEntries + "/" + followerExits
                    + ", registration=" + registrationEntries + "/"
                    + registrationExits
                    + ", learner handler=" + handlerEntries + "/"
                    + handlerExits);
        }
        if (target == null) return;
        SootClass owner = application(target.clazz);
        SootMethod selected = exactMethod(owner, target);
        if (target.is("Follower", "followLeader")
                || target.is("Learner", "registerWithLeader")) return;
        if (!target.is("Leader", "waitForEpochAck")
                && !target.is("QuorumPeer", "loadDataBase")) {
            throw new IllegalArgumentException("ZooKeeper target source binding "
                    + "has no verified peer scope: " + target.clazz + "#"
                    + target.method + target.descriptor);
        }
        String scope = scopeName(target.method);
        int selectedEntries = selectedTargetEntry(selected, scope);
        int selectedExits = beforeReturns(selected,
                bridge("selectedTargetExited", 0));
        int selectedFailures = afterUncaught(selected,
                bridge("selectedTargetExited", 0));
        if (selectedEntries != 1 || selectedExits == 0
                || selectedFailures != 1) {
            throw new IllegalStateException("ZOOKEEPER_SELECTED_TARGET_SCOPE_MISSING: "
                    + target.clazz + "#" + target.method + target.descriptor
                    + " entry/return/failure=" + selectedEntries + "/"
                    + selectedExits + "/" + selectedFailures);
        }
    }

    private static String scopeName(String method) {
        return method.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toUpperCase(
                java.util.Locale.ROOT);
    }

    private static SootMethod exactMethod(SootClass owner, TargetMethod target) {
        if (owner == null) throw new IllegalArgumentException("missing target class " + target.clazz);
        SootMethod selected = null;
        for (SootMethod method : owner.getMethods()) {
            if (!method.isConcrete() || !method.getName().equals(target.method)
                    || !descriptor(method).equals(target.descriptor)) continue;
            if (selected != null) throw new IllegalArgumentException("ambiguous target method");
            selected = method;
        }
        if (selected == null) throw new IllegalArgumentException("missing exact target method "
                + target.clazz + "#" + target.method + target.descriptor);
        return selected;
    }

    private static String descriptor(SootMethod method) {
        StringBuilder result = new StringBuilder("(");
        for (Type type : method.getParameterTypes()) result.append(typeDescriptor(type));
        return result.append(')').append(typeDescriptor(method.getReturnType())).toString();
    }

    private static String typeDescriptor(Type type) {
        if (type instanceof ArrayType) {
            ArrayType array = (ArrayType) type;
            StringBuilder result = new StringBuilder();
            for (int i = 0; i < array.numDimensions; i++) result.append('[');
            return result.append(typeDescriptor(array.baseType)).toString();
        }
        if (type instanceof RefType) return "L" + ((RefType) type).getClassName()
                .replace('.', '/') + ";";
        if (type instanceof VoidType) return "V";
        switch (type.toString()) {
            case "boolean": return "Z";
            case "byte": return "B";
            case "char": return "C";
            case "short": return "S";
            case "int": return "I";
            case "long": return "J";
            case "float": return "F";
            case "double": return "D";
            default: throw new IllegalArgumentException("unsupported type " + type);
        }
    }

    private static int selectedTargetEntry(SootMethod method, String scope) {
        Body body = method.retrieveActiveBody();
        Unit first = null;
        for (Unit unit : body.getUnits()) {
            if (!(unit instanceof IdentityStmt)) { first = unit; break; }
        }
        if (first == null) return 0;
        SootMethodRef hook = Scene.v().makeMethodRef(
                Scene.v().loadClassAndSupport(BRIDGE), "selectedTargetEntered",
                Arrays.asList(RefType.v("java.lang.Object"), RefType.v("java.lang.String")),
                VoidType.v(), true);
        body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                Jimple.v().newStaticInvokeExpr(hook, body.getThisLocal(),
                        StringConstant.v(scope))), first);
        return 1;
    }

    private static int beforeReturns(SootMethod method, SootMethodRef hook) {
        int found = 0;
        Body body = method.retrieveActiveBody();
        for (Iterator<Unit> units = body.getUnits().snapshotIterator(); units.hasNext();) {
            Unit unit = units.next();
            if (!(unit instanceof ReturnStmt) && !(unit instanceof ReturnVoidStmt)) continue;
            body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                    Jimple.v().newStaticInvokeExpr(hook)), unit);
            found++;
        }
        return found;
    }

    private static int afterUncaught(SootMethod method, SootMethodRef hook) {
        Body body = method.retrieveActiveBody();
        Unit start = null;
        for (Unit unit : body.getUnits()) {
            if (!(unit instanceof IdentityStmt)) { start = unit; break; }
        }
        if (start == null) return 0;
        Local thrown = Jimple.v().newLocal("$malloryZooKeeperSelectedThrown",
                RefType.v("java.lang.Throwable"));
        body.getLocals().add(thrown);
        Unit handler = Jimple.v().newIdentityStmt(thrown,
                Jimple.v().newCaughtExceptionRef());
        body.getUnits().add(handler);
        body.getUnits().add(Jimple.v().newInvokeStmt(
                Jimple.v().newStaticInvokeExpr(hook)));
        body.getUnits().add(Jimple.v().newThrowStmt(thrown));
        body.getTraps().add(Jimple.v().newTrap(
                Scene.v().getSootClass("java.lang.Throwable"), start, handler, handler));
        body.validate();
        return 1;
    }

    private static int beforeReturns(SootClass type, String methodName,
                                     SootMethodRef hook) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Iterator<Unit> units = body.getUnits().snapshotIterator();
            while (units.hasNext()) {
                Unit unit = units.next();
                if (!(unit instanceof ReturnStmt)
                        && !(unit instanceof ReturnVoidStmt)) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook)), unit);
                found++;
            }
        }
        return found;
    }

    /** Close actor attribution after an exception escapes the whole method. */
    private static int afterUncaught(SootClass type, String methodName,
                                     int parameters, SootMethodRef hook) {
        if (type == null) return 0;
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || method.getParameterCount() != parameters
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Unit start = null;
            for (Unit unit : body.getUnits()) {
                if (!(unit instanceof IdentityStmt)) {
                    start = unit;
                    break;
                }
            }
            if (start == null) continue;
            Local thrown = Jimple.v().newLocal("$malloryZooKeeperThrown",
                    RefType.v("java.lang.Throwable"));
            body.getLocals().add(thrown);
            Unit handler = Jimple.v().newIdentityStmt(thrown,
                    Jimple.v().newCaughtExceptionRef());
            body.getUnits().add(handler);
            body.getUnits().add(Jimple.v().newInvokeStmt(
                    Jimple.v().newStaticInvokeExpr(hook)));
            body.getUnits().add(Jimple.v().newThrowStmt(thrown));
            body.getTraps().add(Jimple.v().newTrap(
                    Scene.v().getSootClass("java.lang.Throwable"),
                    start, handler, handler));
            body.validate();
            found++;
        }
        return found;
    }

    private static SootClass application(String name) {
        SootClass type = Scene.v().getSootClassUnsafe(name);
        return type != null && type.isApplicationClass() ? type : null;
    }

    private static SootMethodRef bridge(String method, int arguments) {
        return bridge(BRIDGE, method, arguments);
    }

    private static SootMethodRef fileBridge(String method, int arguments) {
        return bridge(FILE_BRIDGE, method, arguments);
    }

    private static SootMethodRef bridge(String className, String method,
                                       int arguments) {
        SootClass type = Scene.v().loadClassAndSupport(className);
        soot.Type[] types = new soot.Type[arguments];
        Arrays.fill(types, RefType.v("java.lang.Object"));
        return Scene.v().makeMethodRef(type, method,
                Arrays.asList(types), VoidType.v(), true);
    }

    /** A method's normal return only: an IOException never produces a version. */
    private static int beforeSuccessfulEpochReturns(SootClass type,
                                                     String methodName,
                                                     boolean write,
                                                     SootMethodRef hook) {
        int methods = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || method.getParameterCount() != (write ? 2 : 1)
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            int returns = 0;
            Iterator<Unit> units = body.getUnits().snapshotIterator();
            while (units.hasNext()) {
                Unit unit = units.next();
                if (write && !(unit instanceof ReturnVoidStmt)) continue;
                if (!write && !(unit instanceof ReturnStmt)) continue;
                Value value = write ? body.getParameterLocal(1)
                        : ((ReturnStmt) unit).getOp();
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(),
                                body.getParameterLocal(0), value)), unit);
                returns++;
            }
            if (returns > 0) methods++;
        }
        return methods;
    }

    /** An ACK is sent only after serialization and its requested flush return. */
    private static int beforeSuccessfulPacketReturns(SootClass type,
                                                      String methodName,
                                                      SootMethodRef hook) {
        if (type == null) return 0;
        int methods = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || method.getParameterCount() != 2
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            int returns = 0;
            Iterator<Unit> units = body.getUnits().snapshotIterator();
            while (units.hasNext()) {
                Unit unit = units.next();
                if (!(unit instanceof ReturnVoidStmt)) continue;
                body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(),
                                body.getParameterLocal(0),
                                body.getParameterLocal(1))), unit);
                returns++;
            }
            if (returns > 0) methods++;
        }
        return methods;
    }

    private static int packetMethodEntry(SootClass type, String methodName,
                                         SootMethodRef hook) {
        if (type == null) return 0;
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || method.getParameterCount() != 2
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Unit first = null;
            for (Unit unit : body.getUnits()) {
                if (!(unit instanceof IdentityStmt)) {
                    first = unit;
                    break;
                }
            }
            if (first == null) continue;
            body.getUnits().insertBefore(Jimple.v().newInvokeStmt(
                    Jimple.v().newStaticInvokeExpr(hook,
                            body.getThisLocal(),
                            body.getParameterLocal(0),
                            body.getParameterLocal(1))), first);
            found++;
        }
        return found;
    }

    private static int beforeCall(SootClass type, String methodName,
                                  int sourceLine, String calledName,
                                  SootMethodRef hook) {
        if (type == null) return 0;
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            for (Iterator<Unit> units = body.getUnits().snapshotIterator();
                    units.hasNext();) {
                Unit unit = units.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()
                        || unit.getJavaSourceStartLineNumber() != sourceLine)
                    continue;
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

    /** LEADERINFO is sent only after the matching bufferedOutput.flush succeeds. */
    private static int afterFlushFollowingWrite(SootClass type,
                                                 String methodName,
                                                 int writeLine,
                                                 int flushLine,
                                                 SootMethodRef hook) {
        if (type == null) return 0;
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Value writtenPacket = null;
            Iterator<Unit> units = body.getUnits().snapshotIterator();
            while (units.hasNext()) {
                Unit unit = units.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr call = stmt.getInvokeExpr();
                int line = unit.getJavaSourceStartLineNumber();
                if (line == writeLine && "writeRecord".equals(
                        call.getMethodRef().name())
                        && call.getArgCount() > 0) {
                    if (writtenPacket != null) {
                        throw new IllegalStateException("ambiguous ZooKeeper "
                                + "LEADERINFO write anchor");
                    }
                    writtenPacket = call.getArg(0);
                } else if (line == flushLine && "flush".equals(
                        call.getMethodRef().name())) {
                    if (writtenPacket == null) {
                        throw new IllegalStateException("ZooKeeper "
                                + "LEADERINFO flush has no preceding write");
                    }
                    body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                            Jimple.v().newStaticInvokeExpr(hook,
                                    body.getThisLocal(), writtenPacket)),
                            unit);
                    writtenPacket = null;
                    found++;
                }
            }
        }
        return found;
    }

    /** The original JUnit's FileUtils.write(File, ...) changes epoch files. */
    private static int afterSuccessfulFileUtilsWrites() {
        int count = 0;
        SootMethodRef hook = fileBridge("successfulWrite", 1);
        for (SootClass type : new ArrayList<SootClass>(
                Scene.v().getApplicationClasses())) {
            for (SootMethod method : type.getMethods()) {
                if (!method.isConcrete()) continue;
                Body body = method.retrieveActiveBody();
                Iterator<Unit> units = body.getUnits().snapshotIterator();
                while (units.hasNext()) {
                    Unit unit = units.next();
                    if (!(unit instanceof Stmt)) continue;
                    Stmt stmt = (Stmt) unit;
                    if (!stmt.containsInvokeExpr()) continue;
                    InvokeExpr call = stmt.getInvokeExpr();
                    if (!"org.apache.commons.io.FileUtils".equals(
                            call.getMethodRef().declaringClass().getName())
                            || !"write".equals(call.getMethodRef().name())
                            || call.getArgCount() == 0
                            || !"java.io.File".equals(call.getArg(0)
                                    .getType().toString())) continue;
                    body.getUnits().insertAfter(Jimple.v().newInvokeStmt(
                            Jimple.v().newStaticInvokeExpr(hook,
                                    call.getArg(0))), unit);
                    count++;
                }
            }
        }
        return count;
    }

    private static int entry(SootClass type, String name, int parameters,
                             SootMethodRef hook, boolean withParameter) {
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(name)
                    || method.getParameterCount() != parameters
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Unit first = null;
            for (Unit unit : body.getUnits()) {
                if (!(unit instanceof IdentityStmt)) {
                    first = unit;
                    break;
                }
            }
            if (first == null) continue;
            Value owner = body.getThisLocal();
            Stmt invocation = withParameter
                    ? Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                            hook, owner, body.getParameterLocal(0)))
                    : Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                            hook, owner));
            body.getUnits().insertBefore(invocation, first);
            found++;
        }
        return found;
    }

    private static int afterCall(SootClass type, String methodName,
                                 int sourceLine, String calledName,
                                 SootMethodRef hook) {
        if (type == null) return 0;
        int found = 0;
        for (SootMethod method : type.getMethods()) {
            if (!method.getName().equals(methodName)
                    || !method.isConcrete()) continue;
            Body body = method.retrieveActiveBody();
            Iterator<Unit> units = body.getUnits().snapshotIterator();
            while (units.hasNext()) {
                Unit unit = units.next();
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()
                        || unit.getJavaSourceStartLineNumber() != sourceLine) {
                    continue;
                }
                InvokeExpr call = stmt.getInvokeExpr();
                if (!call.getMethodRef().name().equals(calledName)
                        || call.getArgCount() == 0) continue;
                Stmt invocation = Jimple.v().newInvokeStmt(
                        Jimple.v().newStaticInvokeExpr(hook,
                                body.getThisLocal(), call.getArg(0)));
                body.getUnits().insertAfter(invocation, unit);
                found++;
            }
        }
        return found;
    }
}
