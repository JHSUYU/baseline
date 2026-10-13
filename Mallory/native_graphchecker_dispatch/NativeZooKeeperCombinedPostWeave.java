package edu.uva.liftlab.mallory.nativecampaign;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

/** Runs the two source-built ZooKeeper post-passes in their required order. */
public final class NativeZooKeeperCombinedPostWeave {
    private NativeZooKeeperCombinedPostWeave() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException(
                    "expected WOVEN_CLASSES IMMUTABLE_DEPENDENCY_CLASSPATH");
        }
        invoke("edu.uva.liftlab.graphchecker.causynth.NativeZooKeeperProtocolWeaveMain",
                new String[] {args[0], args[1], "all"});
        invoke("edu.uva.liftlab.mallory.nativebinding.NativeZooKeeperActorWeave",
                new String[] {"--classes", args[0]});
        System.out.println("NATIVE_ZOOKEEPER_COMBINED_POST_WEAVE_OK");
    }

    private static void invoke(String name, String[] args) throws Exception {
        Method main = Class.forName(name).getMethod("main", String[].class);
        try {
            main.invoke(null, (Object) args);
        } catch (InvocationTargetException wrapped) {
            Throwable cause = wrapped.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw wrapped;
        }
    }
}
