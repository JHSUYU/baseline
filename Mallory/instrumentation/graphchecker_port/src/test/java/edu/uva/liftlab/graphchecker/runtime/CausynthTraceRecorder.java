package edu.uva.liftlab.graphchecker.runtime;

/** Test classpath stand-in for the separately built original recorder. */
public final class CausynthTraceRecorder {
    public static String siteId;
    public static String nodeId;
    public static String occurrenceId;
    public static long ordinal;
    public static String exceptionClass;
    public static Object owner;

    private CausynthTraceRecorder() { }

    public static void recordNativeFaultDoor(String site, String node,
                                             String occurrence, long doorOrdinal,
                                             String exception, Object receiver) {
        siteId = site;
        nodeId = node;
        occurrenceId = occurrence;
        ordinal = doorOrdinal;
        exceptionClass = exception;
        owner = receiver;
    }
}
