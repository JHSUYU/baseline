package edu.uva.liftlab.graphchecker.causynth;

import org.junit.Test;

import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/** Bytecode use-def identity, including a source-line-separated local throw. */
public final class ExceptionTargetLineResolverTest {
    private static final String SOURCE =
            "package fx;\n"
            + "import java.io.IOException;\n"
            + "public final class ThrowShapes {\n"
            + "  public static void local(boolean bad) throws IOException {\n"
            + "    if (bad) {\n"
            + "      IOException ive = new IOException(\"local\");\n"
            + "      System.err.println(ive.getMessage());\n"
            + "      throw ive;\n"
            + "    }\n"
            + "  }\n"
            + "  public static void copied() throws IOException {\n"
            + "    IOException original = new IOException(\"copied\");\n"
            + "    IOException alias = original;\n"
            + "    throw alias;\n"
            + "  }\n"
            + "  public static void direct() throws IOException {\n"
            + "    throw new IOException(\"direct\");\n"
            + "  }\n"
            + "  public static void nestedDirect() throws IOException {\n"
            + "    throw new IOException(new IOException(\"cause\"));\n"
            + "  }\n"
            + "  public static void otherObject() throws IOException {\n"
            + "    IOException first = new IOException(\"first\");\n"
            + "    IOException second = new IOException(\"second\");\n"
            + "    throw second;\n"
            + "  }\n"
            + "  public static void replaced() throws IOException {\n"
            + "    IOException first = new IOException(\"replaced-first\");\n"
            + "    first = new IOException(\"replaced-second\");\n"
            + "    throw first;\n"
            + "  }\n"
            + "  public static void merged(boolean left) throws IOException {\n"
            + "    IOException selected;\n"
            + "    if (left) selected = new IOException(\"left\");\n"
            + "    else selected = new IOException(\"right\");\n"
            + "    throw selected;\n"
            + "  }\n"
            + "  public static void passedOnly() throws IOException {\n"
            + "    IOException merelyLogged = new IOException(\"passed\");\n"
            + "    System.err.println(merelyLogged);\n"
            + "    throw new IOException(\"actual\");\n"
            + "  }\n"
            + "}\n";

    @Test public void resolvesDirectAndLocalOnlyWhenConstructedObjectReachesThrow()
            throws Exception {
        Path root = Files.createTempDirectory("target-local-throw-");
        Path source = root.resolve("fx/ThrowShapes.java");
        Files.createDirectories(source.getParent());
        Files.write(source, SOURCE.getBytes(StandardCharsets.UTF_8));
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        assertEquals(0, compiler.run(null, null, null, "-g", "-d",
                root.toString(), source.toString()));
        assertMethod(root, "new IOException(\"local\")", "local", 0);
        assertMethod(root, "new IOException(\"copied\")", "copied", 0);
        assertMethod(root, "new IOException(\"direct\")", "direct", 0);
        assertMethod(root, "new IOException(new IOException(\"cause\"))",
                "nestedDirect", 0);
        assertMethod(root, "new IOException(\"second\")", "otherObject", 1);
        assertUnresolved(root, "new IOException(\"first\")");
        assertUnresolved(root, "new IOException(\"replaced-first\")");
        assertUnresolved(root, "new IOException(\"left\")");
        assertUnresolved(root, "new IOException(\"right\")");
        assertUnresolved(root, "new IOException(\"passed\")");
    }

    private static void assertMethod(Path root, String marker,
                                     String method, int ordinal)
            throws Exception {
        ExceptionTargetSite site = ExceptionTargetLineResolver.locate(
                Collections.singletonList(root.toString()), target(marker));
        assertEquals(method, site.methodName);
        assertEquals(ordinal, site.exceptionConstructionOrdinal);
        assertEquals("java.io.IOException", site.exceptionClass);
    }

    private static void assertUnresolved(Path root, String marker)
            throws Exception {
        try {
            ExceptionTargetLineResolver.locate(
                    Collections.singletonList(root.toString()), target(marker));
            fail("same method and exception class must not substitute for the thrown object");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("TARGET_LINE_UNRESOLVED"));
        }
    }

    private static ExceptionTargetLineResolver.TargetLine target(String marker) {
        int offset = SOURCE.indexOf(marker);
        if (offset < 0) throw new AssertionError(marker);
        int line = 1;
        for (int i = 0; i < offset; i++) if (SOURCE.charAt(i) == '\n') line++;
        return new ExceptionTargetLineResolver.TargetLine(
                marker, "fx.ThrowShapes", line, "IOException");
    }
}
