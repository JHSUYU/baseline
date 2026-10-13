package edu.uva.liftlab.graphchecker;

/** Exposes GraphChecker's original lambda naming rule to Mallory's Soot scene. */
public final class MalloryLambdaClassNames {
    private MalloryLambdaClassNames() { }

    public static void install() {
        LambdaClassNames.install();
    }
}
