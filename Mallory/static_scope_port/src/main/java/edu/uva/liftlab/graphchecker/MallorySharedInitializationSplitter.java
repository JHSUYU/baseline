package edu.uva.liftlab.graphchecker;

/** Exposes GraphChecker's original jb.sils replacement to Mallory's scene. */
public final class MallorySharedInitializationSplitter {
    private MallorySharedInitializationSplitter() { }

    public static void install() {
        SharedInitializationSplitter.install();
    }
}
