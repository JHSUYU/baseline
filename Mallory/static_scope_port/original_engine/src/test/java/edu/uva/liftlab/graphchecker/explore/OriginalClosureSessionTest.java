package edu.uva.liftlab.graphchecker.explore;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ActivationRow;
import edu.uva.liftlab.graphchecker.contract.CausalContext;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.graphchecker.contract.ExpressionTable;
import edu.uva.liftlab.graphchecker.contract.GapRow;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.LocationKind;
import edu.uva.liftlab.graphchecker.contract.NodeId;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.ReadRow;
import edu.uva.liftlab.graphchecker.contract.Role;
import edu.uva.liftlab.graphchecker.contract.RowCodec;
import edu.uva.liftlab.graphchecker.contract.SessionDir;
import edu.uva.liftlab.graphchecker.contract.SessionManifest;
import edu.uva.liftlab.graphchecker.contract.SessionReader;
import edu.uva.liftlab.graphchecker.contract.TargetRow;
import edu.uva.liftlab.graphchecker.contract.Task;
import edu.uva.liftlab.graphchecker.contract.WriteRow;
import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** The original post-run closure reads native GraphChecker contract files. */
public final class OriginalClosureSessionTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void exactVersionedReadDemandsItsNativeSessionWriter()
            throws Exception {
        Path iteration = temporary.newFolder("iteration").toPath();
        SessionDir dir = SessionDir.of(iteration, "seed").create();
        NodeId node = NodeId.of("server", 0);
        OccurrenceAddress writer = OccurrenceAddress.of(node, "R.writer",
                CausalContext.of(Role.of("SERVER"), "write", 1),
                ExecutionIndex.empty());
        OccurrenceAddress target = OccurrenceAddress.of(node, "R.target",
                CausalContext.of(Role.of("SERVER"), "check", 1),
                ExecutionIndex.empty());
        LocationId state = LocationId.of(LocationKind.MAP, "object-1", "keys");
        Endpoint written = Endpoint.of(writer,
                Endpoint.stateSite("Keys", "put", 1, true),
                ExecutionIndex.empty(), 0);
        Endpoint read = Endpoint.of(target,
                Endpoint.stateSite("Keys", "get", 2, false),
                ExecutionIndex.empty(), 0);
        RowCodec.writeAll(dir.activations(), Arrays.asList(
                ActivationRow.of("seed", writer, "task-writer", false, true, "writer-thread"),
                ActivationRow.of("seed", target, "task-target", false, true, "reader-thread")),
                RowCodec::writeActivation);
        RowCodec.writeAll(dir.writes(), Collections.singletonList(
                WriteRow.of("seed", 1L, written, state, 5L, "value-1", "I")),
                RowCodec::writeWrite);
        RowCodec.writeAll(dir.reads(), Collections.singletonList(
                ReadRow.of("seed", 2L, read, state, 5L, "M_READ", "I", "1")),
                RowCodec::writeRead);
        RowCodec.writeAll(dir.targets(), Collections.singletonList(
                TargetRow.of("seed", 3L, target, "Keys#check#u3",
                        "(= M_READ 0)", false, true)), RowCodec::writeTarget);
        JsonObject constant = new JsonObject();
        constant.addProperty("_type", "ConstExpr");
        constant.addProperty("_exp", "C_I_1");
        constant.addProperty("_java_type", "I");
        Map<String, JsonObject> expressions = new LinkedHashMap<>();
        expressions.put("value-1", constant);
        RowCodec.writeExpressions(dir.expressions(), ExpressionTable.of(expressions));
        RowCodec.writeManifest(dir.manifest(), SessionManifest.of("seed",
                SessionManifest.Role.SEED, Collections.<String>emptyList()));

        JsonObject scopeRow = new JsonObject();
        scopeRow.addProperty("kind", "STATIC_SCOPE_SITE");
        scopeRow.addProperty("role", "TARGET_SITE");
        scopeRow.addProperty("regionId", "R.target");
        scopeRow.addProperty("siteId", "Keys#check#u3");
        Path scopeFile = iteration.resolve("static_scope_map.jsonl");
        RowCodec.writeJsonl(scopeFile, Collections.singletonList(scopeRow));

        SessionReader nativeSession = SessionReader.read(dir);
        assertEquals(1, nativeSession.reads().size());
        assertTrue(nativeSession.incomplete().isEmpty());
        Corpus corpus = Corpus.read(iteration, null);
        ArrayList<GapRow> gaps = new ArrayList<>();
        ClosurePlanner.Plan closure = ClosurePlanner.plan(corpus, target, 8,
                StaticScopeMap.read(scopeFile),
                Branches.of(corpus, Collections.singletonList(target), gaps));
        assertTrue(closure.truncated.isEmpty());
        assertTrue(closure.tasks.stream().map(Task::focused)
                .anyMatch(writer::equals));
    }
}
