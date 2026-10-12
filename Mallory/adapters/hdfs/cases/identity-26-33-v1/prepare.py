"""Regenerate SHA-pinned source-only HDFS26/33 identity overlays.

No Hadoop or adapter source is modified, and no JVM is started here.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
HADOOP = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
SRC = "Mallory/adapters/hdfs/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/"
TRANSFORMER = SRC + "HdfsMiniClusterTransformer.java"
HOOKS = SRC + "HdfsHooks.java"
PIN = {
    TRANSFORMER: "98886c4ff83d3a9dd766f43752f3e2bc2c0ecfbd69c8e0668342abe57bd41441",
    HOOKS: "7a8d2b1171b7e48701e9493fbb3a238ae60902e3eddf62e16e2880fdc9f31458",
}
BASE = ROOT / "Mallory/adapters/hdfs/cases/pending-triage-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def replace_once(data: str, old: str, new: str) -> str:
    assert data.count(old) == 1, (old[:80], data.count(old))
    return data.replace(old, new, 1)


def write_patch(rel: str, before: str, after: str, name: str) -> dict:
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=4))
    assert diff
    path = OUT / name
    path.write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
    return artifact(path)


def prepare() -> None:
    for rel, digest in PIN.items():
        assert sha(ROOT / rel) == digest, f"source drift: {rel}"
    t_before = (ROOT / TRANSFORMER).read_text()
    h_before = (ROOT / HOOKS).read_text()

    # The exact MiniDFSCluster call has [args, conf, resources] on the stack.
    # Spill and restore those reference arguments to name the concrete config
    # before DataNode's constructor starts its block-pool actor threads.
    t_after = replace_once(
        t_before,
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/MiniDFSCluster\")\n"
        "          && method.name.equals(\"startDataNodes\")) {\n"
        "        for (AbstractInsnNode instruction : method.instructions.toArray()) {\n"
        "          if (!(instruction instanceof MethodInsnNode)) continue;\n"
        "          MethodInsnNode call = (MethodInsnNode) instruction;\n"
        "          if (!call.owner.equals(\"org/apache/hadoop/hdfs/server/datanode/DataNode\")\n"
        "              || !call.name.equals(\"runDatanodeDaemon\") || !call.desc.equals(\"()V\")) continue;\n",
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/MiniDFSCluster\")\n"
        "          && method.name.equals(\"startDataNodes\")) {\n"
        "        int constructionSites = 0;\n"
        "        int daemonSites = 0;\n"
        "        for (AbstractInsnNode instruction : method.instructions.toArray()) {\n"
        "          if (!(instruction instanceof MethodInsnNode)) continue;\n"
        "          MethodInsnNode call = (MethodInsnNode) instruction;\n"
        "          if (call.getOpcode() == Opcodes.INVOKESTATIC\n"
        "              && call.owner.equals(\"org/apache/hadoop/hdfs/server/datanode/DataNode\")\n"
        "              && call.name.equals(\"instantiateDataNode\")\n"
        "              && call.desc.equals(\"([Ljava/lang/String;Lorg/apache/hadoop/conf/Configuration;\"\n"
        "                  + \"Lorg/apache/hadoop/hdfs/server/datanode/SecureDataNodeStarter$SecureResources;)\"\n"
        "                  + \"Lorg/apache/hadoop/hdfs/server/datanode/DataNode;\")) {\n"
        "            int args = method.maxLocals;\n"
        "            int config = args + 1;\n"
        "            int resources = args + 2;\n"
        "            method.maxLocals += 3;\n"
        "            InsnList hook = new InsnList();\n"
        "            hook.add(new VarInsnNode(Opcodes.ASTORE, resources));\n"
        "            hook.add(new VarInsnNode(Opcodes.ASTORE, config));\n"
        "            hook.add(new VarInsnNode(Opcodes.ASTORE, args));\n"
        "            hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n"
        "            hook.add(new VarInsnNode(Opcodes.ALOAD, config));\n"
        "            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,\n"
        "                \"dataNodeConstructionConfigured\",\n"
        "                \"(Ljava/lang/Object;Ljava/lang/Object;)V\", false));\n"
        "            hook.add(new VarInsnNode(Opcodes.ALOAD, args));\n"
        "            hook.add(new VarInsnNode(Opcodes.ALOAD, config));\n"
        "            hook.add(new VarInsnNode(Opcodes.ALOAD, resources));\n"
        "            method.instructions.insertBefore(instruction, hook);\n"
        "            constructionSites++;\n"
        "            changed = true;\n"
        "          }\n"
        "          if (!call.owner.equals(\"org/apache/hadoop/hdfs/server/datanode/DataNode\")\n"
        "              || !call.name.equals(\"runDatanodeDaemon\") || !call.desc.equals(\"()V\")) continue;\n")
    t_after = replace_once(
        t_after,
        "              || !call.name.equals(\"runDatanodeDaemon\") || !call.desc.equals(\"()V\")) continue;\n"
        "          InsnList hook = new InsnList();\n",
        "              || !call.name.equals(\"runDatanodeDaemon\") || !call.desc.equals(\"()V\")) continue;\n"
        "          daemonSites++;\n"
        "          InsnList hook = new InsnList();\n")
    t_after = replace_once(
        t_after,
        "          changed = true;\n"
        "        }\n"
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/MiniDFSCluster\")\n"
        "          && (method.name.equals(\"createNameNode\")\n",
        "          changed = true;\n"
        "        }\n"
        "        if (constructionSites != daemonSites || constructionSites > 1)\n"
        "          throw new IllegalStateException(\"HDFS DataNode construction/daemon hook mismatch\");\n"
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/MiniDFSCluster\")\n"
        "          && (method.name.equals(\"createNameNode\")\n")
    t_after = replace_once(
        t_after,
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataStorage\")\n"
        "          && method.name.equals(\"getBlockPoolSliceStorage\")) {\n",
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataNode\")\n"
        "          && method.name.equals(\"startDataNode\")) {\n"
        "        int refreshes = 0;\n"
        "        for (AbstractInsnNode instruction : method.instructions.toArray()) {\n"
        "          if (!(instruction instanceof MethodInsnNode)) continue;\n"
        "          MethodInsnNode call = (MethodInsnNode) instruction;\n"
        "          if (!call.owner.equals(\"org/apache/hadoop/hdfs/server/datanode/BlockPoolManager\")\n"
        "              || !call.name.equals(\"refreshNamenodes\")) continue;\n"
        "          InsnList hook = new InsnList();\n"
        "          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n"
        "          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,\n"
        "              \"dataNodeConstructionReady\", \"(Ljava/lang/Object;)V\", false));\n"
        "          method.instructions.insertBefore(instruction, hook);\n"
        "          refreshes++;\n"
        "          changed = true;\n"
        "        }\n"
        "        if (refreshes != 1)\n"
        "          throw new IllegalStateException(\"Expected one HDFS block-pool refresh\");\n"
        "      } else if (name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataStorage\")\n"
        "          && method.name.equals(\"getBlockPoolSliceStorage\")) {\n")
    t_after = replace_once(
        t_after,
        "        || name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataStorage\")\n",
        "        || name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataNode\")\n"
        "        || name.equals(\"org/apache/hadoop/hdfs/server/datanode/DataStorage\")\n")

    h_after = replace_once(
        h_before,
        "  private static final Map<Object, Integer> DN_OBJECT_EPOCHS = new IdentityHashMap<Object, Integer>();\n",
        "  private static final Map<Object, Integer> DN_OBJECT_EPOCHS = new IdentityHashMap<Object, Integer>();\n"
        "  private static final Map<Object, PendingDataNode> PENDING_DN_CONFIGS =\n"
        "      new IdentityHashMap<Object, PendingDataNode>();\n"
        "\n"
        "  private static final class PendingDataNode {\n"
        "    final Object cluster;\n"
        "    final int index;\n"
        "    final String node;\n"
        "    final int epoch;\n"
        "    PendingDataNode(Object cluster, int index, String node, int epoch) {\n"
        "      this.cluster = cluster;\n"
        "      this.index = index;\n"
        "      this.node = node;\n"
        "      this.epoch = epoch;\n"
        "    }\n"
        "  }\n")
    h_after = replace_once(
        h_after,
        "  /** Register a DN before its daemon starts; Builder.build returns too late for startup checks. */\n"
        "  public static synchronized void dataNodeStarting(Object dn, Object cluster) {\n",
        "  /** Stage the concrete MiniDFSCluster config before its DN constructor starts actors. */\n"
        "  public static synchronized void dataNodeConstructionConfigured(Object cluster, Object conf) {\n"
        "    if (cluster == null || conf == null) return;\n"
        "    try {\n"
        "      Object existing = field(cluster, \"dataNodes\");\n"
        "      if (!(existing instanceof List<?>))\n"
        "        throw new IllegalStateException(\"MiniDFSCluster.dataNodes is not a list\");\n"
        "      int index = ((List<?>) existing).size();\n"
        "      String prefix = CLUSTER_NAMES.get(cluster);\n"
        "      if (prefix == null) {\n"
        "        prefix = \"hdfs-cluster-\" + CLUSTERS.incrementAndGet();\n"
        "        CLUSTER_NAMES.put(cluster, prefix);\n"
        "      }\n"
        "      Map<Integer, Integer> epochs = DN_EPOCHS.get(cluster);\n"
        "      Integer previous = epochs == null ? null : epochs.get(index);\n"
        "      int epoch = previous == null ? 0 : previous + 1;\n"
        "      PendingDataNode pending = PENDING_DN_CONFIGS.get(conf);\n"
        "      if (pending != null) {\n"
        "        if (pending.cluster != cluster || pending.index != index)\n"
        "          throw new IllegalStateException(\"HDFS DataNode config reused for another actor\");\n"
        "        return; // A constructor retry is still the same logical startup.\n"
        "      }\n"
        "      PENDING_DN_CONFIGS.put(conf, new PendingDataNode(\n"
        "          cluster, index, prefix + \"/dn\" + index, epoch));\n"
        "    } catch (ReflectiveOperationException failure) {\n"
        "      throw new IllegalStateException(\"HDFS DataNode construction config unavailable\", failure);\n"
        "    }\n"
        "  }\n"
        "\n"
        "  /** Register storage before BlockPoolManager.refreshNamenodes starts BP actors. */\n"
        "  public static synchronized void dataNodeConstructionReady(Object dn) {\n"
        "    if (dn == null) return;\n"
        "    try {\n"
        "      PendingDataNode pending = PENDING_DN_CONFIGS.get(invoke(dn, \"getConf\"));\n"
        "      if (pending == null) return; // Non-MiniDFSCluster DataNode.\n"
        "      Probe.registerNode(dn, pending.node, pending.epoch);\n"
        "      register(field(dn, \"storage\"), pending.node, pending.epoch);\n"
        "      register(field(dn, \"blockPoolManager\"), pending.node, pending.epoch);\n"
        "      DN_OBJECT_EPOCHS.put(dn, pending.epoch);\n"
        "    } catch (ReflectiveOperationException failure) {\n"
        "      throw new IllegalStateException(\"HDFS early DataNode binding failed\", failure);\n"
        "    }\n"
        "  }\n"
        "\n"
        "  /** Register a DN before its daemon starts; Builder.build returns too late for startup checks. */\n"
        "  public static synchronized void dataNodeStarting(Object dn, Object cluster) {\n")
    h_after = replace_once(
        h_after,
        "      int epoch = epochs.containsKey(index) ? epochs.get(index) + 1 : 0;\n"
        "      epochs.put(index, epoch);\n"
        "      DN_OBJECT_EPOCHS.put(dn, epoch);\n"
        "      Probe.registerNode(dn, node, epoch);\n",
        "      PendingDataNode pending = PENDING_DN_CONFIGS.remove(invoke(dn, \"getConf\"));\n"
        "      if (pending != null && (pending.cluster != cluster\n"
        "          || pending.index != index || !pending.node.equals(node)))\n"
        "        throw new IllegalStateException(\"HDFS DataNode early/late actor mismatch\");\n"
        "      int epoch = pending == null\n"
        "          ? (epochs.containsKey(index) ? epochs.get(index) + 1 : 0)\n"
        "          : pending.epoch;\n"
        "      epochs.put(index, epoch);\n"
        "      DN_OBJECT_EPOCHS.put(dn, epoch);\n"
        "      Probe.registerNode(dn, node, epoch);\n")

    patches = {
        "transformer": write_patch(TRANSFORMER, t_before, t_after,
                                   "hdfs-transformer-early-dn.patch"),
        "hooks": write_patch(HOOKS, h_before, h_after,
                             "hdfs-hooks-early-dn.patch"),
    }
    configurations = {}
    for case in ("HDFS-26", "HDFS-33"):
        base = BASE / f"{case}-healthy-only.json"
        config = json.loads(base.read_text())
        additions = [
            "org.apache.hadoop.hdfs.MiniDFSCluster",
            "org.apache.hadoop.hdfs.MiniDFSCluster$Builder",
            "org.apache.hadoop.hdfs.server.datanode.DataNode",
            "org.apache.hadoop.hdfs.server.datanode.DataStorage",
        ]
        if case == "HDFS-26":
            additions.append("org.apache.hadoop.hdfs.server.datanode.BPServiceActor")
        config["agent_include"] = list(dict.fromkeys(config["agent_include"] + additions))
        config["agent_properties"]["adapter.jar"] = "__ISOLATED_ADAPTER_JAR__"
        config["cwd"] = "__ISOLATED_HDFS_SOURCE_ROOT__"
        config["source_equivalent_root"] = "__ISOLATED_HDFS_SOURCE_ROOT__"
        config["runtime_artifacts"] = [x for x in config["runtime_artifacts"]
                                       if "hdfs-adapter-v10" not in x["path"]]
        config["runtime_artifacts"].append({
            "path": "__ISOLATED_ADAPTER_JAR__", "sha256": "__ADAPTER_SHA256__"})
        config["mapping"].pop("adapter_v10_sha256", None)
        config["mapping"]["adapter_identity_v1_sha256"] = "__ADAPTER_SHA256__"
        config["mapping"]["source_root"] = "__ISOLATED_HDFS_SOURCE_ROOT__"
        config["mapping"]["compiled_artifact"] = (
            "__ISOLATED_HDFS_SOURCE_ROOT__/hadoop-hdfs-project/hadoop-hdfs/target/classes")
        config["mapping"]["calibration_revision"] = "identity_26_33_v1_healthy_only"
        config["mapping"]["status"] = "template_unbuilt_no_runtime_admission"
        config["mapping"]["node_identity_binding_configured"] = True
        config["mapping"]["node_identity_binding_verified"] = False
        config["healthy_gate"]["require_named_target_node"] = True
        config["calibration_only"] = True
        config["auto_promote_if_healthy"] = False
        config["budget"] = {
            "trials": 1, "seconds": 300, "max_faults_per_trial": 0,
            "trial_timeout_seconds": 240,
            "trial_timeout_basis": "one_isolated_healthy_run_only",
        }
        path = OUT / f"{case}-healthy-only.template.json"
        path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        configurations[case] = {"base": artifact(base), "template": artifact(path)}

    source = [
        ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/MiniDFSCluster.java", "1808-1850"),
        ("hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java", "531-595,1880-1960,3238-3261"),
        ("hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", "230-266,320-346"),
        ("hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java", "360-383,603-629"),
        ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollback.java", "139-203"),
        ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDataNodeHotSwapVolumes.java", "403-425"),
    ]
    prior = {}
    for case in ("HDFS-26", "HDFS-33"):
        p = ROOT / "data/mallory/calibration" / case / "result.json"
        result = json.loads(p.read_text())
        assert result["trials"][0]["target_reached"]
        assert not result["target_node_named"]
        prior[case] = {
            "result": artifact(p), "target_identity_gaps": result["target_identity_gaps"],
            "target_class_sha256": result["runtime_attestation"]["observed_target_class_sha256"],
        }
    receipt = {
        "schema_version": 1,
        "status": "source_only_unbuilt_no_jvm",
        "no_jvm_or_fault_trial_launched": True,
        "pristine_adapter": {rel: artifact(ROOT / rel) for rel in PIN},
        "patches": patches,
        "healthy_templates": configurations,
        "prior_healthy": prior,
        "source_refs": [{**artifact(HADOOP / path), "lines": lines}
                        for path, lines in source],
        "identity_claim": "Configuration object used by one MiniDFSCluster DataNode startup "
                          "is staged before DataNode construction; the same object's "
                          "DataNode and DataStorage are registered before block-pool "
                          "threads start. Later registration must agree on cluster index/epoch.",
        "healthy_gate": {
            "junit_tests": 1, "junit_failures": 0, "junit_errors": 0,
            "exact_nonthrowing_target_on_named_dn": True,
            "no_unknown_target_identity_gap": True,
            "root_free_event_time_path": True,
        },
        "admission": "Build patched adapter in a fresh isolated checkout and substitute "
                     "template placeholders with SHA-pinned built artifacts. Dispatch "
                     "may admit one healthy run per case; no fault trial or full fuzz.",
    }
    (OUT / "preflight.json").write_text(json.dumps(receipt, indent=2,
                                                   sort_keys=True) + "\n")


if __name__ == "__main__":
    prepare()
