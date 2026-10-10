package edu.uva.liftlab.mallory.instrumentation;

import java.lang.instrument.ClassFileTransformer;
import java.io.IOException;
import java.io.InputStream;
import java.security.ProtectionDomain;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.LookupSwitchInsnNode;
import org.objectweb.asm.tree.TableSwitchInsnNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Selective ASM rewrite. Site names identify bytecode locations, not source lines alone. */
public final class MalloryTransformer implements ClassFileTransformer {
  private static final String PROBE = Type.getInternalName(Probe.class);
  private final AgentConfig config;
  private final SiteCatalog catalog;

  public MalloryTransformer(AgentConfig config) {
    this.config = config;
    try {
      this.catalog = config.siteCatalog == null ? null : new SiteCatalog(config.siteCatalog);
    } catch (IOException failure) {
      throw new IllegalStateException("Cannot open Mallory site catalog", failure);
    }
  }

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> classBeingRedefined,
                                    ProtectionDomain protectionDomain, byte[] classfileBuffer) {
    if (!config.includes(className)) return null;
    try {
      ClassNode node = new ClassNode();
      new ClassReader(classfileBuffer).accept(node, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      List<Map<String, Object>> sites = new ArrayList<Map<String, Object>>();
      for (MethodNode method : node.methods) {
        if (instrumentMethod(node.name, node.superName, method, sites)) changed = true;
      }
      if (!changed) return null;
      ClassWriter writer = new SafeWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
          loader, node);
      node.accept(writer);
      byte[] result = writer.toByteArray();
      if (catalog != null) {
        String originalHash = sha256(classfileBuffer);
        String transformedHash = sha256(result);
        String loaderId = loader == null ? "bootstrap" : loader.getClass().getName()
            + "@" + Integer.toHexString(System.identityHashCode(loader));
        for (Map<String, Object> site : sites) {
          site.put("class_name", node.name.replace('/', '.'));
          site.put("bytecode_sha256", originalHash);
          site.put("instrumented_sha256", transformedHash);
          site.put("class_loader_id", loaderId);
        }
        catalog.append(sites);
      }
      return result;
    } catch (Throwable failure) {
      System.err.println("Mallory could not instrument " + className + ": " + failure);
      return null;
    }
  }

  private static String sha256(byte[] bytes) throws Exception {
    byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
    StringBuilder hex = new StringBuilder(digest.length * 2);
    for (byte value : digest) hex.append(String.format("%02x", value & 255));
    return hex.toString();
  }

  private boolean instrumentMethod(String owner, String superOwner, MethodNode method,
                                   List<Map<String, Object>> sites) {
    if ((method.access & (Opcodes.ACC_ABSTRACT | Opcodes.ACC_NATIVE)) != 0
        || method.name.equals("<clinit>")
        || method.instructions.size() == 0) return false;
    AbstractInsnNode constructorInit = method.name.equals("<init>")
        ? constructorInitialization(owner, superOwner, method) : null;
    if (method.name.equals("<init>") && constructorInit == null) return false;
    String methodSite = siteBase(owner, method);
    boolean region = matches(config.regions, owner, method, -1, null);
    AgentConfig.NodeBinding nodeBinding = nodeBinding(owner, method);
    if (nodeBinding != null && (method.access & Opcodes.ACC_STATIC) != 0)
      throw new IllegalArgumentException("Node binding needs an instance method: " + methodSite);
    int line = -1;
    int branchIndex = 0;
    int doorIndex = 0;
    int asyncIndex = 0;
    int fieldIndex = 0;
    int throwIndex = 0;
    int callIndex = 0;
    boolean initialized = constructorInit == null;
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof LineNumberNode) {
        line = ((LineNumberNode) instruction).line;
        continue;
      }
      if (instruction instanceof MethodInsnNode) callIndex++;
      if (!initialized) {
        if (instruction == constructorInit) initialized = true;
        continue;
      }
      if (instruction instanceof JumpInsnNode && isConditional(instruction.getOpcode())) {
        if (config.branchCoverage || matches(config.targets, owner, method, line, null)) {
          String site = methodSite + "@" + line + ":branch:" + (++branchIndex);
          boolean target = matches(config.targets, owner, method, line, null);
          instrumentBranch(method, (JumpInsnNode) instruction, site, target);
          if (target) sites.add(catalogRow("TARGET_CHECK", site, line, null));
          changed = true;
        }
      } else if (instruction instanceof TableSwitchInsnNode) {
        if (config.branchCoverage || matches(config.targets, owner, method, line, null)) {
          instrumentTableSwitch(method, (TableSwitchInsnNode) instruction,
              methodSite + "@" + line + ":branch:" + (++branchIndex),
              matches(config.targets, owner, method, line, null));
          if (matches(config.targets, owner, method, line, null))
            sites.add(catalogRow("TARGET_CHECK", methodSite + "@" + line + ":branch:" + branchIndex, line, null));
          changed = true;
        }
      } else if (instruction instanceof LookupSwitchInsnNode) {
        if (config.branchCoverage || matches(config.targets, owner, method, line, null)) {
          instrumentLookupSwitch(method, (LookupSwitchInsnNode) instruction,
              methodSite + "@" + line + ":branch:" + (++branchIndex),
              matches(config.targets, owner, method, line, null));
          if (matches(config.targets, owner, method, line, null))
            sites.add(catalogRow("TARGET_CHECK", methodSite + "@" + line + ":branch:" + branchIndex, line, null));
          changed = true;
        }
      } else if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        String callee = call.owner.replace('/', '.') + "#" + call.name + call.desc;
        AgentConfig.SiteRule doorRule = matchingRule(config.doors, owner, method, line, callee);
        if (doorRule != null || config.autoIoDoors && isIoCall(call)) {
          String site = methodSite + "@" + line + ":door:" + (++doorIndex);
          String exceptionClass = doorRule != null && doorRule.exceptionClass != null
              && !doorRule.exceptionClass.isEmpty() ? doorRule.exceptionClass : "java.io.IOException";
          InsnList probe = new InsnList();
          probe.add(new LdcInsnNode(site));
          probe.add(new LdcInsnNode(exceptionClass));
          probe.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "beforeDoor",
              "(Ljava/lang/String;Ljava/lang/String;)V", false));
          method.instructions.insertBefore(call, probe);
          Map<String, Object> doorSite = catalogRow("DOOR_OBSERVED", site, line, callee);
          doorSite.put("exception_class", exceptionClass);
          sites.add(doorSite);
          changed = true;
        }
        if (matches(config.async, owner, method, line, callee)) {
          String site = methodSite + "@" + line + ":async:" + (++asyncIndex);
          if (instrumentAsyncCall(method, call, site)) {
            sites.add(catalogRow("TASK_SUBMIT", site, line, callee));
            changed = true;
          }
        }
        if (config.mapState && isMapCall(call)) {
          instrumentMapCall(method, call, methodSite + "@" + line + ":map:" + (++fieldIndex));
          changed = true;
        }
        AgentConfig.SiteRule targetCall = matchingCallRule(config.targets, owner, method, line, callee);
        if (targetCall != null) {
          String site = methodSite + "@" + line + ":callthrow:" + callIndex;
          instrumentCallThrow(method, call, site);
          Map<String, Object> row = catalogRow("TARGET_THROW", site, line, callee);
          if (targetCall.exceptionClass != null && !targetCall.exceptionClass.isEmpty())
            row.put("exception_class", targetCall.exceptionClass);
          sites.add(row);
          changed = true;
        }
      } else if (instruction instanceof FieldInsnNode && config.fieldState) {
        instrumentField(method, (FieldInsnNode) instruction,
            methodSite + "@" + line + ":field:" + (++fieldIndex));
        changed = true;
      } else if (instruction.getOpcode() == Opcodes.ATHROW
          && matches(config.targets, owner, method, line, null)) {
        String site = methodSite + "@" + line + ":throw:" + (++throwIndex);
        InsnList probe = new InsnList();
        probe.add(new InsnNode(Opcodes.DUP));
        probe.add(new LdcInsnNode(site));
        probe.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
            "(Ljava/lang/Throwable;Ljava/lang/String;)V", false));
        method.instructions.insertBefore(instruction, probe);
        sites.add(catalogRow("TARGET_THROW", site, line, null));
        changed = true;
      }
    }
    if (config.methodCoverage) {
      if (constructorInit == null)
        method.instructions.insert(staticCall(methodSite, "method", "(Ljava/lang/String;)V"));
      else
        method.instructions.insert(constructorInit,
            staticCall(methodSite, "method", "(Ljava/lang/String;)V"));
      changed = true;
    }
    if (region || nodeBinding != null) {
      instrumentScopes(method, methodSite, region, nodeBinding, constructorInit);
      if (region) sites.add(catalogRow("REGION_ENTER", methodSite, -1, null));
      if (nodeBinding != null) sites.add(catalogRow("NODE_BINDING", methodSite, -1, null));
      changed = true;
    }
    return changed;
  }

  private static AbstractInsnNode constructorInitialization(String owner, String superOwner,
                                                              MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (call.getOpcode() == Opcodes.INVOKESPECIAL && "<init>".equals(call.name)
          && (owner.equals(call.owner) || superOwner != null && superOwner.equals(call.owner)))
        return call;
    }
    return null;
  }

  private static void instrumentCallThrow(MethodNode method, MethodInsnNode call, String site) {
    LabelNode start = new LabelNode();
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    LabelNode resume = new LabelNode();
    method.instructions.insertBefore(call, start);
    InsnList after = new InsnList();
    after.add(end);
    after.add(new JumpInsnNode(Opcodes.GOTO, resume));
    after.add(handler);
    after.add(new InsnNode(Opcodes.DUP));
    after.add(new LdcInsnNode(site));
    after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
        "(Ljava/lang/Throwable;Ljava/lang/String;)V", false));
    after.add(new InsnNode(Opcodes.ATHROW));
    after.add(resume);
    method.instructions.insert(call, after);
    method.tryCatchBlocks.add(0,
        new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static Map<String, Object> catalogRow(String type, String site, int line, String callee) {
    Map<String, Object> row = new LinkedHashMap<String, Object>();
    row.put("type", type);
    row.put("site", site);
    row.put("line", line);
    if (callee != null) row.put("callee", callee);
    if ("DOOR_OBSERVED".equals(type)) {
      row.put("fault_type", "EXCEPTION");
      row.put("exception_class", "java.io.IOException");
    }
    return row;
  }

  private static void instrumentBranch(MethodNode method, JumpInsnNode jump,
                                       String site, boolean target) {
    LabelNode originalTarget = jump.label;
    LabelNode trueLabel = new LabelNode();
    LabelNode resumeLabel = new LabelNode();
    jump.label = trueLabel;
    InsnList edges = new InsnList();
    edges.add(branchCall(site, false, target));
    edges.add(new JumpInsnNode(Opcodes.GOTO, resumeLabel));
    edges.add(trueLabel);
    edges.add(branchCall(site, true, target));
    edges.add(new JumpInsnNode(Opcodes.GOTO, originalTarget));
    edges.add(resumeLabel);
    method.instructions.insert(jump, edges);
  }

  private static InsnList branchCall(String site, boolean taken, boolean target) {
    InsnList call = new InsnList();
    call.add(new LdcInsnNode(site));
    call.add(new InsnNode(taken ? Opcodes.ICONST_1 : Opcodes.ICONST_0));
    call.add(new InsnNode(target ? Opcodes.ICONST_1 : Opcodes.ICONST_0));
    call.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "branch", "(Ljava/lang/String;ZZ)V", false));
    return call;
  }

  private static void instrumentTableSwitch(MethodNode method, TableSwitchInsnNode branch,
                                            String site, boolean target) {
    InsnList edges = new InsnList();
    LabelNode originalDefault = branch.dflt;
    branch.dflt = switchEdge(edges, site, "DEFAULT", target, originalDefault);
    for (int i = 0; i < branch.labels.size(); i++) {
      LabelNode original = branch.labels.get(i);
      branch.labels.set(i, switchEdge(edges, site, "CASE:" + (branch.min + i), target, original));
    }
    method.instructions.insert(branch, edges);
  }

  private static void instrumentLookupSwitch(MethodNode method, LookupSwitchInsnNode branch,
                                             String site, boolean target) {
    InsnList edges = new InsnList();
    LabelNode originalDefault = branch.dflt;
    branch.dflt = switchEdge(edges, site, "DEFAULT", target, originalDefault);
    for (int i = 0; i < branch.labels.size(); i++) {
      LabelNode original = branch.labels.get(i);
      branch.labels.set(i, switchEdge(edges, site, "CASE:" + branch.keys.get(i), target, original));
    }
    method.instructions.insert(branch, edges);
  }

  private static LabelNode switchEdge(InsnList edges, String site, String outcome,
                                      boolean target, LabelNode original) {
    LabelNode trampoline = new LabelNode();
    edges.add(trampoline);
    edges.add(new LdcInsnNode(site));
    edges.add(new LdcInsnNode(outcome));
    edges.add(new InsnNode(target ? Opcodes.ICONST_1 : Opcodes.ICONST_0));
    edges.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "branchCase",
        "(Ljava/lang/String;Ljava/lang/String;Z)V", false));
    edges.add(new JumpInsnNode(Opcodes.GOTO, original));
    return trampoline;
  }

  private AgentConfig.NodeBinding nodeBinding(String owner, MethodNode method) {
    for (AgentConfig.NodeBinding binding : config.nodeBindings)
      if (binding.matches(owner, method.name, method.desc)) return binding;
    return null;
  }

  private static void instrumentScopes(MethodNode method, String site, boolean region,
                                       AgentConfig.NodeBinding nodeBinding,
                                       AbstractInsnNode constructorInit) {
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    if (nodeBinding != null) {
      entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
      entry.add(new LdcInsnNode(nodeBinding.field != null && !nodeBinding.field.isEmpty()
          ? nodeBinding.field : nodeBinding.getter));
      entry.add(new LdcInsnNode(nodeBinding.prefix == null ? "" : nodeBinding.prefix));
      entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE,
          nodeBinding.field != null && !nodeBinding.field.isEmpty()
              ? "enterNodeFromField" : "enterNodeFromGetter",
          "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false));
    }
    if (region) entry.add(staticCall(site, "regionEnter", "(Ljava/lang/String;)V"));
    entry.add(start);
    if (constructorInit == null) method.instructions.insert(entry);
    else method.instructions.insert(constructorInit, entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int opcode = instruction.getOpcode();
      if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN) {
        method.instructions.insertBefore(instruction, exitScopes(site, region, nodeBinding != null));
      }
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(exitScopes(site, region, nodeBinding != null));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList exitScopes(String site, boolean region, boolean nodeBinding) {
    InsnList exit = new InsnList();
    if (region) exit.add(staticCall(site, "regionExit", "(Ljava/lang/String;)V"));
    if (nodeBinding) exit.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE,
        "exitNode", "()V", false));
    return exit;
  }

  private static InsnList staticCall(String site, String name, String descriptor) {
    InsnList result = new InsnList();
    result.add(new LdcInsnNode(site));
    result.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, name, descriptor, false));
    return result;
  }

  private static boolean isConditional(int opcode) {
    return opcode >= Opcodes.IFEQ && opcode <= Opcodes.IF_ACMPNE
        || opcode == Opcodes.IFNULL || opcode == Opcodes.IFNONNULL;
  }

  private static String siteBase(String owner, MethodNode method) {
    return owner.replace('/', '.') + "#" + method.name + method.desc;
  }

  private static boolean matches(List<AgentConfig.SiteRule> rules, String owner,
                                 MethodNode method, int line, String callee) {
    return matchingRule(rules, owner, method, line, callee) != null;
  }

  private static AgentConfig.SiteRule matchingRule(List<AgentConfig.SiteRule> rules, String owner,
                                 MethodNode method, int line, String callee) {
    for (AgentConfig.SiteRule rule : rules) {
      if (rule.matches(owner, method.name, method.desc, line, callee)) return rule;
    }
    return null;
  }

  private static AgentConfig.SiteRule matchingCallRule(List<AgentConfig.SiteRule> rules,
      String owner, MethodNode method, int line, String callee) {
    for (AgentConfig.SiteRule rule : rules)
      if (rule.callee != null && rule.matches(owner, method.name, method.desc, line, callee))
        return rule;
    return null;
  }

  private static boolean isIoCall(MethodInsnNode call) {
    String owner = call.owner;
    return owner.startsWith("java/io/") && (call.name.startsWith("read") ||
        call.name.startsWith("write") || call.name.equals("flush") || call.name.equals("sync"))
        || owner.startsWith("java/net/") && (call.name.startsWith("connect") ||
        call.name.startsWith("send") || call.name.startsWith("receive"))
        || owner.startsWith("java/nio/channels/") && (call.name.startsWith("read") ||
        call.name.startsWith("write") || call.name.startsWith("connect"))
        || owner.startsWith("org/apache/hadoop/ipc/") && call.name.equals("call")
        || owner.startsWith("org/apache/hadoop/hbase/ipc/") && call.name.equals("call")
        || owner.startsWith("org/apache/solr/client/solrj/") && call.name.equals("request");
  }

  private static boolean isMapCall(MethodInsnNode call) {
    return (call.owner.equals("java/util/Map") || call.owner.equals("java/util/HashMap")
        || call.owner.equals("java/util/concurrent/ConcurrentHashMap"))
        && (call.name.equals("get") && call.desc.equals("(Ljava/lang/Object;)Ljava/lang/Object;")
        || call.name.equals("put") && call.desc.equals("(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;"));
  }

  private static boolean instrumentAsyncCall(MethodNode method, MethodInsnNode call, String site) {
    Type[] arguments = Type.getArgumentTypes(call.desc);
    if (arguments.length != 1) return false;
    String name;
    String descriptor;
    if (arguments[0].getDescriptor().equals("Ljava/lang/Runnable;")) {
      name = "wrapRunnable";
      descriptor = "(Ljava/lang/Runnable;Ljava/lang/String;)Ljava/lang/Runnable;";
    } else if (arguments[0].getDescriptor().equals("Ljava/util/concurrent/Callable;")) {
      name = "wrapCallable";
      descriptor = "(Ljava/util/concurrent/Callable;Ljava/lang/String;)Ljava/util/concurrent/Callable;";
    } else return false;
    InsnList wrap = new InsnList();
    wrap.add(new LdcInsnNode(site));
    wrap.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, name, descriptor, false));
    method.instructions.insertBefore(call, wrap);
    return true;
  }

  private static void instrumentMapCall(MethodNode method, MethodInsnNode call, String site) {
    // Preserve the invocation's result and emit only after it completes successfully.
    int local = method.maxLocals;
    int receiver = local;
    int key = local + 1;
    int valueOrResult = local + 2;
    method.maxLocals += 3;
    boolean write = call.name.equals("put");
    InsnList before = new InsnList();
    if (write) before.add(new VarInsnNode(Opcodes.ASTORE, valueOrResult));
    before.add(new VarInsnNode(Opcodes.ASTORE, key));
    before.add(new VarInsnNode(Opcodes.ASTORE, receiver));
    before.add(new VarInsnNode(Opcodes.ALOAD, receiver));
    before.add(new VarInsnNode(Opcodes.ALOAD, key));
    if (write) before.add(new VarInsnNode(Opcodes.ALOAD, valueOrResult));
    method.instructions.insertBefore(call, before);
    InsnList after = new InsnList();
    after.add(new VarInsnNode(Opcodes.ASTORE, valueOrResult));
    after.add(new VarInsnNode(Opcodes.ALOAD, receiver));
    after.add(new VarInsnNode(Opcodes.ALOAD, key));
    after.add(new LdcInsnNode(site));
    after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE,
        write ? "stateWrite" : "stateRead",
        "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;)V", false));
    after.add(new VarInsnNode(Opcodes.ALOAD, valueOrResult));
    method.instructions.insert(call, after);
  }

  private static void instrumentField(MethodNode method, FieldInsnNode field, String site) {
    int opcode = field.getOpcode();
    Type type = Type.getType(field.desc);
    int ownerLocal = method.maxLocals;
    int valueLocal = ownerLocal + 1;
    method.maxLocals += 1 + type.getSize();
    String key = field.owner.replace('/', '.') + "#" + field.name;
    InsnList before = new InsnList();
    InsnList after = new InsnList();
    if (opcode == Opcodes.GETFIELD) {
      before.add(new VarInsnNode(Opcodes.ASTORE, ownerLocal));
      before.add(new VarInsnNode(Opcodes.ALOAD, ownerLocal));
      after.add(new VarInsnNode(type.getOpcode(Opcodes.ISTORE), valueLocal));
      after.add(new VarInsnNode(Opcodes.ALOAD, ownerLocal));
      after.add(new LdcInsnNode(key));
      after.add(new LdcInsnNode(site));
      after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "stateRead",
          "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;)V", false));
      after.add(new VarInsnNode(type.getOpcode(Opcodes.ILOAD), valueLocal));
    } else if (opcode == Opcodes.PUTFIELD) {
      before.add(new VarInsnNode(type.getOpcode(Opcodes.ISTORE), valueLocal));
      before.add(new VarInsnNode(Opcodes.ASTORE, ownerLocal));
      before.add(new VarInsnNode(Opcodes.ALOAD, ownerLocal));
      before.add(new VarInsnNode(type.getOpcode(Opcodes.ILOAD), valueLocal));
      after.add(new VarInsnNode(Opcodes.ALOAD, ownerLocal));
      after.add(new LdcInsnNode(key));
      after.add(new LdcInsnNode(site));
      after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "stateWrite",
          "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;)V", false));
    } else if (opcode == Opcodes.GETSTATIC) {
      after.add(new VarInsnNode(type.getOpcode(Opcodes.ISTORE), valueLocal));
      after.add(new InsnNode(Opcodes.ACONST_NULL));
      after.add(new LdcInsnNode(key));
      after.add(new LdcInsnNode(site));
      after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "stateRead",
          "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;)V", false));
      after.add(new VarInsnNode(type.getOpcode(Opcodes.ILOAD), valueLocal));
    } else if (opcode == Opcodes.PUTSTATIC) {
      before.add(new VarInsnNode(type.getOpcode(Opcodes.ISTORE), valueLocal));
      before.add(new VarInsnNode(type.getOpcode(Opcodes.ILOAD), valueLocal));
      after.add(new InsnNode(Opcodes.ACONST_NULL));
      after.add(new LdcInsnNode(key));
      after.add(new LdcInsnNode(site));
      after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "stateWrite",
          "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;)V", false));
    }
    method.instructions.insertBefore(field, before);
    method.instructions.insert(field, after);
  }

  private static final class SafeWriter extends ClassWriter {
    private final ClassLoader loader;
    private final ClassNode current;
    private final Map<String, ClassInfo> classes = new HashMap<String, ClassInfo>();

    SafeWriter(int flags, ClassLoader loader, ClassNode current) {
      super(flags);
      this.loader = loader;
      this.current = current;
    }

    @Override protected String getCommonSuperClass(String first, String second) {
      try { return commonSuperClass(first, second); }
      catch (IOException | RuntimeException unavailable) { return "java/lang/Object"; }
    }

    private String commonSuperClass(String first, String second) throws IOException {
      if (first.equals(second)) return first;
      if (assignable(first, second, new HashSet<String>())) return first;
      if (assignable(second, first, new HashSet<String>())) return second;
      if (first.startsWith("[") || second.startsWith("[")) {
        if (!first.startsWith("[") || !second.startsWith("[")) return "java/lang/Object";
        String leftComponent = component(first);
        String rightComponent = component(second);
        if (primitive(leftComponent) || primitive(rightComponent)) return "java/lang/Object";
        return "[" + descriptor(commonSuperClass(leftComponent, rightComponent));
      }
      ClassInfo left = info(first);
      ClassInfo right = info(second);
      if (left == null || right == null || left.isInterface() || right.isInterface())
        return "java/lang/Object";
      String parent = left.superName;
      while (parent != null) {
        if (assignable(parent, second, new HashSet<String>())) return parent;
        ClassInfo next = info(parent);
        parent = next == null ? null : next.superName;
      }
      return "java/lang/Object";
    }

    private boolean assignable(String target, String source, Set<String> visited)
        throws IOException {
      if (target.equals(source)) return true;
      if ("java/lang/Object".equals(target) && !primitive(source)) return true;
      if (source.startsWith("[")) {
        if ("java/lang/Cloneable".equals(target) || "java/io/Serializable".equals(target))
          return true;
        if (!target.startsWith("[")) return false;
        String targetComponent = component(target);
        String sourceComponent = component(source);
        if (primitive(targetComponent) || primitive(sourceComponent))
          return targetComponent.equals(sourceComponent);
        return assignable(targetComponent, sourceComponent, visited);
      }
      if (target.startsWith("[") || primitive(source)) return false;
      if (!visited.add(source)) return false;
      ClassInfo currentInfo = info(source);
      if (currentInfo == null) return false;
      if (currentInfo.superName != null
          && assignable(target, currentInfo.superName, visited)) return true;
      for (String face : currentInfo.interfaces)
        if (assignable(target, face, visited)) return true;
      return false;
    }

    private ClassInfo info(String name) throws IOException {
      if (name.equals(current.name))
        return new ClassInfo(current.superName, current.interfaces,
            (current.access & Opcodes.ACC_INTERFACE) != 0);
      if (classes.containsKey(name)) return classes.get(name);
      InputStream stream = loader == null ? null : loader.getResourceAsStream(name + ".class");
      if (stream == null) stream = ClassLoader.getSystemResourceAsStream(name + ".class");
      ClassInfo result = null;
      if (stream != null) {
        try {
          ClassReader reader = new ClassReader(stream);
          result = new ClassInfo(reader.getSuperName(),
              java.util.Arrays.asList(reader.getInterfaces()),
              (reader.getAccess() & Opcodes.ACC_INTERFACE) != 0);
        } finally { stream.close(); }
      }
      classes.put(name, result);
      return result;
    }

    private static String component(String array) {
      String value = array.substring(1);
      return value.startsWith("L") ? value.substring(1, value.length() - 1) : value;
    }

    private static String descriptor(String name) {
      return name.startsWith("[") || primitive(name) ? name : "L" + name + ";";
    }

    private static boolean primitive(String name) {
      return name.length() == 1 && "ZCBSIFJD".contains(name);
    }

    private static final class ClassInfo {
      final String superName;
      final List<String> interfaces;
      final boolean isInterface;
      ClassInfo(String superName, List<String> interfaces, boolean isInterface) {
        this.superName = superName;
        this.interfaces = interfaces;
        this.isInterface = isInterface;
      }
      boolean isInterface() { return isInterface; }
    }
  }
}
