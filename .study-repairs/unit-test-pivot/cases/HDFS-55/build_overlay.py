#!/usr/bin/env python3
"""Build isolated HDFS-55 target-check probes on the released Hadoop classes."""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
PIVOT = HERE.parents[1]
CONTROL = PIVOT / "known-bug-controls/HDFS-17899"
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar")
CLIENT_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
CLIENT_CLASS = "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class"
BALANCER_ROOT = "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/balancer"


def instrument_guard(source: str) -> str:
    original = """        if (encryptionKey == null ||
            encryptionKey.expiryDate < timer.now()) {"""
    replacement = """        boolean needsRefresh = encryptionKey == null ||
            encryptionKey.expiryDate < timer.now();
        Hdfs17899Probe.observeKeyCheck(this, encryptionKey, needsRefresh);
        if (needsRefresh) {"""
    if source.count(original) != 1:
        raise RuntimeError("Hadoop 3.4.3 KeyManager guard changed")
    return source.replace(original, replacement)


def build(mode: str) -> Path:
    spec = importlib.util.spec_from_file_location("hdfs17899_control_build",
                                                 CONTROL / "build_overlay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    overlay = BUILD / f"{mode}-overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"),
        "classpath", "--glob"], env=env, text=True).strip()
    cp = os.pathsep.join((str(overlay), hadoop_cp))
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(overlay),
                    str(HERE / "Hdfs17899Probe.java")], check=True)
    patcher = BUILD / "patcher"
    patcher.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JDK / "javac"), "-cp", str(ASM), "-d",
                    str(patcher), str(CONTROL / "PatchSaslClient.java")], check=True)
    original_class = BUILD / "input" / CLIENT_CLASS
    original_class.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CLIENT_JAR) as archive:
        original_class.write_bytes(archive.read(CLIENT_CLASS))
    subprocess.run([str(JDK / "java"), "-cp",
        os.pathsep.join((str(patcher), str(ASM))), "PatchSaslClient",
        str(original_class), str(overlay)], check=True)
    key_source = (SOURCE / BALANCER_ROOT / "KeyManager.java").read_text()
    if mode == "fixed":
        key_source = module.patch_key_manager(key_source)
    key_source = instrument_guard(key_source)
    generated = BUILD / f"{mode}-src" / "org/apache/hadoop/hdfs/server/balancer"
    generated.mkdir(parents=True, exist_ok=True)
    key_file = generated / "KeyManager.java"
    key_file.write_text(key_source)
    source_files = [str(key_file)]
    if mode == "fixed":
        dispatcher = generated / "Dispatcher.java"
        dispatcher.write_text(module.patch_dispatcher(
            (SOURCE / BALANCER_ROOT / "Dispatcher.java").read_text()))
        source_files.append(str(dispatcher))
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", cp,
                    "-d", str(overlay), *source_files], check=True)
    return overlay


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("original", "fixed"), required=True)
    print(build(parser.parse_args().mode))
