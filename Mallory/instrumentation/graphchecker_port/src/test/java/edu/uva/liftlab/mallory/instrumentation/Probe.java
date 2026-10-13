package edu.uva.liftlab.mallory.instrumentation;

/** Test double for the optional original Mallory fault-plan controller. */
public final class Probe {
    public static volatile String observed;
    public static volatile boolean inject;
    private Probe() { }
    public static void beforeDoor(String siteId, String exceptionClass) {
        observed = siteId + ":" + exceptionClass;
        if (inject) Probe.<RuntimeException>throwUnchecked(
                new java.io.IOException("synthetic transport fault"));
    }

    @SuppressWarnings("unchecked")
    private static <E extends Throwable> void throwUnchecked(Throwable failure) throws E {
        throw (E) failure;
    }
}
