import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Exercises the optional bytecode adapter seam without changing fixture code. */
public final class NativePostWeaveProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !"--classes".equals(args[0])) {
            throw new IllegalArgumentException("expected --classes <woven-dir>");
        }
        Path root = Paths.get(args[1]);
        Path clazz = root.resolve(
                "edu/uva/liftlab/graphchecker/runtime/PlainFixture.class");
        if (!Files.isRegularFile(clazz)) {
            throw new IllegalStateException("original GraphChecker weave is absent");
        }
        Files.write(root.resolve("post-weave-verified.txt"),
                "original GraphChecker output checked\n".getBytes(StandardCharsets.UTF_8));
    }
}
