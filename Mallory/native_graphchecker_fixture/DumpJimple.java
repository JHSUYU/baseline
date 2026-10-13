import edu.uva.liftlab.graphchecker.runtime.PlainFixture;
import java.io.File;
import soot.Body;
import soot.G;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.options.Options;

/** Prints original jtp-entry units, before any instrumentation changes them. */
public final class DumpJimple {
    public static void main(String[] args) {
        G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_soot_classpath(args[0] + File.pathSeparator + args[1]);
        SootClass clazz = Scene.v().loadClassAndSupport(PlainFixture.class.getName());
        clazz.setApplicationClass();
        Scene.v().loadNecessaryClasses();
        SootMethod method = clazz.getMethod("int run(int)");
        Body body = method.retrieveActiveBody();
        int index = 0;
        for (Unit unit : body.getUnits()) {
            System.out.println(index++ + "\t" + unit.getClass().getSimpleName()
                    + "\t" + unit);
        }
    }
}
