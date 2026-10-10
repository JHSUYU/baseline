#!/usr/bin/env python3
"""Offline source, bytecode, actor, and package preflight for SOLR-39."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
CHECK = "org.apache.solr.update.processor.RoutedAliasUpdateProcessor#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1"
GET_DATA = ("org/apache/solr/common/cloud/SolrZkClient", "getData",
            "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;Z)[B")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def line(path: Path, number: int, fragment: str) -> None:
    lines = path.read_text().splitlines()
    require(len(lines) >= number and fragment in lines[number - 1],
            f"source line changed: {path}:{number}")


def method_code(data: bytes, wanted: str, descriptor: str) -> tuple[bytes, list[tuple[int, int]], dict[int, tuple[str, str, str]]]:
    """Read the needed class-file Code and LineNumberTable without a JVM."""
    pos = 8

    def u2() -> int:
        nonlocal pos
        value = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        return value

    def u4() -> int:
        nonlocal pos
        value = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        return value

    require(data[:4] == b"\xca\xfe\xba\xbe", "invalid class file")
    constant_pool = [None]
    count = u2()
    index = 1
    while index < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            length = u2()
            value = data[pos:pos + length].decode()
            pos += length
        elif tag in (3, 4):
            value = u4()
        elif tag in (5, 6):
            value = (u4(), u4())
        elif tag in (7, 8, 16, 19, 20):
            value = u2()
        elif tag in (9, 10, 11, 12, 17, 18):
            value = (u2(), u2())
        elif tag == 15:
            kind = data[pos]
            pos += 1
            value = (kind, u2())
        else:
            raise ValueError(f"unsupported class constant tag {tag}")
        constant_pool.append((tag, value))
        index += 1
        if tag in (5, 6):
            constant_pool.append(None)
            index += 1

    def cp(index: int):
        tag, value = constant_pool[index]
        if tag == 1:
            return value
        if tag in (7, 8, 16, 19, 20):
            return cp(value)
        if tag == 12:
            return tuple(cp(item) for item in value)
        if tag in (9, 10, 11):
            owner = cp(value[0])
            name, desc = cp(value[1])
            return (owner, name, desc)
        return value

    def skip_attributes() -> None:
        nonlocal pos
        for _ in range(u2()):
            u2()
            length = u4()
            pos += length

    u2()  # access flags
    u2()  # this class
    u2()  # super class
    interface_count = u2()
    pos += 2 * interface_count
    for _ in range(u2()):
        u2()
        u2()
        u2()
        skip_attributes()
    for _ in range(u2()):
        u2()
        name, desc = cp(u2()), cp(u2())
        for _ in range(u2()):
            attr = cp(u2())
            length = u4()
            end = pos + length
            if attr == "Code" and name == wanted and desc == descriptor:
                u2()  # max stack
                u2()  # max locals
                code_length = u4()
                code = data[pos:pos + code_length]
                pos += code_length
                exception_count = u2()
                pos += 8 * exception_count
                lines = []
                for _ in range(u2()):
                    child = cp(u2())
                    child_length = u4()
                    child_end = pos + child_length
                    if child == "LineNumberTable":
                        lines = [(u2(), u2()) for _ in range(u2())]
                    pos = child_end
                refs = {}
                for offset, opcode in enumerate(code):
                    if opcode in (0xb6, 0xb7, 0xb8, 0xb9):
                        ref = cp(struct.unpack_from(">H", code, offset + 1)[0])
                        if isinstance(ref, tuple) and len(ref) == 3:
                            refs[offset] = ref
                return code, lines, refs
            pos = end
    raise ValueError(f"method not found: {wanted}{descriptor}")


def main() -> dict:
    manifest = read(HERE / "manifest.json")
    require(manifest["case_id"] == "SOLR-39", "wrong manifest case")
    for label, record in manifest["files"].items():
        path = Path(record["path"])
        require(path.is_file() and sha(path) == record["sha256"],
                f"missing or changed {label}: {path}")

    config = read(HERE / "config.json")
    sites = read(HERE / "sites.json")
    source = Path(config["cwd"])
    require(config["case_id"] == "SOLR-39" and
            config["cluster_test"] == "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test",
            "selector changed")
    require(config["source_equivalent_root"] == str(source) and source.is_dir(),
            "source root changed or missing")
    require(config["site_file"] == str(HERE / "sites.json"), "site file changed")
    require(config["target"]["check_sites"] == [CHECK] and
            config["expected_target_class_sha256"] == manifest["class_sha256"]["target"],
            "exact target changed")
    require(config["calibration_only"] is True and config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and config["fault_types"] == ["EXCEPTION"],
            "healthy-only restriction changed")
    require(config["require_event_time_paths"] is True and config["reject_coarse_roots"] is True,
            "event-time admission flags changed")
    require(config["command"][1] == str(ROOT / "Mallory/adapters/solr/releases/v38/run_pilot.py") and
            config["command"][2:5] == ["SOLR-39", "--source", str(source)],
            "runner or source changed")
    require("-Dsolr.disableConfigSetsCreateAuthChecks=true" in config["env"]["JAVA_TOOL_OPTIONS"] and
            config["env"]["MALLORY_SOLR_AWAITSFIX"] == "1", "passing JUnit fixture flags changed")
    require("org.apache.solr.common.cloud.ZkStateReader" in config["agent_include"],
            "candidate door class not included")
    require(sites["doors"] == manifest["candidate_doors"] and
            [(row["clazz"], row["line"]) for row in sites["targets"]] == [
                ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor", 246),
                ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor", 247)],
            "candidate door or target catalog changed")

    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"runtime artifact changed: {path}")
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config  # noqa: E402
    validate_config(config)

    core_jar = Path(config["mapping"]["compiled_jar"])
    solrj_jar = Path(config["mapping"]["compiled_solrj_jar"])
    with zipfile.ZipFile(core_jar) as archive:
        target = archive.read("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class")
    with zipfile.ZipFile(solrj_jar) as archive:
        reader = archive.read("org/apache/solr/common/cloud/ZkStateReader.class")
    require(hashlib.sha256(target).hexdigest() == manifest["class_sha256"]["target"] and
            hashlib.sha256(reader).hexdigest() == manifest["class_sha256"]["reader"],
            "compiled class changed")
    code, lines, refs = method_code(target, "lookupShardLeadersOfCollections", "()Ljava/util/List;")
    require([(offset, number) for offset, number in lines if number in (244, 245, 246, 247, 249)] ==
            [(0, 244), (11, 245), (28, 246), (32, 247), (40, 249)] and
            code[29] == 0xc7 and struct.unpack_from(">h", code, 30)[0] == 11 and
            code[39] == 0xbf, "target branch/throw bytecode changed")
    reader_desc = "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/solr/common/cloud/ZkStateReader$VersionedCollectionProps;"
    code, lines, refs = method_code(reader, "fetchCollectionProperties", reader_desc)
    require((69, 1274) in lines and code[78] == 0xb6 and refs.get(78) == GET_DATA,
            "collection-property getData callsite bytecode changed")

    processor = source / "solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"
    test = source / "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"
    reader_source = source / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    require(sha(processor) == config["mapping"]["target_source_sha256"] and
            sha(test) == config["mapping"]["test_source_sha256"] and
            sha(reader_source) == config["mapping"]["reader_source_sha256"],
            "source file changed")
    for number, fragment in ((102, "getCollectionProperties"), (195, "lookupShardLeadersOfCollections"),
                             (201, "lookupShardLeadersOfCollections"), (246, "if (collections == null)"),
                             (247, "newAliasMustExistException")):
        line(processor, number, fragment)
    for number, fragment in ((89, "configureCluster(4)"), (132, "createTimeRoutedAlias"),
                             (139, "solrClient.commit(alias)"), (175, "deleteById(alias")):
        line(test, number, fragment)
    for number, fragment in ((1220, "haveUnexpiredProps"), (1225, "fetchCollectionProperties"),
                             (1274, "zkClient.getData"), (2223, "volatile read")):
        line(reader_source, number, fragment)

    prior = read(Path(manifest["files"]["solr10_prior_healthy"]["path"]))
    require(prior["case_id"] == "SOLR-10" and prior["healthy_seed_verified"] is True and
            prior["junit"]["status"] == "passed" and prior["junit"]["tests"] == 1 and
            prior["pilot_test"] == config["cluster_test"] and prior["named_target_nodes"] == ["node2"],
            "passing selector baseline changed")
    prior_pilot = read(Path(manifest["files"]["solr10_prior_pilot"]["path"]))
    prior_log = Path(manifest["files"]["solr10_prior_junit_log"]["path"]).read_text()
    require(prior_pilot["target_nodes"] == ["node2"] and
            prior_pilot["test_source_sha256"] == config["mapping"]["test_source_sha256"] and
            "MALLORY_SOLR_NODE logical=node2 physical=127.0.0.1:34103_solr epoch=0" in prior_log,
            "passing selector actor baseline changed")
    request = read(HERE / "admission-request.json")
    require(request["go"] is False and request["mode"] == "healthy" and
            request["config_sha256"] == sha(HERE / "config.json"),
            "admission request changed")
    result = {"status": "offline_preflight_passed_healthy_only", "case_id": "SOLR-39",
              "config_sha256": sha(HERE / "config.json"), "site_sha256": sha(HERE / "sites.json"),
              "target_class_sha256": hashlib.sha256(target).hexdigest(),
              "reader_class_sha256": hashlib.sha256(reader).hexdigest(), "jvm_run": False}
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
