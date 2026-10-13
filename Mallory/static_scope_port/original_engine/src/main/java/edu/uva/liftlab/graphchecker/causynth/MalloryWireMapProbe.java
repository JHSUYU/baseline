package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.options.Options;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Check a system-wide wire map against compiled classes with the original
 * GraphChecker parser, without running a case or a fault campaign.
 */
public final class MalloryWireMapProbe {
    private MalloryWireMapProbe() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException(
                    "usage: MalloryWireMapProbe MAPPINGS.jsonl CLASSPATH.txt");
        }
        Path mapping = Paths.get(args[0]).toAbsolutePath().normalize();
        Path classpath = Paths.get(args[1]).toAbsolutePath().normalize();
        String cp = new String(Files.readAllBytes(classpath),
                StandardCharsets.UTF_8).trim();
        if (!Files.isRegularFile(mapping) || cp.isEmpty()) {
            throw new IllegalArgumentException("mapping or classpath missing");
        }
        Set<String> owners = declaredOwners(mapping);
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_soot_classpath(cp);
        Options.v().set_output_format(Options.output_format_none);
        for (String owner : owners) {
            SootClass type = Scene.v().loadClassAndSupport(owner);
            if (type.isPhantom()) {
                throw new IllegalStateException("mapping owner unresolved: "
                        + owner);
            }
            type.setApplicationClass();
        }
        Scene.v().loadNecessaryClasses();
        Map<String, SootMethod> methods = new LinkedHashMap<>();
        for (SootClass type : Scene.v().getApplicationClasses()) {
            for (SootMethod method : type.getMethods()) {
                methods.put(method.getSignature(), method);
            }
        }
        System.setProperty(WireFlowCatalog.PROPERTY, mapping.toString());
        List<WireFlowCatalog.WireFlow> resolved =
                WireFlowCatalog.fromConfiguration(methods).flows();
        if (resolved.size() != rowCount(mapping)) {
            throw new IllegalStateException("resolved " + resolved.size()
                    + " of " + rowCount(mapping) + " wire rows");
        }
        for (WireFlowCatalog.WireFlow flow : resolved) {
            if (flow.producers.size() != 1 || flow.consumers.size() != 1) {
                throw new IllegalStateException("unpaired wire flow: " + flow.id);
            }
            System.out.println(flow.id + "\t" + flow.javaType + "\t"
                    + flow.producers.get(0).site() + "\t"
                    + flow.consumers.get(0).site());
        }
    }

    private static Set<String> declaredOwners(Path mapping) throws Exception {
        Set<String> owners = new LinkedHashSet<>();
        for (JsonObject row : rows(mapping)) {
            for (String side : new String[] {"producer", "consumer"}) {
                owners.add(owner(row.getAsJsonObject(side).get("method")
                        .getAsString()));
                if (row.has(side + "FrameMethod")) {
                    owners.add(owner(row.get(side + "FrameMethod")
                            .getAsString()));
                }
            }
        }
        return owners;
    }

    private static String owner(String signature) {
        int colon = signature.indexOf(':');
        if (!signature.startsWith("<") || colon <= 1) {
            throw new IllegalArgumentException("invalid Soot method signature: "
                    + signature);
        }
        return signature.substring(1, colon);
    }

    private static int rowCount(Path mapping) throws Exception {
        return rows(mapping).size();
    }

    private static List<JsonObject> rows(Path mapping) throws Exception {
        List<JsonObject> rows = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(mapping,
                StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.trim().isEmpty()) {
                    rows.add(JsonParser.parseString(line).getAsJsonObject());
                }
            }
        }
        return Collections.unmodifiableList(rows);
    }
}
