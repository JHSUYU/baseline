package edu.uva.liftlab.graphchecker.causynth;

/**
 * Immutable class-file identity for one declared exception construction
 * ({@link ExceptionTargetLineResolver}); {@code id} is the target's name.
 */
public final class ExceptionTargetSite {
    final String id;
    final String className;
    final String methodName;
    final String methodDescriptor;
    final String methodSignature;
    final String exceptionClass;
    final int exceptionConstructionOrdinal;
    final int callUnitIndex;
    final String calledMethod;

    ExceptionTargetSite(String id, String className, String methodName,
                        String methodDescriptor, String methodSignature,
                        String exceptionClass,
                        int exceptionConstructionOrdinal) {
        this.id = id == null ? "" : id;
        this.className = className;
        this.methodName = methodName;
        this.methodDescriptor = methodDescriptor;
        this.methodSignature = methodSignature;
        this.exceptionClass = exceptionClass;
        this.exceptionConstructionOrdinal = exceptionConstructionOrdinal;
        this.callUnitIndex = -1;
        this.calledMethod = "";
    }

    ExceptionTargetSite(String id, soot.SootMethod owner, int callUnitIndex,
                        String calledMethod, String exceptionClass) {
        this.id = id == null ? "" : id;
        this.className = owner.getDeclaringClass().getName();
        this.methodName = owner.getName();
        this.methodDescriptor = "";
        this.methodSignature = owner.getSignature();
        this.exceptionClass = exceptionClass;
        this.exceptionConstructionOrdinal = -1;
        this.callUnitIndex = callUnitIndex;
        this.calledMethod = calledMethod;
    }

    public String stableIdentity() {
        if (callUnitIndex >= 0) return methodSignature + "#u" + callUnitIndex
                + "#callthrow:" + calledMethod + "#" + exceptionClass;
        return className + "#" + methodName + methodDescriptor + "#new:"
                + exceptionClass + "#" + exceptionConstructionOrdinal;
    }

}
