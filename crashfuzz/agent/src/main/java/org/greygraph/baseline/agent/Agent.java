package org.greygraph.baseline.agent;

import java.io.FileInputStream;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.util.Properties;

/** One instrumentation path for method, field, branch, and fault events. */
public final class Agent {
    private Agent() { }

    public static void premain(String configPath, Instrumentation instrumentation) {
        if (configPath == null || configPath.trim().isEmpty()) {
            throw new IllegalArgumentException(
                    "-javaagent:adhoc-crashfuzz-agent.jar=/path/agent.properties is required");
        }
        Properties properties = new Properties();
        try (FileInputStream input = new FileInputStream(configPath)) {
            properties.load(input);
        } catch (IOException error) {
            throw new IllegalStateException("cannot read agent config " + configPath, error);
        }
        Hook.configure(properties);
        instrumentation.addTransformer(new ProbeTransformer(properties), false);
    }
}
