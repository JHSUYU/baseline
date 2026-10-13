package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

public final class FixtureExternalConstructorJUnit {
    @Test public void originalReaderConstructor() throws Exception {
        Path file = Files.createTempFile("mallory-reader-", ".txt");
        Files.write(file, "hello\n".getBytes(StandardCharsets.UTF_8));
        try {
            assertEquals("hello", new FixtureExternalConstructor().firstLine(file));
        } finally {
            Files.deleteIfExists(file);
        }
    }
}
