"""Create SHA-pinned proposed patches and a source-only HDFS-48 pilot receipt.

This script reads code and old trials. It never patches a live source tree or
starts a JVM. Dispatch must allocate an isolated worktree before any pilot.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
HADOOP = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
TEST_REL = ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/"
            "hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java")
ADAPTER_REL = ("Mallory/adapters/hdfs/src/main/java/edu/uva/liftlab/mallory/"
               "adapters/hdfs/HdfsMiniClusterTransformer.java")
HOOKS_REL = ("Mallory/adapters/hdfs/src/main/java/edu/uva/liftlab/mallory/"
             "adapters/hdfs/HdfsHooks.java")
TEST_SHA = "58c382b17db4855ebc3e105feb72232c086126e3ecb8a71dc8919d5967c8af00"
ADAPTER_SHA = "98886c4ff83d3a9dd766f43752f3e2bc2c0ecfbd69c8e0668342abe57bd41441"
HOOKS_SHA = "7a8d2b1171b7e48701e9493fbb3a238ae60902e3eddf62e16e2880fdc9f31458"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def patch(rel: str, before: str, after: str, name: str) -> dict:
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3))
    assert diff
    path = OUT / name
    path.write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
    return artifact(path)


def one_replace(before: str, old: str, new: str) -> str:
    assert before.count(old) == 1, f"expected one source match; got {before.count(old)}"
    return before.replace(old, new, 1)


def prepare() -> None:
    test = HADOOP / TEST_REL
    adapter = ROOT / ADAPTER_REL
    hooks = ROOT / HOOKS_REL
    assert sha(test) == TEST_SHA
    assert sha(adapter) == ADAPTER_SHA
    assert sha(hooks) == HOOKS_SHA
    test_before = test.read_text()
    test_after = one_replace(
        test_before,
        "  @Before\n  public void setUp() throws Exception {\n"
        "    conf.setLong(DFSConfigKeys.DFS_BLOCK_SIZE_KEY, BLOCKSIZE);\n",
        "  @Before\n  public void setUp() throws Exception {\n"
        "    // HDFS-48 Mallory pilot: retry one local pre-send IOException.\n"
        "    conf.setBoolean(\"dfs.client.retry.policy.enabled\", true);\n"
        "    conf.set(\"dfs.client.retry.policy.spec\", \"20,1\");\n"
        "    conf.setLong(DFSConfigKeys.DFS_BLOCK_SIZE_KEY, BLOCKSIZE);\n")
    adapter_before = adapter.read_text()
    adapter_after = one_replace(
        adapter_before,
        "          && method.desc.startsWith(\"(Lorg/apache/hadoop/ipc/Client$Call;)\")) {\n"
        "        InsnList hook = new InsnList();\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n",
        "          && method.desc.startsWith(\"(Lorg/apache/hadoop/ipc/Client$Call;)\")) {\n"
        "        InsnList hook = new InsnList();\n"
        "        // Observe the protobuf method before rpcSend. A pre-send fault\n"
        "        // must not create a SEND edge for a request never queued.\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 1));\n"
        "        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, \"rpcBeforeSend\",\n"
        "            \"(Ljava/lang/Object;)V\", false));\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n")
    hooks_before = hooks.read_text()
    hooks_after = one_replace(
        hooks_before,
        "  public static void rpcSend(Object connection, Object call) {\n",
        "  /** Method-aware client RPC door, before serialization and queueing. */\n"
        "  public static void rpcBeforeSend(Object call) {\n"
        "    final Object request;\n"
        "    try {\n"
        "      request = field(call, \"rpcRequest\");\n"
        "    } catch (ReflectiveOperationException failure) {\n"
        "      throw new IllegalStateException(\"HDFS client RPC request unavailable\", failure);\n"
        "    }\n"
        "    if (request == null || !request.getClass().getName().equals(\n"
        "        \"org.apache.hadoop.ipc.ProtobufRpcEngine2$RpcProtobufRequest\")) return;\n"
        "    String rpcName = request.toString();\n"
        "    String protocol = \"org.apache.hadoop.hdfs.protocol.ClientProtocol.\";\n"
        "    if (!rpcName.startsWith(protocol)) return;\n"
        "    String method = rpcName.substring(protocol.length());\n"
        "    if (method.isEmpty())\n"
        "      throw new IllegalStateException(\"HDFS client RPC method unavailable\");\n"
        "    Probe.beforeDoor(\"hdfs:client-send-rpc-request:\" + method,\n"
        "        \"java.io.IOException\");\n"
        "  }\n\n"
        "  public static void rpcSend(Object connection, Object call) {\n")
    patches = {
        "hadoop_test": patch(TEST_REL, test_before, test_after,
                             "hadoop-test-retry.patch"),
        "hdfs_adapter": patch(ADAPTER_REL, adapter_before, adapter_after,
                              "hdfs-adapter-client-door.patch"),
        "hdfs_hooks": patch(HOOKS_REL, hooks_before, hooks_after,
                            "hdfs-hooks-client-door.patch"),
    }

    decision_path = ROOT / "Mallory/cases/revisions/HDFS-48-nn-v14.pilot-decision-v2.json"
    decision = json.loads(decision_path.read_text())
    trial_root = ROOT / "data/mallory/pilots_v14/HDFS-48-nn-only/trials"
    trials = []
    for result_path in sorted(trial_root.glob("r*/result.json")):
        d = json.loads(result_path.read_text())
        if not d.get("plan"):
            continue
        assert len(d["plan"]) == 1
        stdout = result_path.parent / "stdout.log"
        failures = re.findall(r"TestRenameWithSnapshots\.testRenameUndo_1:(\d+)",
                              stdout.read_text(errors="replace"))
        trials.append({
            "trial": result_path.parent.name,
            "result": artifact(result_path),
            "stdout": artifact(stdout),
            "fault_site": d["plan"][0]["point"]["site"],
            "fault_ordinal": d["plan"][0]["point"]["door_ordinal"],
            "fault_effective": d["feedback"]["all_faults_effective"],
            "postfault_target_reached": d["feedback"]["target_reached"],
            "junit_failure_line": int(failures[-1]) if failures else None,
        })
    assert len(trials) == 10
    assert all(x["fault_effective"] and not x["postfault_target_reached"]
               for x in trials)

    source = [
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/"
         "hadoop/hdfs/server/namenode/INodeDirectory.java", "351-359,381-399"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/"
         "hadoop/hdfs/server/namenode/FSDirRenameOp.java", "47-65,489-523,629-686"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/"
         "hadoop/hdfs/server/namenode/NameNodeRpcServer.java", "1047-1073"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/"
         "hadoop/hdfs/server/namenode/FSNamesystem.java", "3301-3330"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/"
         "apache/hadoop/hdfs/NameNodeProxiesClient.java", "122-140,339-388"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/"
         "apache/hadoop/hdfs/client/HdfsClientConfigKeys.java", "355-362"),
        (HADOOP / "hadoop-common-project/hadoop-common/src/main/java/org/"
         "apache/hadoop/io/retry/RetryUtils.java", "59-122"),
        (HADOOP / "hadoop-common-project/hadoop-common/src/main/java/org/"
         "apache/hadoop/ipc/Client.java", "1159-1190,1452-1495"),
        (HADOOP / "hadoop-common-project/hadoop-common/src/main/java/org/"
         "apache/hadoop/ipc/ProtobufRpcEngine2.java", "180-201,649-681"),
        (HADOOP / "hadoop-common-project/hadoop-common/src/main/java/org/"
         "apache/hadoop/ipc/internal/ShadedProtobufHelper.java", "48-65,152-166"),
        (HADOOP / "hadoop-common-project/hadoop-common/src/main/java/org/"
         "apache/hadoop/io/retry/RetryPolicies.java", "387-429,483-518"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/"
         "apache/hadoop/hdfs/protocol/HdfsConstants.java", "145-149"),
        (HADOOP / "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/"
         "apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.java", "543-551"),
    ]
    receipt = {
        "schema_version": 1,
        "case_id": "HDFS-48",
        "status": "source_backed_hypothesis_unverified_no_jvm",
        "no_jvm_or_fault_trial_launched": True,
        "original_junit": "org.apache.hadoop.hdfs.server.namenode.snapshot."
                          "TestRenameWithSnapshots#testRenameUndo_1",
        "pristine_test": artifact(test),
        "pristine_adapter": artifact(adapter),
        "pristine_hooks": artifact(hooks),
        "patches": patches,
        "prior_decision": artifact(decision_path),
        "prior_healthy_result": artifact(ROOT / "data/mallory/calibration_v14_node0/"
                                         "HDFS-48/trials/r0000/result.json"),
        "prior_nn_pilot_effective_trials": trials,
        "source_refs": [{**artifact(p), "lines": lines} for p, lines in source],
        "source_reasoning": [
            "NN RpcCall entry IOException becomes RemoteException(IOException). "
            "The existing JUnit aborts at setup/rename and no postfault NN target appears.",
            "The target is reached inside FSDirRenameOp.RenameOperation after "
            "RPC ingress. Edit-log rename/sync is after the in-memory target.",
            "The non-HA ClientProtocol proxy has a retry wrapper, but its "
            "default retry policy is disabled. RetryUtils retries a local "
            "IOException when explicitly enabled, while RemoteException "
            "apart from SafeModeException is not retried.",
            "ClientNamenodeProtocolTranslatorPB.rename converts the local "
            "ServiceException cause back to IOException via "
            "ShadedProtobufHelper.ipc. The 20,1 retry spec permits one retry.",
            "A method-aware beforeDoor at Client.Connection.sendRpcRequest "
            "before rpcSend selects ClientProtocol.rename and throws before "
            "queueing. A single retry could then send the rename and reach "
            "NN replaceChild after the fault. This remains unverified.",
        ],
        "healthy_gate": {
            "junit_tests": 1, "junit_failures": 0, "junit_errors": 0,
            "exact_named_nn_target": True, "selected_throw_absent": True,
            "named_client_actor": "hdfs-client",
            "root_free_event_time_path_from_retry_send": True,
        },
        "required_agent_include_additions": [
            "org.apache.hadoop.ipc.Client$Connection",
            "org.apache.hadoop.ipc.Client",
            "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots",
        ],
        "pilot_bounds": {
            "max_fault_trials": 6, "max_elapsed_seconds": 480,
            "max_faults_per_sequence": 1,
            "inject_site": "hdfs:client-send-rpc-request:rename",
            "fault_exception": "java.io.IOException",
            "only_client_rename_request": True,
            "required_evidence": ["effective_fault_before_send",
                                  "fault_site_is_ClientProtocol_rename",
                                  "client_retry_send_and_nn_receive_same_logical_rpc",
                                  "postfault_exact_named_nn_target",
                                  "passing_junit_or_source_reviewed_failure"],
        },
        "admission": "Isolated test/adapter build only. Verify patches against pinned "
                     "source, run one patched healthy JUnit, then at most six "
                     "targeted single-fault pilot trials. Do not promote to "
                     "full fuzz until event-time causal audit passes.",
    }
    (OUT / "preflight.json").write_text(json.dumps(receipt, indent=2,
                                                   sort_keys=True) + "\n")


if __name__ == "__main__":
    prepare()
