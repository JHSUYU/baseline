#!/usr/bin/env python3
"""JVM-free source/test admission check for the HBASE-37 gap receipt."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report = json.loads((HERE / "source-gap.json").read_text())
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    site = json.loads((HERE / "candidate-sites.json").read_text())
    require(receipt["status"] == "historical_minihbasecluster_only_gap_superseded" and
            receipt["case_id"] == "HBASE-37",
            "wrong stage receipt")
    for name in ("source-gap.json", "candidate-sites.json", "preflight.py"):
        require(sha(HERE / name) == receipt[name.replace(".", "_") + "_sha256"],
                f"SHA changed: {name}")
    require(report["kind"] == "source_backed_test_admission_gap" and
            report["terminal"] is False and report["jvm_started"] is False,
            "source gap status changed")
    for relative, expected in report["source_sha256"].items():
        require(sha(SOURCE / relative) == expected, f"source changed: {relative}")
    locations = report["source_locations"]
    target = (SOURCE / locations["MasterAddressTracker.java"]).read_text()
    util = (SOURCE / locations["ZKUtil.java"]).read_text()
    watcher = (SOURCE / locations["ZKWatcher.java"]).read_text()
    active = (SOURCE / locations["ActiveMasterManager.java"]).read_text()
    local_test = (SOURCE / locations["TestRSStatusPage.java"]).read_text()
    mini_test = (SOURCE / locations["TestGetInfoPort.java"]).read_text()
    info_test = (SOURCE / locations["TestInfoServers.java"]).read_text()
    jsp = (SOURCE / locations["backupMasterStatus.jsp"]).read_text()
    require("data = ZKUtil.getData(zkw, zkw.getZNodePaths().masterAddressZNode);" in target and
            "if (data == null) {\n      throw new IOException(\"Can't get master address from ZooKeeper; znode data == null\");" in target,
            "selected null guard changed")
    require("zkw.getRecoverableZooKeeper().getData(znode, null, null);" in util and
            "catch (KeeperException.NoNodeException e)" in util and
            "zkw.keeperException(e);" in util,
            "ZKUtil NoNode/null-return route changed")
    require("public void keeperException(KeeperException ke) throws KeeperException" in watcher and
            "throw ke;" in watcher, "other KeeperException rethrow changed")
    require("return MasterAddressTracker.getMasterInfoPort(watcher);" in active and
            "catch (Exception e)" in active, "caller catch changed")
    require("new LocalHBaseCluster(conf, 1)" in local_test and
            "int masterPort = master.getActiveMasterInfoPort();" in local_test,
            "observed JUnit path changed")
    require("testUtil.startMiniCluster();" in mini_test and
            ".getMasterAddressTracker()" in mini_test and
            ".getMasterInfoPort() > 0" in mini_test,
            "MiniHBaseCluster instance-getter comparison changed")
    require("UTIL.startMiniCluster();" in info_test and
            "master.getActiveMasterInfoPort();" in jsp and
            "if (!master.isActiveMaster())" in jsp,
            "MiniHBaseCluster page comparison changed")
    require(len(site["doors"]) == 1 and site["doors"][0] == {
        "clazz": "org.apache.hadoop.hbase.zookeeper.ZKUtil",
        "method": "getData",
        "descriptor": "(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B",
        "line": 343,
        "callee": "org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper#getData"
                  "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                  "Lorg/apache/zookeeper/data/Stat;)[B",
        "exception_class": "org.apache.zookeeper.KeeperException$NoNodeException",
    }, "candidate typed door changed")
    require(sha(HERE / "candidate-sites.json") == report["candidate_fault"]["site_file_sha256"],
            "candidate site not pinned by report")
    jar = Path(report["compiled_artifact"]["path"])
    require(sha(jar) == report["compiled_artifact"]["sha256"], "compiled jar changed")
    with zipfile.ZipFile(jar) as archive:
        cls = archive.read("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.class")
    require(hashlib.sha256(cls).hexdigest() ==
            report["compiled_artifact"]["target_class_sha256"],
            "compiled target class changed")
    prior = json.loads((ROOT / "data/mallory/calibration/HBASE-37/result.json").read_text())
    require(prior["status"] == "healthy_node_identity_missing" and
            prior["target_node_named"] is False and
            prior["trials"][0]["target_reached"] is True,
            "prior healthy evidence changed")
    print("PASS HBASE-37 static source/test gap preflight; JVM runs=0")


if __name__ == "__main__":
    main()
