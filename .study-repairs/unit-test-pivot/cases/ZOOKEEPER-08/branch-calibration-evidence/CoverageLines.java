import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.ICounter;
import org.jacoco.core.tools.ExecFileLoader;

public final class CoverageLines {
    public static void main(String[] args) throws Exception {
        ExecFileLoader data = new ExecFileLoader();
        data.load(new File(args[0]));
        CoverageBuilder coverage = new CoverageBuilder();
        new Analyzer(data.getExecutionDataStore(), coverage).analyzeAll(new File(args[1]));
        for (IClassCoverage clazz : coverage.getClasses()) {
            System.out.println("class=" + clazz.getName());
            for (int line = 160; line <= 194; ++line) {
                int status = clazz.getLine(line).getStatus();
                if (status != ICounter.EMPTY) {
                    System.out.println(line + ": status=" + status
                        + " instructions=" + clazz.getLine(line).getInstructionCounter().getCoveredCount()
                        + "/" + clazz.getLine(line).getInstructionCounter().getTotalCount()
                        + " branches=" + clazz.getLine(line).getBranchCounter().getCoveredCount()
                        + "/" + clazz.getLine(line).getBranchCounter().getTotalCount());
                }
            }
        }
    }
}
