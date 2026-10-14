"""Graph delta from the original GraphChecker REGION_STATE recording path.

The source-built original resolver binds an exact target branch to a recorded
region occurrence. The original recorder produces the runtime region plan.
This adapter then counts only observed trace branches and paired exchanges;
the static candidate graph is an input pin, not an observed edge.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import fcntl
from pathlib import Path
from typing import Any

from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    DEPENDENCIES, JAR,
)

SCHEMA = 1
REGION_IN_ENDPOINT = re.compile(r"/region/(REGION\.[^/]+)/")
PLAN_ID_CLASS = "edu.uva.liftlab.mallory.nativefeedback.RegionPlanIdsMain"
PLAN_ID_SOURCE = Path(__file__).with_name("RegionPlanIdsMain.java")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _rows(path: Path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"non-object trace row {path}:{number}")
                yield row


def _plan_identity_rows(plan_path: Path, engine_jar: Path,
                        plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Join Finalizer's selected occurrences using original GraphChecker IDs.

    The REGION_STATE trace has no SessionReader ActivationRows. Its original
    RuntimeSelectedRegionFinalizer plan is the admitted target demand closure;
    OccurrenceAddress, not a Python approximation of its hash, names members.
    """
    jar_sha = _sha(engine_jar)
    classes = PLAN_ID_SOURCE.parent / "target" / f"region-plan-ids-{jar_sha[:16]}"
    compiled = classes / "edu/uva/liftlab/mallory/nativefeedback/RegionPlanIdsMain.class"
    dependencies = DEPENDENCIES.read_text(encoding="utf-8").strip()
    classpath = f"{engine_jar}:{dependencies}"
    classes.mkdir(parents=True, exist_ok=True)
    with (classes / ".build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not compiled.is_file() or compiled.stat().st_mtime < PLAN_ID_SOURCE.stat().st_mtime:
            subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                            str(PLAN_ID_SOURCE)], check=True, timeout=120,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    before = _sha(plan_path)
    output = subprocess.run(["java", "-cp", f"{classes}:{classpath}",
                             PLAN_ID_CLASS, str(plan_path)], check=True,
                            timeout=120, text=True, capture_output=True).stdout
    if _sha(engine_jar) != jar_sha or _sha(plan_path) != before:
        raise ValueError("original plan or GraphChecker engine changed during ID join")
    by_address = {row["occurrenceId"]: row for row in plans}
    if len(by_address) != len(plans):
        raise ValueError("original Finalizer plan repeats an occurrence address")
    by_id: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        identifier, separator, address = line.partition("\t")
        if not separator or not identifier or address not in by_address:
            raise ValueError("GraphChecker returned an unknown plan occurrence")
        if identifier in by_id:
            raise ValueError("original Finalizer plan has colliding occurrence IDs")
        by_id[identifier] = by_address[address]
    if len(by_id) != len(plans):
        raise ValueError("GraphChecker omitted a Finalizer plan occurrence")
    return by_id


def _source_actor(source_key: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)#epoch([0-9]+)", source_key)
    if match is None:
        raise ValueError(f"trace has no physical actor and epoch: {source_key}")
    return match.group(1), int(match.group(2))


def _family(source_key: str, region_id: str) -> str:
    actor, _ = _source_actor(source_key)
    return f"{actor}/relation/{region_id}"


def _closed_inputs(trace_dir: Path, scope: Path, graph: Path,
                   skeletons: Path) -> dict[str, str]:
    manifest_file = trace_dir / "streaming_trace_manifest.json"
    manifest = _json(manifest_file)
    if (manifest.get("schemaVersion") != 2 or
            manifest.get("kind") != "STREAMING_RUNTIME_TRACE" or
            manifest.get("status") != "CLOSED" or
            not isinstance(manifest.get("tracedRows"), str) or
            not manifest["tracedRows"]):
        raise ValueError("original REGION_STATE trace is not CLOSED")
    trace_file = trace_dir / "runtime_trace.jsonl"
    return {"traceManifestSha256": _sha(manifest_file),
            "runtimeTraceSha256": _sha(trace_file),
            "scheduleSha256": _sha(trace_dir / "schedule.jsonl"),
            "scopeMapSha256": _sha(scope),
            "candidateGraphSha256": _sha(graph),
            "regionSkeletonsSha256": _sha(skeletons),
            "tracedRowsDigest": manifest["tracedRows"]}


def _validate_target(receipt: dict[str, Any], pins: dict[str, str],
                     branches: list[dict[str, Any]], calls: dict[int, dict[str, Any]],
                     target_site: str, fault_events: Path) -> dict[str, Any]:
    if (receipt.get("schemaVersion") != 1 or
            receipt.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE" or
            receipt.get("checkSiteId") != target_site):
        raise ValueError("original resolver selected another target")
    for field in ("traceManifestSha256", "runtimeTraceSha256", "scheduleSha256",
                  "scopeMapSha256", "candidateGraphSha256",
                  "regionSkeletonsSha256"):
        if receipt.get(field) != pins[field]:
            raise ValueError(f"target receipt input changed: {field}")
    selected = [row for row in branches if
                row.get("seq") == receipt.get("selectedEventSeq") and
                row.get("callId") == receipt.get("selectedCallId") and
                row.get("siteId") == target_site]
    if len(selected) != 1:
        raise ValueError("selected exact target branch is absent")
    call = calls.get(receipt["selectedCallId"])
    if call is None or call.get("sourceKey") != receipt[
            "selectedOccurrenceAddress"].split("/region/", 1)[0]:
        raise ValueError("selected target branch actor differs from occurrence")
    actor, epoch = _source_actor(call["sourceKey"])
    earlier = [row for row in branches if row.get("siteId") == target_site
               and row.get("seq", 0) <= receipt["selectedEventSeq"] and
               calls.get(row.get("callId", -1), {}).get("sourceKey") ==
               call["sourceKey"]]
    ordinal = len(earlier)
    checks = [row for row in _rows(fault_events) if row.get("kind") ==
              "TARGET_CHECK" and row.get("siteId") == target_site and
              row.get("node") == actor and row.get("actorEpochOrdinal") == epoch
              and row.get("ordinal") == ordinal
              and isinstance(row.get("occurrenceId"), str) and row["occurrenceId"]]
    if not checks:
        raise ValueError("exact target branch has no matching runtime TARGET_CHECK")
    return {"sourceKey": call["sourceKey"], "physicalActor": actor,
            "actorEpochOrdinal": epoch,
            "selectedOccurrenceAddress": receipt["selectedOccurrenceAddress"],
            "selectedEventSeq": receipt["selectedEventSeq"],
            "selectedCallId": receipt["selectedCallId"],
            "targetOrdinal": ordinal,
            "observedOutcome": selected[0]["outcome"],
            "observedFatal": selected[0]["outcome"] == receipt.get("fatalOutcome"),
            "targetCheckOccurrenceIds": sorted({r["occurrenceId"] for r in checks})}


def _target_throws(fault_events: Path, target_throw: dict[str, str] | None,
                   actor: str, epoch: int, occurrence_ids: set[str]
                   ) -> list[dict[str, Any]]:
    if target_throw is None:
        return []
    if not all(isinstance(target_throw.get(field), str) and target_throw[field]
               for field in ("siteId", "exceptionClass")):
        raise ValueError("target_throw requires exact siteId and exceptionClass")
    events = list(_rows(fault_events))
    checks = {row.get("occurrenceId"): row.get("seq") for row in events if
              row.get("kind") == "TARGET_CHECK" and row.get("node") == actor and
              row.get("actorEpochOrdinal") == epoch and
              row.get("occurrenceId") in occurrence_ids}
    return [row for row in events if row.get("kind") == "TARGET_THROW" and
            row.get("siteId") == target_throw["siteId"] and
            row.get("exceptionClass") == target_throw["exceptionClass"] and
            row.get("node") == actor and row.get("actorEpochOrdinal") == epoch and
            row.get("occurrenceId") in checks and
            isinstance(row.get("seq"), int) and isinstance(
                checks[row["occurrenceId"]], int) and
            row["seq"] > checks[row["occurrenceId"]]]


def _fatal_unplanned(trace_dir: Path, fault_events: Path,
                     target_site: str, target_throw: dict[str, str] | None,
                     pins: dict[str, str], engine_jar: Path) -> dict[str, Any] | None:
    """Preserve an exact thrown target when original nonfatal planning stops."""
    if target_throw is None:
        return None
    calls: dict[int, str] = {}
    branches: list[dict[str, Any]] = []
    for row in _rows(trace_dir / "runtime_trace.jsonl"):
        if row.get("event") == "METHOD_ENTER":
            calls[row.get("callId")] = row.get("sourceKey", "")
        elif row.get("event") == "BRANCH" and row.get("siteId") == target_site:
            branches.append(row)
    events = list(_rows(fault_events))
    for checked in events:
        if checked.get("kind") != "TARGET_CHECK" or checked.get(
                "siteId") != target_site:
            continue
        actor = checked.get("node")
        epoch = checked.get("actorEpochOrdinal")
        occurrence = checked.get("occurrenceId")
        if not (isinstance(actor, str) and isinstance(epoch, int) and
                isinstance(occurrence, str) and occurrence):
            continue
        source = f"{actor}#epoch{epoch}"
        matching = [row for row in branches if calls.get(row.get("callId")) ==
                    source]
        ordinal = checked.get("ordinal")
        if (not isinstance(ordinal, int) or ordinal < 1 or
                ordinal > len(matching)):
            continue
        throws = _target_throws(fault_events, target_throw, actor, epoch,
                                {occurrence})
        if not throws:
            continue
        return {"schemaVersion": SCHEMA, "backend": "original_region_state",
                "status": "target_throw_unplanned", "targetSiteId": target_site,
                "targetReached": True, "targetThrowObserved": True,
                "targetEvidence": {"physicalActor": actor,
                                   "actorEpochOrdinal": epoch,
                                   "targetCheckOccurrenceIds": [occurrence],
                                   "rawTargetBranchSeqs": [matching[ordinal - 1]["seq"]],
                                   "targetThrowRows": throws},
                "nodeFamilies": [], "edgeFamilies": [],
                "closureEdgeFamilies": [], "branchOutcomeIds": [],
                "provenance": {**pins, "faultEventsSha256": _sha(fault_events),
                               "engineJarSha256": _sha(engine_jar)}}
    return None


def summarize_region_state(
        trace_dir: Path, plan_path: Path, target_receipt: Path,
        fault_events: Path, static_scope_map: Path, candidate_graph: Path,
        region_skeletons: Path, target_site: str, output: Path | None = None,
        *, engine_jar: Path | None = None,
        target_throw: dict[str, str] | None = None) -> dict[str, Any]:
    """Summarize one original Recorder plan and its immutable raw trace."""
    trace_dir = trace_dir.resolve(strict=True)
    paths = [plan_path, target_receipt, fault_events, static_scope_map,
             candidate_graph, region_skeletons]
    (plan_path, target_receipt, fault_events, static_scope_map,
     candidate_graph, region_skeletons) = [path.resolve(strict=True)
                                           for path in paths]
    pins = _closed_inputs(trace_dir, static_scope_map, candidate_graph,
                          region_skeletons)
    calls: dict[int, dict[str, Any]] = {}
    branches: list[dict[str, Any]] = []
    exchange_rows: list[dict[str, Any]] = []
    trace_count = 0
    for row in _rows(trace_dir / "runtime_trace.jsonl"):
        trace_count += 1
        event = row.get("event")
        if event == "METHOD_ENTER" and isinstance(row.get("callId"), int):
            calls[row["callId"]] = {"parentCallId": row.get("parentCallId", 0),
                                    "sourceKey": row.get("sourceKey"),
                                    "seq": row.get("seq")}
        elif event == "BRANCH":
            branches.append({key: row.get(key) for key in (
                "seq", "callId", "siteId", "outcome")})
        elif event in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE"):
            exchange_rows.append({key: row.get(key) for key in (
                "event", "seq", "callId", "transport", "correlationId", "attemptId",
                "half", "spanId", "remoteParentSpanId", "producerEndpoint",
                "producerEndpointId",
                "sourceKey")})
    receipt = _json(target_receipt)
    target = _validate_target(receipt, pins, branches, calls, target_site,
                              fault_events)
    plan_rows = list(_rows(plan_path))
    if not plan_rows or plan_rows[0].get("kind") != (
            "CONCOLIC_RUNTIME_MODEL_CATALOG"):
        raise ValueError("original Recorder region catalog is missing")
    plans = [row for row in plan_rows[1:] if row.get("kind") ==
             "CONCOLIC_REGION_PLAN"]
    if len(plans) != len(plan_rows) - 1 or not plans:
        raise ValueError("original Recorder plan has invalid rows")
    original_jar = (engine_jar or JAR).resolve(strict=True)
    closure_by_id = _plan_identity_rows(plan_path, original_jar, plans)
    by_occurrence = {row["occurrenceId"]: row for row in plans}
    selected = by_occurrence.get(target["selectedOccurrenceAddress"])
    if selected is None:
        raise ValueError("original Recorder plan lost the exact target occurrence")
    if not any(closure_by_id.get(identifier) is selected for identifier in
               target["targetCheckOccurrenceIds"]):
        raise ValueError("original Finalizer plan omitted the exact target check")
    if receipt["targetRegionId"] != selected["regionId"] and receipt[
            "targetRegionId"] not in selected.get("foldedRegionIds", []):
        raise ValueError("target check region is outside its selected activation")
    node_families = {_family(row["sourceKey"], row["regionId"]) for row in plans}
    by_root = {row["rootCallId"]: row for row in plans}
    # A transport RECEIVE can precede the first instrumented method entry on
    # its thread (callId=0).  GraphChecker carries the producer endpoint ID in
    # the subsequent occurrence's causal context, so retain those exact
    # identities as an alternative to call-stack ownership.  The token
    # boundaries matter: a substring match would alias different messages.
    by_message_anchor: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for plan in plans:
        context = plan["occurrenceId"].split("/ctx:Anchor:", 1)
        if len(context) != 2 or "@" not in context[1]:
            continue
        endpoint_id = context[1].split("@", 1)[0]
        if endpoint_id:
            by_message_anchor.setdefault((plan["sourceKey"], endpoint_id), []).append(plan)
    owner_cache: dict[int, dict[str, Any] | None] = {}

    def owner(call_id: int) -> dict[str, Any] | None:
        if call_id in owner_cache:
            return owner_cache[call_id]
        walked: list[int] = []
        current = call_id
        found = None
        while current and current not in owner_cache:
            walked.append(current)
            if current in by_root:
                found = by_root[current]
                break
            call = calls.get(current)
            current = call.get("parentCallId", 0) if call else 0
        if found is None and current in owner_cache:
            found = owner_cache[current]
        for part in walked:
            owner_cache[part] = found
        return found

    branch_outcomes = set()
    exchanges: dict[tuple[str, str, str, str], dict[str, list[dict[str, Any]]]] = {}
    for row in branches:
        if (isinstance(row.get("callId"), int) and
                owner(row["callId"]) is not None and
                isinstance(row.get("siteId"), str)):
            branch_outcomes.add(f"{row['siteId']}|{str(row.get('outcome')).lower()}")
    for row in exchange_rows:
        key = tuple(str(row.get(field) or "") for field in (
            "transport", "correlationId", "attemptId", "half"))
        if all(key):
            exchanges.setdefault(key, {"EXCHANGE_SEND": [],
                                       "EXCHANGE_RECEIVE": []})[row["event"]].append(row)
    edge_families = set()
    closure_edges = set()
    paired = unmapped = ambiguous = anchor_mapped = 0

    def endpoint_owner(endpoint: str) -> dict[str, Any] | None:
        # Original Endpoint.render() appends /site:<site>/sidx:<index>/att:<n>
        # to the exact occurrence address. The site cannot contain '/', so
        # the final /site: delimiter names the producer without a scan over
        # every member in the Finalizer plan.
        address, delimiter, _ = endpoint.rpartition("/site:")
        if not delimiter:
            return None
        return by_occurrence.get(address)

    for key, pair in exchanges.items():
        for received in pair["EXCHANGE_RECEIVE"]:
            candidates = [sent for sent in pair["EXCHANGE_SEND"] if
                          sent.get("spanId") is not None and
                          sent.get("spanId") == received.get("remoteParentSpanId")]
            if len(candidates) != 1:
                ambiguous += 1
                continue
            sent = candidates[0]
            paired += 1
            source_region = REGION_IN_ENDPOINT.search(sent.get(
                "producerEndpoint") or "")
            destination = owner(received.get("callId") or 0)
            destinations = [destination] if destination is not None else []
            if not destinations:
                endpoint_id = sent.get("producerEndpointId")
                producer_endpoint = sent.get("producerEndpoint") or ""
                # The original region plan must actually contain the exact
                # producer occurrence.  A role-only endpoint or a copied
                # context from another physical source is insufficient.
                producer = endpoint_owner(producer_endpoint)
                producer_enter = calls.get(producer["rootCallId"], {}) \
                    if producer is not None else {}
                if (isinstance(endpoint_id, str) and endpoint_id and
                        producer is not None and
                        producer["sourceKey"] == sent.get("sourceKey") and
                        isinstance(producer_enter.get("seq"), int) and
                        producer_enter["seq"] <= sent.get("seq", -1) and
                        isinstance(received.get("seq"), int) and
                        sent["seq"] < received["seq"]):
                    destinations = [plan for plan in by_message_anchor.get((
                        received.get("sourceKey"), endpoint_id), []) if
                        isinstance(calls.get(plan["rootCallId"], {}).get("seq"), int)
                        and received.get("seq", -1) <
                        calls[plan["rootCallId"]]["seq"]]
                    if destinations:
                        anchor_mapped += 1
            if source_region is None or not destinations:
                unmapped += 1
                continue
            source_family = _family(sent["sourceKey"], source_region.group(1))
            for destination in destinations:
                destination_family = _family(destination["sourceKey"],
                                             destination["regionId"])
                family = f"{key[0]}|{key[3]}|{source_family}->{destination_family}"
                edge_families.add(family)
                if (endpoint_owner(sent.get("producerEndpoint") or "") is not None
                        and destination["occurrenceId"] in by_occurrence):
                    closure_edges.add(family)
    selected_family = _family(selected["sourceKey"], selected["regionId"])
    throws = _target_throws(fault_events, target_throw,
                            target["physicalActor"],
                            target["actorEpochOrdinal"],
                            set(target["targetCheckOccurrenceIds"]))
    result = {"schemaVersion": SCHEMA, "backend": "original_region_state",
              "status": "recorded", "targetSiteId": target_site,
              "targetReached": True,
              "targetThrowObserved": bool(throws),
              "targetRegionId": receipt["targetRegionId"],
              "targetActivationRegionId": selected["regionId"],
              "targetNodeFamily": selected_family,
              "targetEvidence": {**target, "targetThrowRows": throws},
              "closureMembershipAuthority":
                  "original_runtime_selected_region_finalizer",
              "closureOccurrenceIds": sorted(closure_by_id),
              "closureMembers": sorted(({
                  "occurrenceId": identifier,
                  "occurrenceAddress": plan["occurrenceId"],
                  "regionId": plan["regionId"],
                  "sourceKey": plan["sourceKey"],
                  "admissionBasis": plan.get("admissionBasis", ""),
                  "demandDepth": plan.get("demandDepth"),
              } for identifier, plan in closure_by_id.items()),
                  key=lambda row: row["occurrenceId"]),
              "nodeFamilies": sorted(node_families),
              "edgeFamilies": sorted(edge_families),
              "closureEdgeFamilies": sorted(closure_edges),
              "branchOutcomeIds": sorted(branch_outcomes),
              "counts": {"traceRows": trace_count, "regionPlanRows": len(plans),
                         "pairedExchangeEvents": paired,
                         "anchorMappedPairedExchanges": anchor_mapped,
                         "unmappedPairedExchanges": unmapped,
                         "ambiguousExchangeReceives": ambiguous,
                         "catalogGaps": len(plan_rows[0].get("gaps", []))},
              "provenance": {**pins, "regionPlanSha256": _sha(plan_path),
                             "targetReceiptSha256": _sha(target_receipt),
                             "faultEventsSha256": _sha(fault_events),
                             "engineJarSha256": _sha(engine_jar or JAR)}}
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def delta_region_state(healthy: dict[str, Any], faulted: dict[str, Any]
                       ) -> dict[str, Any]:
    """Compare recorded families; never interpret target loss as novelty."""
    if healthy.get("backend") != "original_region_state" or not healthy.get(
            "targetReached"):
        raise ValueError("healthy original target recording is required")
    if (faulted.get("backend") != healthy["backend"] or
            faulted.get("targetSiteId") != healthy["targetSiteId"] or
            faulted.get("provenance", {}).get("scopeMapSha256") != healthy[
                "provenance"]["scopeMapSha256"] or
            faulted.get("provenance", {}).get("candidateGraphSha256") != healthy[
                "provenance"]["candidateGraphSha256"] or
            faulted.get("provenance", {}).get("regionSkeletonsSha256") != healthy[
                "provenance"]["regionSkeletonsSha256"] or
            faulted.get("provenance", {}).get("tracedRowsDigest") != healthy[
                "provenance"]["tracedRowsDigest"]):
        raise ValueError("REGION_STATE delta inputs differ")
    if not faulted.get("targetReached") or faulted.get(
            "targetActivationRegionId") != healthy["targetActivationRegionId"]:
        return {"status": "target_lost", "targetRetained": False,
                "newNodeFamilies": [], "newEdgeFamilies": [],
                "newClosureEdgeFamilies": [], "newBranchOutcomeIds": []}
    result: dict[str, Any] = {"status": "compared", "targetRetained": True,
                              "targetActorChanged": faulted.get(
                                  "targetNodeFamily") != healthy["targetNodeFamily"]}
    for field, out in (("nodeFamilies", "newNodeFamilies"),
                       ("edgeFamilies", "newEdgeFamilies"),
                       ("closureEdgeFamilies", "newClosureEdgeFamilies"),
                       ("branchOutcomeIds", "newBranchOutcomeIds")):
        result[out] = sorted(set(faulted[field]) - set(healthy[field]))
        result["lost" + field[0].upper() + field[1:]] = sorted(
            set(healthy[field]) - set(faulted[field]))
    return result


def record_region_state(
        trace_dir: Path, output_dir: Path, *, test_id: str, target_site: str,
        fault_events: Path, static_scope_map: Path, candidate_graph: Path,
        region_skeletons: Path, engine_jar: Path = JAR,
        java: Path = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java"),
        loop_bound: int = 3, timeout_seconds: int = 300,
        heap_mb: int = 3072,
        target_throw: dict[str, str] | None = None) -> dict[str, Any]:
    """Run original resolver and Recorder once for one fresh CLOSED trace."""
    if (loop_bound <= 0 or timeout_seconds <= 0 or
            not isinstance(heap_mb, int) or isinstance(heap_mb, bool) or
            not 0 < heap_mb <= 65536):
        raise ValueError("positive loop bound, timeout, and bounded heap are required")
    trace_dir = trace_dir.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    scope, graph, skeletons = (path.resolve(strict=True) for path in (
        static_scope_map, candidate_graph, region_skeletons))
    engine_jar = engine_jar.resolve(strict=True)
    java = java.resolve(strict=True)
    before = _closed_inputs(trace_dir, scope, graph, skeletons)
    classpath = os.pathsep.join((str(engine_jar),
                                 DEPENDENCIES.read_text(encoding="utf-8").strip()))
    base = [str(java), f"-Xmx{heap_mb}m",
            f"-Dcausynth.loop.default.bound={loop_bound}",
            "-cp", classpath]
    receipt_file = output_dir / "target-occurrence.json"
    resolver = [*base,
                "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
                "--trace-dir", str(trace_dir), "--test", test_id,
                "--region-skeletons", str(skeletons),
                "--static-scope-map", str(scope),
                "--candidate-graph", str(graph),
                "--check-site-id", target_site, "--output", str(receipt_file)]
    (output_dir / "resolver-command.json").write_text(json.dumps(resolver) + "\n")
    resolved = subprocess.run(resolver, text=True, capture_output=True,
                              timeout=timeout_seconds)
    (output_dir / "resolver.stdout").write_text(resolved.stdout)
    (output_dir / "resolver.stderr").write_text(resolved.stderr)
    if resolved.returncode != 0:
        if "TARGET_CHECK_NOT_OBSERVED" in resolved.stderr:
            result = _fatal_unplanned(trace_dir, fault_events, target_site,
                                      target_throw, before, engine_jar)
            if result is None:
                result = {"schemaVersion": SCHEMA,
                          "backend": "original_region_state",
                          "targetSiteId": target_site, "targetReached": False,
                          "targetThrowObserved": False,
                          "status": "target_absent", "nodeFamilies": [],
                          "edgeFamilies": [], "closureEdgeFamilies": [],
                          "branchOutcomeIds": [], "provenance": before}
            (output_dir / "summary.json").write_text(json.dumps(result,
                                                  sort_keys=True, indent=2) + "\n")
            return result
        raise RuntimeError("original target resolver failed: " +
                           resolved.stderr[-2000:])
    receipt = _json(receipt_file)
    plan_dir = output_dir / "recorded"
    target_arg = ",".join((str(graph), str(scope), str(skeletons),
                           str(plan_dir)))
    recorder = [*base, "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
                "--trace-dir", str(trace_dir), "--test", test_id,
                "--target", f"native={target_arg}",
                "--target-occurrence", receipt["selectedOccurrenceAddress"]]
    (output_dir / "recorder-command.json").write_text(json.dumps(recorder) + "\n")
    recorded = subprocess.run(recorder, text=True, capture_output=True,
                              timeout=timeout_seconds)
    (output_dir / "recorder.stdout").write_text(recorded.stdout)
    (output_dir / "recorder.stderr").write_text(recorded.stderr)
    if recorded.returncode != 0:
        fatal = _fatal_unplanned(trace_dir, fault_events, target_site,
                                 target_throw, before, engine_jar)
        if fatal is not None:
            (output_dir / "summary.json").write_text(json.dumps(
                fatal, sort_keys=True, indent=2) + "\n")
            return fatal
        raise RuntimeError("original GraphChecker Recorder failed: " +
                           recorded.stderr[-2000:])
    if _closed_inputs(trace_dir, scope, graph, skeletons) != before:
        raise ValueError("original trace or static inputs changed during extraction")
    summary = summarize_region_state(trace_dir,
                                     plan_dir / "concolic_region_plan.jsonl",
                                     receipt_file, fault_events, scope, graph,
                                     skeletons, target_site,
                                     output_dir / "summary.json",
                                     engine_jar=engine_jar,
                                     target_throw=target_throw)
    summary["provenance"]["extractor"] = "invoked_original_resolver_and_recorder"
    (output_dir / "summary.json").write_text(json.dumps(summary,
                                                  sort_keys=True, indent=2) + "\n")
    return summary
