package edu.uva.liftlab.mallory.nativefeedback;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ActivationRow;
import edu.uva.liftlab.graphchecker.contract.AttachRow;
import edu.uva.liftlab.graphchecker.contract.CausalContext;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.graphchecker.contract.ExportRow;
import edu.uva.liftlab.graphchecker.contract.ExpressionTable;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.LocationKind;
import edu.uva.liftlab.graphchecker.contract.NodeId;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.ReadRow;
import edu.uva.liftlab.graphchecker.contract.Role;
import edu.uva.liftlab.graphchecker.contract.RowCodec;
import edu.uva.liftlab.graphchecker.contract.SessionDir;
import edu.uva.liftlab.graphchecker.contract.SessionManifest;
import edu.uva.liftlab.graphchecker.contract.TargetRow;
import edu.uva.liftlab.graphchecker.contract.WriteRow;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Synthetic native-contract pair, used only to test edge identity rules. */
public final class SyntheticNativeSession {
    private SyntheticNativeSession() { }

    public static void main(String[] args) throws Exception {
        Path iteration = Paths.get(args[0]);
        boolean omitHandoffExpression = Arrays.asList(args).contains(
                "--missing-handoff-expression");
        boolean secondTarget = Arrays.asList(args).contains("--second-target");
        SessionDir dir = SessionDir.of(iteration, "seed").create();
        OccurrenceAddress sender = OccurrenceAddress.of(NodeId.of("nn", 0),
                "R.sender", CausalContext.of(Role.of("SERVER"), "send", 1),
                ExecutionIndex.empty());
        Endpoint out = Endpoint.of(sender, "RPC.PORT", ExecutionIndex.empty(), 0);
        OccurrenceAddress writer = OccurrenceAddress.of(NodeId.of("dn", 0),
                "R.writer", CausalContext.of(out.id(), "RPC.call"),
                ExecutionIndex.empty());
        OccurrenceAddress target = OccurrenceAddress.of(NodeId.of("dn", 0),
                "R.target", CausalContext.of(Role.of("SERVER"), "check", 1),
                ExecutionIndex.empty());
        OccurrenceAddress targetTwo = OccurrenceAddress.of(NodeId.of("dn2", 0),
                "R.target", CausalContext.of(Role.of("SERVER"), "check", 1),
                ExecutionIndex.empty());
        Endpoint in = Endpoint.of(writer, "RPC.PORT", ExecutionIndex.empty(), 0);
        Endpoint stateOut = Endpoint.of(writer, "STATE.write",
                ExecutionIndex.empty(), 0);
        Endpoint stateIn = Endpoint.of(target, "STATE.read",
                ExecutionIndex.empty(), 0);
        LocationId location = LocationId.of(LocationKind.MAP, "object-1", "keys");
        java.util.List<ActivationRow> activations = new java.util.ArrayList<>(Arrays.asList(
                ActivationRow.of("seed", sender, "sender", false, true, "nn-thread"),
                ActivationRow.of("seed", writer, "writer", false, true,
                        "dn-worker", out),
                ActivationRow.of("seed", target, "target", false, true,
                        "dn-checker")));
        if (secondTarget) {
            activations.add(ActivationRow.of("seed", targetTwo, "target-two",
                    false, true, "dn2-checker"));
        }
        RowCodec.writeAll(dir.activations(), activations, RowCodec::writeActivation);
        RowCodec.writeAll(dir.exports(), Collections.singletonList(
                ExportRow.of("seed", 1L, out, "value-1", "I", 11L, "1")),
                RowCodec::writeExport);
        RowCodec.writeAll(dir.attaches(), Collections.singletonList(
                AttachRow.of("seed", 2L, in, "M_HANDOFF", "I", "1", false,
                        null, out, "rpc-1", AttachRow.HANDLE)),
                RowCodec::writeAttach);
        RowCodec.writeAll(dir.writes(), Collections.singletonList(
                WriteRow.of("seed", 3L, stateOut, location, 5L,
                        "expr-handoff", "I")), RowCodec::writeWrite);
        RowCodec.writeAll(dir.reads(), Collections.singletonList(
                ReadRow.of("seed", 4L, stateIn, location, 5L, "M_READ", "I", "1")),
                RowCodec::writeRead);
        java.util.List<TargetRow> targets = new java.util.ArrayList<>(
                Collections.singletonList(TargetRow.of("seed", 5L, target,
                        "Keys#check#u3", "(= M_READ 0)", false, true)));
        if (secondTarget) {
            targets.add(TargetRow.of("seed", 6L, targetTwo, "Keys#check#u3",
                    "(= 1 0)", false, true));
        }
        RowCodec.writeAll(dir.targets(), targets, RowCodec::writeTarget);
        JsonObject constant = new JsonObject();
        constant.addProperty("_type", "ConstExpr");
        constant.addProperty("_exp", "C_I_1");
        constant.addProperty("_java_type", "I");
        Map<String, JsonObject> expressions = new LinkedHashMap<>();
        expressions.put("value-1", constant);
        JsonObject handoff = new JsonObject();
        handoff.addProperty("_type", "SymbolExpression");
        handoff.addProperty("_exp", "M_HANDOFF");
        handoff.addProperty("_java_type", "I");
        if (!omitHandoffExpression) {
            expressions.put("expr-handoff", handoff);
        }
        RowCodec.writeExpressions(dir.expressions(), ExpressionTable.of(expressions));
        RowCodec.writeManifest(dir.manifest(), SessionManifest.of("seed",
                SessionManifest.Role.SEED, Collections.<String>emptyList()));
        JsonObject scope = new JsonObject();
        scope.addProperty("kind", "STATIC_SCOPE_SITE");
        scope.addProperty("role", "TARGET_SITE");
        scope.addProperty("regionId", "R.target");
        scope.addProperty("siteId", "Keys#check#u3");
        RowCodec.writeJsonl(iteration.resolve("static_scope_map.jsonl"),
                Collections.singletonList(scope));
    }
}
