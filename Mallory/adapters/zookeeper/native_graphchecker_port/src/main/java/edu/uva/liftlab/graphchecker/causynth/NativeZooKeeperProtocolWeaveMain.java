package edu.uva.liftlab.graphchecker.causynth;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.Collections;
import soot.G;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.options.Options;

/** A post-pass on an isolated original-GraphChecker woven class tree. */
public final class NativeZooKeeperProtocolWeaveMain {
    private static final String[] CLIENT_CLASSES = {
        "org.apache.zookeeper.ClientCnxnSocketNIO",
        "org.apache.zookeeper.server.NIOServerCnxn"
    };
    private static final String[] QUORUM_CLASSES = {
        "org.apache.zookeeper.server.quorum.LearnerHandler",
        "org.apache.zookeeper.server.quorum.Learner",
        "org.apache.zookeeper.server.quorum.Follower",
        "org.apache.zookeeper.server.quorum.ObserverMaster"
    };

    private NativeZooKeeperProtocolWeaveMain() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2 && args.length != 3) throw new IllegalArgumentException(
                "usage: NativeZooKeeperProtocolWeaveMain "
                + "<original-woven-class-tree> <immutable-dependency-classpath> "
                + "[client|quorum|all]");
        String mode = args.length == 3 ? args[2] : "all";
        if (!"client".equals(mode) && !"quorum".equals(mode)
                && !"all".equals(mode)) {
            throw new IllegalArgumentException("unknown protocol mode " + mode);
        }
        boolean client = !"quorum".equals(mode);
        boolean quorum = !"client".equals(mode);
        java.util.List<String> selected = new java.util.ArrayList<String>();
        if (client) selected.addAll(Arrays.asList(CLIENT_CLASSES));
        if (quorum) selected.addAll(Arrays.asList(QUORUM_CLASSES));
        Path woven = Paths.get(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(woven)) throw new IllegalArgumentException(
                "woven classes missing: " + woven);
        Path scratch = Files.createTempDirectory(woven.getParent(),
                "native-zk-protocol-");
        Path output = scratch.resolve("output");
        Files.createDirectories(output);
        for (String name : selected) {
            Path relative = Paths.get(name.replace('.', '/') + ".class");
            Path source = woven.resolve(relative);
            if (!Files.isRegularFile(source)) throw new IllegalStateException(
                    "selected ZooKeeper class absent: " + source);
        }
        G.reset();
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_prepend_classpath(true);
        Options.v().set_process_dir(Collections.singletonList(woven.toString()));
        Options.v().set_soot_classpath(woven
                + File.pathSeparator + args[1] + File.pathSeparator
                + System.getProperty("java.class.path"));
        Options.v().set_output_dir(output.toString());
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_keep_line_number(true);
        Options.v().set_whole_program(true);
        for (String name : Arrays.asList(
                "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperClientTraceBridge",
                "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperProposalTraceBridge",
                "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperHandshakeTraceBridge")) {
            Scene.v().addBasicClass(name, SootClass.SIGNATURES);
        }
        Scene.v().loadNecessaryClasses();
        // Soot's writer emits no Code attribute for a concrete method left
        // at signature resolution.  Materialize only the classes this
        // protocol pass replaces; every other class remains byte-identical.
        for (String name : selected) {
            SootClass type = Scene.v().getSootClass(name);
            for (SootMethod method : type.getMethods()) {
                if (method.isConcrete()) method.retrieveActiveBody();
            }
        }
        NativeZooKeeperProtocolWeave.apply(client, quorum);
        PackManager.v().writeOutput();
        for (String name : selected) {
            Path relative = Paths.get(name.replace('.', '/') + ".class");
            Path source = output.resolve(relative);
            if (!Files.isRegularFile(source)) throw new IllegalStateException(
                    "Soot did not emit selected class: " + source);
            Files.copy(source, woven.resolve(relative),
                    StandardCopyOption.REPLACE_EXISTING);
        }
        System.out.println("native ZooKeeper protocol classes=" + selected.size()
                + " mode=" + mode);
    }
}
