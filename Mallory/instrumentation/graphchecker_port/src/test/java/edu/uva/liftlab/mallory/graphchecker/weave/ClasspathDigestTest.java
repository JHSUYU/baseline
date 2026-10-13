package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertTrue;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.junit.Test;

public final class ClasspathDigestTest {
    @Test public void rejectsStaticScopeFromDifferentSootDependencies() throws Exception {
        Path work = Files.createTempDirectory(Paths.get("/dev/shm"), "mallory-gc-cp-");
        Path manifest = work.resolve("manifest.json");
        Files.write(manifest, ("{\"sootDependencyClasspathSha256\":\""
                + "0000000000000000000000000000000000000000000000000000000000000000"
                + "\"}").getBytes(StandardCharsets.UTF_8));
        try {
            WeaveMain.weave(manifest, work, work.resolve("woven"), "different.jar");
            throw new AssertionError("mismatched Soot dependency classpath was accepted");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("dependency classpath differs"));
        }
    }
}
