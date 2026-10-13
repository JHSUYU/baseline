package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.nio.file.Path;

public final class FixtureExternalConstructor {
    public String firstLine(Path path) throws IOException {
        try (BufferedReader reader = new BufferedReader(
                new FileReader(path.toFile()))) {
            return reader.readLine();
        }
    }
}
