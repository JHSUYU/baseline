package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public final class SootCalleeIdentityTest {
    @Test public void ignoresOnlyGeneratedLambdaSequenceNumber() {
        String selected = "<org.apache.zookeeper.server.NIOServerCnxnFactory"
                + "$lambda_static_0__64: java.lang.Thread$UncaughtExceptionHandler bootstrap$()>";
        String actual = "<org.apache.zookeeper.server.NIOServerCnxnFactory"
                + "$lambda_static_0__31: java.lang.Thread$UncaughtExceptionHandler bootstrap$()>";
        assertTrue(SootSiteWeaver.sameCallee(actual, selected));
        assertFalse(SootSiteWeaver.sameCallee(actual,
                selected.replace("lambda_static_0", "lambda_static_1")));
        assertFalse(SootSiteWeaver.sameCallee(actual,
                selected.replace("bootstrap$()", "other()")));
        assertFalse(SootSiteWeaver.sameCallee("<X: void close()>", "<Y: void close()>"));
    }
}
