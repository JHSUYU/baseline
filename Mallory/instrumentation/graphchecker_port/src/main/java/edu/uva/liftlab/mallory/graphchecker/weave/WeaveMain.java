package edu.uva.liftlab.mallory.graphchecker.weave;

import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.Collections;
import soot.G;
import soot.PackManager;
import soot.Scene;
import soot.Transform;
import soot.options.Options;

/** Offline Soot class rewrite; run once against the original JUnit build. */
public final class WeaveMain {
    private WeaveMain() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            throw new IllegalArgumentException("usage: WeaveMain <sites.json> <input-classes> <output-classes> <dependency-classpath>");
        }
        weave(Paths.get(args[0]), Paths.get(args[1]), Paths.get(args[2]), args[3]);
    }

    public static void weave(Path manifestFile, Path input, Path output,
                             String dependencyClasspath) throws Exception {
        SiteManifest manifest = SiteManifest.read(manifestFile);
        String actualClasspathSha = sha256(dependencyClasspath);
        if (manifest.sootDependencyClasspathSha256 != null
                && !manifest.sootDependencyClasspathSha256.equals(actualClasspathSha)) {
            throw new IllegalArgumentException("Soot dependency classpath differs from static scope manifest: expected "
                    + manifest.sootDependencyClasspathSha256 + ", actual " + actualClasspathSha);
        }
        Files.createDirectories(output);
        G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_keep_line_number(true);
        Options.v().set_keep_offset(true);
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_output_dir(output.toString());
        Options.v().set_process_dir(Collections.singletonList(input.toString()));
        Options.v().set_soot_classpath(input + File.pathSeparator + dependencyClasspath);
        Scene.v().addBasicClass(TraceHooks.class.getName(), soot.SootClass.SIGNATURES);
        Scene.v().addBasicClass("java.lang.Throwable", soot.SootClass.SIGNATURES);
        SootSiteWeaver weaver = new SootSiteWeaver(manifest);
        PackManager.v().getPack("jtp").add(new Transform("jtp.malloryGraphChecker", weaver));
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();
        weaver.verifyAllSites();
        PackManager.v().writeOutput();
    }

    private static String sha256(String value) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder(digest.length * 2);
        for (byte element : digest) result.append(String.format("%02x", element & 0xff));
        return result.toString();
    }
}
