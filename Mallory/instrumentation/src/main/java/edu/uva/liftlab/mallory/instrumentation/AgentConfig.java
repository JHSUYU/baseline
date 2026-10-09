package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.Gson;
import com.google.gson.annotations.SerializedName;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Properties;

/** Trial-local agent settings. Each fuzz trial starts a fresh JVM. */
public final class AgentConfig {
  public String runId = "run";
  public File events;
  public File faultPlan;
  public File siteCatalog;
  public List<String> includes = new ArrayList<String>();
  public List<SiteRule> targets = new ArrayList<SiteRule>();
  public List<SiteRule> doors = new ArrayList<SiteRule>();
  public List<SiteRule> regions = new ArrayList<SiteRule>();
  public List<SiteRule> async = new ArrayList<SiteRule>();
  public List<NodeBinding> nodeBindings = new ArrayList<NodeBinding>();
  public boolean autoIoDoors;
  public boolean methodCoverage = true;
  public boolean branchCoverage = true;
  public boolean fieldState;
  public boolean mapState;
  public long maxEvents = 1000000L;
  public long maxBytes = 100L * 1024L * 1024L;
  public List<String> adapterTransformers = new ArrayList<String>();
  public List<File> adapterJars = new ArrayList<File>();

  public static AgentConfig load(String agentArgs) throws IOException {
    Properties props = new Properties();
    if (agentArgs != null && !agentArgs.trim().isEmpty()) {
      String path = agentArgs.startsWith("config=") ? agentArgs.substring(7) : agentArgs;
      FileInputStream in = new FileInputStream(path);
      try { props.load(in); } finally { in.close(); }
    }
    AgentConfig config = new AgentConfig();
    config.runId = value("MALLORY_RUN_ID", props.getProperty("run.id"), "run");
    String eventPath = value("MALLORY_EVENT_FILE", props.getProperty("events"), null);
    if (eventPath == null) throw new IOException("MALLORY_EVENT_FILE or events is required");
    config.events = new File(eventPath);
    String planPath = value("MALLORY_PLAN_FILE", props.getProperty("fault.plan"), null);
    if (planPath != null && !planPath.isEmpty()) config.faultPlan = new File(planPath);
    String catalogPath = value("MALLORY_SITE_CATALOG", props.getProperty("site.catalog"), null);
    if (catalogPath != null && !catalogPath.isEmpty()) config.siteCatalog = new File(catalogPath);
    String include = props.getProperty("include", "");
    if (!include.trim().isEmpty()) {
      for (String prefix : include.split(",")) {
        prefix = prefix.trim().replace('.', '/');
        if (!prefix.isEmpty()) config.includes.add(prefix);
      }
    }
    String sitePath = value("MALLORY_SITE_FILE", props.getProperty("site.file"), null);
    if (sitePath != null && !sitePath.isEmpty()) {
      FileReader reader = new FileReader(sitePath);
      SiteFile sites;
      try { sites = new Gson().fromJson(reader, SiteFile.class); } finally { reader.close(); }
      if (sites != null) {
        config.targets = nonNull(sites.targets);
        config.doors = nonNull(sites.doors);
        config.regions = nonNull(sites.regions);
        config.async = nonNull(sites.async);
        config.nodeBindings = sites.nodeBindings == null
            ? new ArrayList<NodeBinding>() : sites.nodeBindings;
      }
    }
    config.autoIoDoors = Boolean.parseBoolean(props.getProperty("auto.io.doors", "false"));
    config.methodCoverage = Boolean.parseBoolean(props.getProperty("coverage.methods", "true"));
    config.branchCoverage = Boolean.parseBoolean(props.getProperty("coverage.branches", "true"));
    config.fieldState = Boolean.parseBoolean(props.getProperty("state.fields", "false"));
    config.mapState = Boolean.parseBoolean(props.getProperty("state.maps", "false"));
    config.maxEvents = positiveLong(props.getProperty("max.events"), config.maxEvents);
    config.maxBytes = positiveLong(props.getProperty("max.bytes"), config.maxBytes);
    String adapters = value("MALLORY_ADAPTER_TRANSFORMERS",
        props.getProperty("adapter.transformers", props.getProperty("adapter.transformer")), "");
    for (String name : adapters.split(",")) if (!name.trim().isEmpty())
      config.adapterTransformers.add(name.trim());
    String jars = value("MALLORY_ADAPTER_JARS",
        props.getProperty("adapter.jars", props.getProperty("adapter.jar")), "");
    for (String path : jars.split(",")) if (!path.trim().isEmpty())
      config.adapterJars.add(new File(path.trim()));
    if (config.includes.isEmpty()) {
      for (SiteRule rule : concat(config.targets, config.doors, config.regions, config.async)) {
        if (rule.className() != null) config.includes.add(rule.className());
      }
      for (NodeBinding binding : config.nodeBindings)
        if (binding.clazz != null) config.includes.add(binding.clazz.replace('.', '/'));
    }
    return config;
  }

  private static String value(String env, String prop, String fallback) {
    String fromEnv = System.getenv(env);
    return fromEnv != null && !fromEnv.isEmpty() ? fromEnv : prop != null ? prop : fallback;
  }

  private static long positiveLong(String text, long fallback) {
    if (text == null || text.trim().isEmpty()) return fallback;
    long parsed = Long.parseLong(text.trim());
    if (parsed <= 0) throw new IllegalArgumentException("Trace limit must be positive");
    return parsed;
  }

  private static List<SiteRule> nonNull(List<SiteRule> list) {
    return list == null ? new ArrayList<SiteRule>() : list;
  }

  @SafeVarargs
  private static List<SiteRule> concat(List<SiteRule>... groups) {
    List<SiteRule> result = new ArrayList<SiteRule>();
    for (List<SiteRule> group : groups) result.addAll(group);
    return result;
  }

  public boolean includes(String internalClass) {
    if (internalClass == null) return false;
    String agentPackage = "edu/uva/liftlab/mallory/instrumentation/";
    if (internalClass.startsWith(agentPackage)
        && internalClass.indexOf('/', agentPackage.length()) < 0) return false;
    for (String selector : includes) {
      if (selector.endsWith("/") && internalClass.startsWith(selector)) return true;
      if (selector.endsWith("*")
          && internalClass.startsWith(selector.substring(0, selector.length() - 1))) return true;
      if (internalClass.equals(selector)) return true;
    }
    return false;
  }

  public static final class SiteFile {
    public List<SiteRule> targets;
    public List<SiteRule> doors;
    public List<SiteRule> regions;
    public List<SiteRule> async;
    public List<NodeBinding> nodeBindings;
  }

  public static final class NodeBinding {
    @SerializedName(value = "class", alternate = {"clazz"})
    public String clazz;
    public String method;
    public String descriptor;
    public String field;
    public String getter;
    public String prefix;

    public boolean matches(String owner, String name, String desc) {
      return clazz != null && clazz.replace('.', '/').equals(owner)
          && method != null && method.equals(name)
          && (descriptor == null || descriptor.equals(desc))
          && ((field != null && !field.isEmpty()) || (getter != null && !getter.isEmpty()));
    }
  }

  public static final class SiteRule {
    @SerializedName(value = "class", alternate = {"clazz"})
    public String clazz;
    public String method;
    public String descriptor;
    public Integer line;
    public String callee;
    @SerializedName(value = "exception_class", alternate = {"exceptionClass"})
    public String exceptionClass;

    public String className() { return clazz == null ? null : clazz.replace('.', '/'); }

    public boolean matches(String owner, String name, String desc, int currentLine, String invoked) {
      if (clazz != null && !className().equals(owner)) return false;
      if (method != null && !method.equals(name)) return false;
      if (descriptor != null && !descriptor.equals(desc)) return false;
      if (line != null && line.intValue() != currentLine) return false;
      return callee == null || callee.equals(invoked);
    }
  }
}
