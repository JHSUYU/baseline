package edu.uva.liftlab.mallory.graphchecker.weave;

/** Process boundary for cluster tests that leave non-daemon server threads. */
public final class JUnitTrialMain {
    private JUnitTrialMain() { }

    public static void main(String[] args) {
        int status = 0;
        try {
            JUnitTrialRunner.main(args);
        } catch (Throwable failure) {
            failure.printStackTrace(System.err);
            status = 1;
        }
        System.exit(status);
    }
}
