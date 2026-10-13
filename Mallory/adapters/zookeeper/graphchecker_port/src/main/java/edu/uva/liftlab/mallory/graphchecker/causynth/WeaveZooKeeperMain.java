package edu.uva.liftlab.mallory.graphchecker.causynth;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import soot.G;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.options.Options;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.io.Reader;
import java.util.Collections;

/** Standalone, isolated verification of the ZooKeeper production weave. */
public final class WeaveZooKeeperMain {
    private WeaveZooKeeperMain() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3 && args.length != 4) {
            throw new IllegalArgumentException("usage: WeaveZooKeeperMain "
                    + "<zookeeper-server/target/classes> <classpath> "
                    + "<isolated-output-dir> [generated-weave-manifest.json]");
        }
        ZooKeeperWeave.TargetMethod target = args.length == 4
                ? targetFromManifest(Paths.get(args[3])) : null;
        Path classes = Paths.get(args[0]).toAbsolutePath().normalize();
        Path output = Paths.get(args[2]).toAbsolutePath().normalize();
        if (!Files.isDirectory(classes) || output.startsWith(classes)
                || classes.startsWith(output)) {
            throw new IllegalArgumentException("source classes must exist; "
                    + "output must be a separate directory");
        }
        Files.createDirectories(output);
        G.reset();
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_prepend_classpath(true);
        Options.v().set_process_dir(Collections.singletonList(
                classes.toString()));
        Options.v().set_soot_classpath(args[1]);
        Options.v().set_output_dir(output.toString());
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_keep_line_number(true);
        Options.v().set_whole_program(true);
        Scene.v().addBasicClass(
                "edu.uva.liftlab.mallory.graphchecker.runtime.ZooKeeperTraceBridge",
                SootClass.SIGNATURES);
        Scene.v().addBasicClass(
                "edu.uva.liftlab.mallory.graphchecker.runtime.PersistentFileTraceBridge",
                SootClass.SIGNATURES);
        Scene.v().loadNecessaryClasses();
        ZooKeeperWeave.apply();
        ZooKeeperWeave.applyRuntimeTargetScope(target);
        PackManager.v().writeOutput();
    }

    private static ZooKeeperWeave.TargetMethod targetFromManifest(Path path)
            throws Exception {
        JsonObject manifest;
        try (Reader reader = Files.newBufferedReader(path)) {
            manifest = JsonParser.parseReader(reader).getAsJsonObject();
        }
        if (manifest.get("schemaVersion").getAsInt() != 1) {
            throw new IllegalArgumentException("unsupported ZooKeeper target manifest");
        }
        JsonArray targets = manifest.getAsJsonArray("targets");
        if (targets == null) throw new IllegalArgumentException("manifest has no targets");
        ZooKeeperWeave.TargetMethod selected = null;
        for (JsonElement element : targets) {
            JsonObject row = element.getAsJsonObject();
            if (!"THROW".equals(row.get("kind").getAsString())) continue;
            if (selected != null) throw new IllegalArgumentException(
                    "ZooKeeper manifest has multiple selected throws");
            selected = new ZooKeeperWeave.TargetMethod(
                    row.get("clazz").getAsString(),
                    row.get("method").getAsString(),
                    row.get("descriptor").getAsString());
        }
        if (selected == null) throw new IllegalArgumentException(
                "ZooKeeper manifest has no selected THROW target");
        boolean checkFound = false;
        for (JsonElement element : targets) {
            JsonObject row = element.getAsJsonObject();
            if ("BRANCH".equals(row.get("kind").getAsString())
                    && selected.clazz.equals(row.get("clazz").getAsString())
                    && selected.method.equals(row.get("method").getAsString())
                    && selected.descriptor.equals(row.get("descriptor").getAsString())) {
                checkFound = true;
            }
        }
        if (!checkFound) throw new IllegalArgumentException(
                "selected THROW has no same-method check branch in manifest");
        return selected;
    }
}
