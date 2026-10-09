import java.io.File;

public final class QjmRpcActorSmoke {
  public static void main(String[] args) {
    QjmRpcActor.resetForSmoke();
    if (QjmRpcActor.resolve(21001) != null) throw new AssertionError("unknown port matched");
    QjmRpcActor.registerPort(21001, "/tmp/test/journalnode-2");
    if (!"journalnode-2".equals(QjmRpcActor.resolve(21001))) throw new AssertionError("peer mismatch");
    QjmRpcActor.registerPort(21002, "/tmp/test/not-a-journalnode");
    if (QjmRpcActor.resolve(21002) != null) throw new AssertionError("unknown actor matched");
    QjmRpcActor.bindTarget(new File("/tmp/test/journalnode-2/test-journal/current"));
    if (!QjmRpcActor.resolve(21001).equals(QjmRpcActor.targetActor()))
      throw new AssertionError("target actor mismatch");
    QjmRpcActor.registerPort(21001, "/tmp/test/journalnode-1");
    if (QjmRpcActor.resolve(21001) != null) throw new AssertionError("ambiguous port matched");
    System.out.println("QJM actor smoke PASS");
  }
}
