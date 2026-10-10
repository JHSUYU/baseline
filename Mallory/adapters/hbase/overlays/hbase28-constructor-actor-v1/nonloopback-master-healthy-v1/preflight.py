#!/usr/bin/env python3
"""JVM-free HBASE-28 admission check for a nonloopback master UI bind."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import socket
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6")
CONFIG_SHA256 = "2b99bfa3c35c8c9d1e3e48322a8e8466ff55b16699fe09388ca8bb43660dc84f"
SOURCE_PINS = {
    "hbase-common/src/main/java/org/apache/hadoop/hbase/HBaseConfiguration.java":
        "3f3aa0d24b0226eb918894a82099b5a5f9638e968d58468907bd588ab3065704",
    "hbase-common/src/main/java/org/apache/hadoop/hbase/util/Addressing.java":
        "fc05e62bb8fbb9bd4ecfc24f0cc003f1191d8aa9cb4fe3f500899a3ec61d5b17",
    "hbase-server/src/test/java/org/apache/hadoop/hbase/HBaseTestingUtility.java":
        "6c8e5bf0053fce4dcac27594a73e9bb4173d14e52bb296dffef7c0bdea6cab45",
    "hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/http/TestRSStatusPage.java":
        "8643f58811d877d807023356c7d23f8f55530d209f53a2367cfb221e95db292b",
    "hbase-server/src/main/java/org/apache/hadoop/hbase/LocalHBaseCluster.java":
        "3e9865e035bc5782e90404fae93cd47c37ccf4b2621923c73b56f5fcbc1ed5cb",
    "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java":
        "62ac5f8b5b42b57630c9421e16bd5371856064b312f3db06aefd03e35391e4b3",
    "hbase-server/src/main/java/org/apache/hadoop/hbase/master/HMaster.java":
        "6d47807a0bf39b6cf48677bd8acbd7eaf0bc0a6a148a04d013573cefa4b4deb1",
    "hbase-server/src/main/java/org/apache/hadoop/hbase/regionserver/HRegionServer.java":
        "c8a345ad34d12767d0277302ab705b9429626f0e8d7689fd493b2f81f8059023",
}


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def digest(path: Path) -> str:
    require(path.is_file(), f"missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    require(digest(path) == expected, f"SHA mismatch: {path}")


def xml_properties(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {p.findtext("name"): p.findtext("value") for p in root.findall("property")}


def local_ipv4_addresses() -> set[str]:
    addresses = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            try:
                data = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            addresses.add(socket.inet_ntoa(data[20:24]))
    return addresses


def preflight(node1: bool) -> None:
    check(HERE / "config.json", CONFIG_SHA256)
    config = json.loads((HERE / "config.json").read_text())
    require(config["case_id"] == "HBASE-28" and config["system"] == "hbase",
            "wrong case")
    require(config["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage#testStatusPage",
            "wrong test")
    require(config["command"][-2:] ==
            ["org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage", "testStatusPage"],
            "wrong JUnit runner selection")
    cp = config["command"][config["command"].index("-cp") + 1].split(":")
    require(cp[0] == str(HERE) and str(DIST / "conf") in cp,
            "case-local hbase-site.xml must be first on classpath")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["agent_properties"]["auto.io.doors"] is False and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "healthy-only observation controls changed")
    require(config["agent_properties"]["adapter.transformers"].endswith(
        "edu.uva.liftlab.mallory.hbase.hbase28.ConstructorActorTransformer") and
            "org.apache.hadoop.hbase.util.Addressing" in config["agent_include"] and
            "org.apache.hadoop.hbase.util.JVMClusterUtil" in config["agent_include"],
            "constructor actor or typed door instrumentation missing")
    bind = config["healthy_admission"]["bind_ipv4"]
    address = ipaddress.ip_address(bind)
    require(address.version == 4 and not address.is_loopback and
            not address.is_unspecified and not address.is_multicast,
            "configured bind is not nonloopback IPv4")
    props = xml_properties(HERE / "hbase-site.xml")
    distro_props = xml_properties(DIST / "conf/hbase-site.xml")
    require(props == {**distro_props, "hbase.master.info.bindAddress": bind} and
            "hbase.regionserver.info.bindAddress" not in props,
            "case-local configuration must change only master UI bind")
    require(any(item["path"] == str(HERE / "hbase-site.xml") and
                item["sha256"] == digest(HERE / "hbase-site.xml")
                for item in config["runtime_artifacts"]),
            "case-local configuration lacks SHA pin")
    for relative, expected in SOURCE_PINS.items():
        check(SOURCE / relative, expected)
    test = (SOURCE / "hbase-server/src/test/java/org/apache/hadoop/hbase/"
            "regionserver/http/TestRSStatusPage.java").read_text()
    require('conf.setInt(HConstants.MASTER_INFO_PORT, 0);' in test and
            'conf.setInt(HConstants.REGIONSERVER_INFO_PORT, 0);' in test and
            'CLUSTER = new LocalHBaseCluster(conf, 1);' in test and
            'new URL("http://" + hostname + ":" + infoPort + "/regionserver.jsp")'
            in test and
            'String expectedMasterLink = "<a href=\\\"//" + masterHostname' in test and
            "hbase.master.info.bindAddress" not in test,
            "selected JUnit no longer preserves master bind or RS-only HTTP fetch")
    hbase_conf = (SOURCE / "hbase-common/src/main/java/org/apache/hadoop/hbase/"
                  "HBaseConfiguration.java").read_text()
    utility = (SOURCE / "hbase-server/src/test/java/org/apache/hadoop/hbase/"
               "HBaseTestingUtility.java").read_text()
    require('conf.addResource("hbase-site.xml");' in hbase_conf and
            "this(HBaseConfiguration.create());" in utility,
            "classpath resource path changed")
    cluster = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/"
               "LocalHBaseCluster.java").read_text()
    factory = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/"
               "util/JVMClusterUtil.java").read_text()
    require("addMaster(new Configuration(conf), i);" in cluster and
            "addRegionServer(new Configuration(conf), j);" in cluster and
            "JVMClusterUtil.createMasterThread" in cluster and
            "server = hmc.getConstructor(Configuration.class).newInstance(c);" in factory,
            "master constructor actor path changed")
    target = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/"
              "regionserver/HRegionServer.java").read_text()
    addressing = (SOURCE / "hbase-common/src/main/java/org/apache/hadoop/hbase/"
                  "util/Addressing.java").read_text()
    require('addr = this.conf.get("hbase.master.info.bindAddress", "0.0.0.0");'
            in target and
            "if (!Addressing.isLocalAddress(InetAddress.getByName(addr)))" in target and
            "putUpWebUI();" in target,
            "exact master guard path changed")
    require("addr.isAnyLocalAddress() || addr.isLoopbackAddress()" in addressing and
            "local = NetworkInterface.getByInetAddress(addr) != null;" in addressing and
            "catch (SocketException e)" in addressing,
            "nonloopback typed door changed")
    sites = json.loads(Path(config["site_file"]).read_text())
    require(config["target"]["check_sites"] ==
            ["org.apache.hadoop.hbase.regionserver.HRegionServer#putUpWebUI()V@2482:branch:3"]
            and sites["doors"] == [{
                "clazz": "org.apache.hadoop.hbase.util.Addressing",
                "method": "isLocalAddress",
                "descriptor": "(Ljava/net/InetAddress;)Z",
                "line": 148,
                "callee": "java.net.NetworkInterface#getByInetAddress"
                          "(Ljava/net/InetAddress;)Ljava/net/NetworkInterface;",
                "exception_class": "java.net.SocketException"}],
            "exact guard or pretarget typed door selector changed")
    for item in config["runtime_artifacts"]:
        check(Path(item["path"]), item["sha256"])
    manifest = Path(config["core_release"]["path"]) / "manifest.json"
    check(manifest, config["core_release"]["manifest_sha256"])
    with zipfile.ZipFile(DIST / "lib/hbase-server-2.6.6-tests.jar") as jar:
        require(hashlib.sha256(jar.read(
            "org/apache/hadoop/hbase/regionserver/http/TestRSStatusPage.class"
        )).hexdigest() == "caff2eebc9d97c0db6393931adf03607487b2a3715e6a09e13f020d1588ae375",
                "selected JUnit class changed")
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(bind in local_ipv4_addresses(),
                f"{bind} is not assigned to a local IPv4 interface")
    print("PASS HBASE-28 JVM-free nonloopback master preflight; "
          "healthy trial zero remains pending")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, KeyError, FileNotFoundError, ET.ParseError,
            zipfile.BadZipFile) as exc:
        raise SystemExit(f"HBASE-28 nonloopback preflight gap: {exc}")


if __name__ == "__main__":
    main()
