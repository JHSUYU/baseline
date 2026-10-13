import edu.uva.liftlab.graphchecker.contract.SessionReader;
import java.nio.file.Paths;

/** Ensures the published target and decision resolve through original SessionReader. */
public final class ReadNativeSession {
    public static void main(String[] args) throws Exception {
        SessionReader session = SessionReader.read(Paths.get(args[0]), args[1]);
        if (!session.incomplete().isEmpty()) throw new IllegalStateException(session.incomplete());
        if (session.activations().size() != 1 || session.decisions().size() != 1
                || session.targets().size() != 1 || !session.gaps().isEmpty()) {
            throw new IllegalStateException("wrong native row counts");
        }
        String branch = session.decisions().get(0).term();
        String target = session.targets().get(0).phiTerm();
        if (branch.isEmpty() || target.isEmpty()
                || session.expressions().expression(branch) == null
                || session.expressions().expression(target) == null) {
            throw new IllegalStateException("native expression references missing");
        }
        System.out.println("SESSION_READER_OK branch=" + branch + " target=" + target);
    }
}
