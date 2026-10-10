import edu.uva.liftlab.mallory.instrumentation.AgentConfig;
import edu.uva.liftlab.mallory.instrumentation.MalloryTransformer;
import edu.uva.liftlab.mallory.solr.SolrTransformer;
import edu.uva.liftlab.mallory.solr.aliasref.AliasValueTransformer;
import edu.uva.liftlab.mallory.solr.solr39.PreemptiveTransformer;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.jar.JarFile;

/** Weave the pinned SolrJ class in the real agent order and verify its load. */
public final class VerifyWovenClass {
  private static final String INTERNAL =
      "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";

  private static final class ChildFirst extends ClassLoader {
    private final byte[] woven;
    ChildFirst(ClassLoader parent, byte[] woven) { super(parent); this.woven = woven; }
    @Override protected Class<?> loadClass(String name, boolean resolve)
        throws ClassNotFoundException {
      if (!name.equals(INTERNAL.replace('/', '.'))) return super.loadClass(name, resolve);
      synchronized (getClassLoadingLock(name)) {
        Class<?> found = findLoadedClass(name);
        if (found == null) found = defineClass(name, woven, 0, woven.length);
        if (resolve) resolveClass(found);
        return found;
      }
    }
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("solrj.jar agent.properties");
    byte[] original;
    try (JarFile jar = new JarFile(args[0])) {
      try (InputStream stream = jar.getInputStream(jar.getEntry(INTERNAL + ".class"))) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        int count;
        while ((count = stream.read(chunk)) != -1) bytes.write(chunk, 0, count);
        original = bytes.toByteArray();
      }
    }
    AgentConfig config = AgentConfig.load("config=" + args[1]);
    byte[] core = new MalloryTransformer(config).transform(
        VerifyWovenClass.class.getClassLoader(), INTERNAL, null, null, original);
    if (core == null) throw new IllegalStateException("core did not weave selected class");
    byte[] solr = new SolrTransformer().transform(
        VerifyWovenClass.class.getClassLoader(), INTERNAL, null, null, core);
    if (solr == null) throw new IllegalStateException("Solr adapter did not weave selected class");
    byte[] refs = new AliasValueTransformer().transform(
        VerifyWovenClass.class.getClassLoader(), INTERNAL, null, null, solr);
    if (refs == null) throw new IllegalStateException("exact reference adapter did not weave class");
    byte[] gated = new PreemptiveTransformer().transform(
        VerifyWovenClass.class.getClassLoader(), INTERNAL, null, null, refs);
    if (gated == null) throw new IllegalStateException("resource gate did not weave class");
    Class<?> verified = Class.forName(INTERNAL.replace('/', '.'), false,
        new ChildFirst(VerifyWovenClass.class.getClassLoader(), gated));
    if (verified.getDeclaredMethods().length == 0) throw new IllegalStateException("empty class");
    MessageDigest md = MessageDigest.getInstance("SHA-256");
    StringBuilder sha = new StringBuilder();
    for (byte b : md.digest(gated)) sha.append(String.format("%02x", b & 255));
    System.out.println("WOVEN_CLASS_VERIFY_OK original=" + original.length
        + " gated=" + gated.length + " sha256=" + sha);
  }
}
