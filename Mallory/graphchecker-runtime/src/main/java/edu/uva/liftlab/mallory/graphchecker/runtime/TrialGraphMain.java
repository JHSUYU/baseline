package edu.uva.liftlab.mallory.graphchecker.runtime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Usage: trace graph feedback targetSite [priorTrace|-] [staticScopeMap]. */
public final class TrialGraphMain {
    private TrialGraphMain() { }

    public static void main(String[] args) throws Exception {
        if (args.length < 4 || args.length > 6) {
            System.err.println("usage: TrialGraphMain trace graph feedback targetSite [priorTrace|-] [staticScopeMap]");
            System.exit(2);
        }
        TrialGraph graph = TrialGraph.read(Paths.get(args[0]));
        TrialGraph prior = args.length >= 5 && !"-".equals(args[4]) ?
                TrialGraph.read(Paths.get(args[4])) : null;
        StaticScope staticScope = args.length == 6 ? StaticScope.read(Paths.get(args[5])) : null;
        Path graphFile = Paths.get(args[1]);
        Path feedbackFile = Paths.get(args[2]);
        graph.write(graphFile);
        Path parent = feedbackFile.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        Files.write(feedbackFile,
                (graph.feedback(args[3], prior, staticScope).toString() + "\n")
                        .getBytes(StandardCharsets.UTF_8));
    }
}
