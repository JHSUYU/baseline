package edu.uva.liftlab.mallory.instrumentation;

import java.lang.instrument.Instrumentation;
import java.lang.instrument.ClassFileTransformer;
import java.io.File;
import java.util.jar.JarFile;

/** Launch with -javaagent:mallory-agent.jar=config=/absolute/agent.properties. */
public final class MalloryAgent {
  private MalloryAgent() { }

  public static void premain(String agentArgs, Instrumentation instrumentation) {
    try {
      AgentConfig config = AgentConfig.load(agentArgs);
      Probe.install(config.runId, config.events, FaultPlan.load(config.faultPlan));
      Probe.configureLimits(config.maxEvents, config.maxBytes);
      for (File adapterJar : config.adapterJars)
        instrumentation.appendToSystemClassLoaderSearch(new JarFile(adapterJar));
      instrumentation.addTransformer(new MalloryTransformer(config), false);
      for (String adapterName : config.adapterTransformers) {
        Class<?> adapter = Class.forName(adapterName, true, ClassLoader.getSystemClassLoader());
        if (!ClassFileTransformer.class.isAssignableFrom(adapter))
          throw new IllegalArgumentException(adapterName + " is not a ClassFileTransformer");
        instrumentation.addTransformer((ClassFileTransformer) adapter.newInstance(), false);
      }
    } catch (Exception failure) {
      throw new IllegalStateException("Mallory instrumentation startup failed", failure);
    }
  }
}
