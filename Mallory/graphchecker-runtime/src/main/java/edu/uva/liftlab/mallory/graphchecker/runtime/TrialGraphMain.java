package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonParser;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Usage: trace graph feedback targetSiteOrJsonArray [priorTrace|-] [staticScopeMap]. */
public final class TrialGraphMain {
    private TrialGraphMain() { }

    static List<String> targetSites(String argument) {
        if (!argument.startsWith("[")) return Collections.singletonList(argument);
        JsonArray array = new JsonParser().parse(argument).getAsJsonArray();
        List<String> sites = new ArrayList<>();
        for (JsonElement item : array) {
            if (!item.isJsonPrimitive() || !item.getAsJsonPrimitive().isString()) {
                throw new IllegalArgumentException("target site array needs string IDs");
            }
            sites.add(item.getAsString());
        }
        return sites;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 4 || args.length > 6) {
            System.err.println("usage: TrialGraphMain trace graph feedback targetSiteOrJsonArray [priorTrace|-] [staticScopeMap]");
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
                (graph.feedback(targetSites(args[3]), prior, staticScope).toString() + "\n")
                        .getBytes(StandardCharsets.UTF_8));
    }
}
