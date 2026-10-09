package zk10;

import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.TestIdentifier;
import org.junit.platform.launcher.TestPlan;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;

/** Inspect how Jupiter resolves the single parameterized invocation. */
public final class DiscoveryProbe {
    private static void show(TestPlan plan, TestIdentifier id, String prefix) {
        System.out.println(prefix + id.getUniqueId() + " | " + id.getDisplayName()
                + " | test=" + id.isTest());
        for (TestIdentifier child : plan.getChildren(id)) {
            show(plan, child, prefix + "  ");
        }
    }

    public static void main(String[] args) {
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectUniqueId(args[0]))
                .build();
        Launcher launcher = LauncherFactory.create();
        TestPlan plan = launcher.discover(request);
        for (TestIdentifier root : plan.getRoots()) {
            show(plan, root, "");
        }
    }
}
