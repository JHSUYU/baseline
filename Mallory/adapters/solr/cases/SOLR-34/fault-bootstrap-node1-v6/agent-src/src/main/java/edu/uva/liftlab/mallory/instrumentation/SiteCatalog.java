package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.Gson;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/** Static sites that were successfully woven into loaded application classes. */
final class SiteCatalog {
  private final BufferedWriter writer;
  private final Gson gson = new Gson();

  SiteCatalog(File path) throws IOException {
    File parent = path.getAbsoluteFile().getParentFile();
    if (parent != null && !parent.exists() && !parent.mkdirs())
      throw new IOException("Cannot create site catalog directory " + parent);
    writer = new BufferedWriter(new OutputStreamWriter(
        new FileOutputStream(path, false), StandardCharsets.UTF_8));
  }

  synchronized void append(List<Map<String, Object>> sites) throws IOException {
    for (Map<String, Object> site : sites) {
      writer.write(gson.toJson(site));
      writer.newLine();
    }
    writer.flush();
  }
}
