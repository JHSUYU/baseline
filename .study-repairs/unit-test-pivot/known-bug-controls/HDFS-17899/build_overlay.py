#!/usr/bin/env python3
"""Case-local SASL hook and optional minimal HDFS-17899 Balancer fix control."""

import argparse
import os
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar")
CLIENT_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
CLIENT_CLASS = "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class"
BALANCER_ROOT = "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/balancer"


def patch_key_manager(source):
    old = """  @Override
  public void close() {
"""
    new = """  public synchronized void clearDataEncryptionKey() {
    encryptionKey = null;
    Hdfs17899Probe.markKeyCleared();
  }

  public void updateBlockKeys() throws IOException {
    if (isBlockTokenEnabled) {
      blockTokenSecretManager.addKeys(namenode.getBlockKeys());
    }
  }

  @Override
  public void close() {
"""
    if source.count(old) != 1:
        raise RuntimeError("KeyManager source changed")
    return source.replace(old, new)


def patch_dispatcher(source):
    old_import = "import org.apache.hadoop.hdfs.protocol.datatransfer.IOStreamPair;"
    source = source.replace(old_import, old_import + "\nimport org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;")
    begin = source.index("    private void dispatch() {")
    end = source.index("    /** Send a reportedBlock replace request", begin)
    section = source[begin:end]
    start = section.index("        sock.connect(\n")
    finish = section.index("        out = new DataOutputStream", start)
    replacement = """        ExtendedBlock eb = new ExtendedBlock(nnc.getBlockpoolID(),
            reportedBlock.getBlock());
        final KeyManager km = nnc.getKeyManager();
        Token<BlockTokenIdentifier> accessToken;
        OutputStream unbufOut;
        InputStream unbufIn;
        int encryptionKeyRetryCount = 0;
        while (true) {
          try {
            sock.connect(NetUtils.createSocketAddr(target.getDatanodeInfo()
                .getXferAddr(Dispatcher.this.connectToDnViaHostname)),
                HdfsConstants.READ_TIMEOUT);
            sock.setSoTimeout(HdfsConstants.READ_TIMEOUT * 5);
            sock.setKeepAlive(true);
            unbufOut = sock.getOutputStream();
            unbufIn = sock.getInputStream();
            accessToken = km.getAccessToken(eb,
                new StorageType[]{target.storageType}, new String[0]);
            IOStreamPair saslStreams = saslClient.socketSend(sock, unbufOut,
                unbufIn, km, accessToken, target.getDatanodeInfo());
            unbufOut = saslStreams.out;
            unbufIn = saslStreams.in;
            break;
          } catch (InvalidEncryptionKeyException e) {
            IOUtils.closeSocket(sock);
            if (++encryptionKeyRetryCount > 1) throw e;
            km.updateBlockKeys();
            km.clearDataEncryptionKey();
            sock = new Socket();
          }
        }
"""
    section = section[:start] + replacement + section[finish:]
    return source[:begin] + section + source[end:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("original", "fixed"), required=True)
    args = parser.parse_args()
    mode = args.mode
    overlay = BUILD / (mode + "-overlay")
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
        str(patcher), str(HERE / "PatchSaslClient.java")], check=True)
    original_class = BUILD / "input" / CLIENT_CLASS
    original_class.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CLIENT_JAR) as archive:
        original_class.write_bytes(archive.read(CLIENT_CLASS))
    subprocess.run([str(JDK / "java"), "-cp",
        os.pathsep.join((str(patcher), str(ASM))), "PatchSaslClient",
        str(original_class), str(overlay)], check=True)
    if mode == "fixed":
        patches = {
            "KeyManager.java": patch_key_manager,
            "Dispatcher.java": patch_dispatcher,
        }
        inputs = []
        for filename, transform in patches.items():
            source = SOURCE / BALANCER_ROOT / filename
            output = BUILD / "patched-src" / "org/apache/hadoop/hdfs/server/balancer" / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(transform(source.read_text()))
            inputs.append(str(output))
        subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", cp,
            "-d", str(overlay), *inputs], check=True)
    print(str(overlay.resolve()))


if __name__ == "__main__":
    main()
