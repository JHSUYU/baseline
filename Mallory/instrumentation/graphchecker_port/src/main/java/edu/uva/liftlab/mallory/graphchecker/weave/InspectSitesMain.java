package edu.uva.liftlab.mallory.graphchecker.weave;

import java.io.File;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import soot.Body;
import soot.BodyTransformer;
import soot.G;
import soot.PackManager;
import soot.Scene;
import soot.Transform;
import soot.Unit;
import soot.options.Options;

/** Inspect unit indices at the same jtp phase used by {@link WeaveMain}. */
public final class InspectSitesMain {
    private InspectSitesMain() { }

    public static void main(String[] args) {
        if (args.length != 4) {
            throw new IllegalArgumentException(
                    "usage: InspectSitesMain <classes-dir> <dependency-classpath> <class> <method+JVM-descriptor>");
        }
        G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_keep_line_number(true);
        Options.v().set_keep_offset(true);
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_process_dir(Collections.singletonList(args[0]));
        Options.v().set_soot_classpath(args[0] + File.pathSeparator + args[1]);
        AtomicBoolean found = new AtomicBoolean();
        PackManager.v().getPack("jtp").add(new Transform("jtp.malloryInspect", new BodyTransformer() {
            @Override protected void internalTransform(Body body, String phase,
                                                       Map<String, String> options) {
                if (!body.getMethod().getDeclaringClass().getName().equals(args[2])
                        || !(body.getMethod().getName()
                                + SootSiteWeaver.descriptor(body.getMethod())).equals(args[3])) {
                    return;
                }
                found.set(true);
                int index = 0;
                Body inspected = Boolean.getBoolean("mallory.inspect.clone")
                        ? (Body) body.clone() : body;
                for (Unit unit : inspected.getUnits()) {
                    System.out.println(index++ + "\t" + unit.getJavaSourceStartLineNumber()
                            + "\t" + unit.getClass().getSimpleName() + "\t" + unit);
                }
            }
        }));
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();
        if (!found.get()) throw new IllegalArgumentException(
                "method missing: " + args[2] + "#" + args[3]);
    }
}
