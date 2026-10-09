#!/usr/bin/env python3
"""Read-only HDFS-33 source, bytecode, and archived-seed audit."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
HDFS = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs")
CLASSES = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs/target/classes")
PARSER = HERE.parent / "hdfs29-replica-recovery-admission-v1/verify_bytecode.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    selector = json.loads((HERE / "selector.json").read_text())
    for item in receipt["artifacts"]:
        path = Path(item["path"])
        assert path.is_file() and sha(path) == item["sha256"], path
    head = subprocess.run(["git", "-C", str(CLASSES.parents[3]), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert head == receipt["source_commit"] == selector["source_commit"]
    assert selector["case_id"] == "HDFS-33"
    assert selector["selected_check_sites"] == [
        "org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder#build()V@259:branch:4",
        "org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder#build()V@259:branch:5"]
    assert selector["selected_throw"].endswith("@259:throw:1")
    assert not selector["healthy_only_config_staged"]
    assert not selector["live_jvm_started"] and not selector["fault_or_full_admitted"]

    spec = importlib.util.spec_from_file_location("hdfs29_class_reader", PARSER)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    _, methods, pool = parser.parse_class(
        CLASSES / "org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder.class")
    build = next(m for m in methods if m["name"] == "build" and m["descriptor"] == "()V")
    calls = parser.calls(build, pool)
    assert any(c["line"] == 258 and c["method"] == "get" and c["owner"] == "java/util/Map"
               for c in calls)
    assert any(c["line"] == 259 and c["owner"] == "java/lang/AssertionError"
               for c in calls)
    check_pc = next(pc for pc, line in build["lines"] if line == 259)
    # $assertionsDisabled; ifne; aload bpStorage; ifnonnull; new AssertionError.
    assert build["code"][check_pc] == 0xB2
    assert build["code"][check_pc + 3] == 0x9A
    assert build["code"][check_pc + 8] == 0xC7

    storage = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java").read_text()
    prepare = storage[storage.index("public VolumeBuilder prepareVolume("):
                      storage.index("static int getParallelVolumeLoadThreadsNum(")]
    assert prepare.index("loadStorageDirectory(") < prepare.index(
        "new VolumeBuilder(this, sd)") < prepare.index("location.makeBlockPoolDir(")
    assert prepare.index("location.makeBlockPoolDir(") < prepare.index(
        "getBlockPoolSliceStorage(nsInfo)")
    assert prepare.index("getBlockPoolSliceStorage(nsInfo)") < prepare.index(
        "loadBpStorageDirectories(") < prepare.index("builder.addBpStorageDirectories(")
    assert prepare.index("builder.addBpStorageDirectories(") < prepare.index("return builder;")
    lookup = storage[storage.index("synchronized BlockPoolSliceStorage getBlockPoolSliceStorage("):
                     storage.index("synchronized void removeBlockPoolStorage(")]
    assert lookup.index("bpStorageMap.get(bpid)") < lookup.index("bpStorageMap.put(bpid, bpStorage)")
    assert "bpStorageMap.remove(bpId)" in storage
    assert "assert bpStorage != null;" in storage[storage.index("public void build()"):
                                                   storage.index("private StorageDirectory loadStorageDirectory(")]

    dataset = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl.java").read_text()
    add = dataset[dataset.index("public void addVolume(final StorageLocation location,"):
                  dataset.index("/**\n   * Removes a set of volumes", dataset.index("public void addVolume(final StorageLocation location,"))]
    assert add.index("dataStorage.prepareVolume(datanode, location, nsInfos)") < add.index(
        "catch (IOException e)") < add.index("throw e;") < add.index("builder.build();")
    assert add.index("exceptions.add(e);") < add.index(
        "throw MultipleIOException.createIOException(exceptions);") < add.index("builder.build();")
    dn = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java").read_text()
    assert "storage.removeBlockPoolStorage(bpId)" in dn
    assert "return e;" in dn[dn.index("private void refreshVolumes("):
                             dn.index("private void removeVolumes(")]
    actor = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java").read_text()
    offer = actor[actor.index("void offerService()") : actor.index("} // offerService")]
    assert "catch (IOException e)" in offer and "sleepAfterException();" in offer
    bpos = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java").read_text()
    assert "if (bpServices.isEmpty())" in bpos and "dn.shutdownBlockPool(this);" in bpos
    test = (HDFS / "src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDataNodeHotSwapVolumes.java").read_text()
    chosen = test[test.index("void testAddOneNewVolume()") : test.index("void testReAddVolumeWithBlocks()")]
    assert "startDFSCluster(1, 1)" in chosen and "addVolumes(1)" in chosen

    archived = json.loads(Path(receipt["archive_result"]).read_text())
    feedback = archived["feedback"]
    assert archived["return_code"] == 0 and not archived["timed_out"]
    assert feedback["target_reached"] and not feedback["target_threw"]
    assert len(feedback["target_instances"]) == 1
    assert feedback["target_instances"][0]["node"] == "unknown"
    assert len(feedback["target_identity_gaps"]) == 2
    assert "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0" in Path(
        receipt["archive_stdout"]).read_text()
    with ZipFile(receipt["adapter_jar"]) as jar:
        transformer = jar.read("edu/uva/liftlab/mallory/adapters/hdfs/HdfsMiniClusterTransformer.class")
    assert b"volumeBuilderEnter" in transformer
    print("HDFS-33 offline source, bytecode, archived reach, and SHA audit: PASS")


if __name__ == "__main__":
    main()
