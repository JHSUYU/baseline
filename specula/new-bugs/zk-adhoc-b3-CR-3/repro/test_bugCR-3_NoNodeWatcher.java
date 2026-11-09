// Observation only: a JDI client that records where NoNodeException is thrown in the test JVM, because
// FinalRequestProcessor catches it (line 604-605) and sends only an error code. It changes no state.
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.util.*;

public class NoNodeWatcher {
    public static void main(String[] a) throws Exception {
        AttachingConnector conn = null;
        for (AttachingConnector c : Bootstrap.virtualMachineManager().attachingConnectors()) {
            if (c.name().equals("com.sun.jdi.SocketAttach")) { conn = c; }
        }
        Map<String, Connector.Argument> args = conn.defaultArguments();
        args.get("hostname").setValue("127.0.0.1");
        args.get("port").setValue(a[0]);
        VirtualMachine vm = null;
        for (int i = 0; i < 1200 && vm == null; i++) {
            try { vm = conn.attach(args); } catch (java.io.IOException e) { Thread.sleep(250); }
        }
        if (vm == null) { System.out.println("[watch] could not attach"); System.exit(2); }
        String type = "org.apache.zookeeper.KeeperException$NoNodeException";
        EventRequestManager erm = vm.eventRequestManager();
        ClassPrepareRequest cpr = erm.createClassPrepareRequest();
        cpr.addClassFilter(type);
        cpr.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        cpr.enable();
        vm.resume();
        Map<String, Integer> counts = new TreeMap<>();
        try {
            while (true) {
                EventSet set = vm.eventQueue().remove();
                for (Event e : set) {
                    if (e instanceof ClassPrepareEvent) {
                        ExceptionRequest er = erm.createExceptionRequest(((ClassPrepareEvent) e).referenceType(), true, true);
                        er.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
                        er.enable();
                    } else if (e instanceof ExceptionEvent) {
                        ExceptionEvent x = (ExceptionEvent) e;
                        Location l = x.location();
                        String at = l.declaringType().name() + "." + l.method().name() + ":" + l.lineNumber();
                        counts.merge(at, 1, Integer::sum);
                        boolean target = l.declaringType().name().endsWith(".FinalRequestProcessor") && l.method().name().equals("handleGetDataRequest");
                        if (target || counts.get(at) == 1) {
                            StringBuilder sb = new StringBuilder("[watch] " + System.currentTimeMillis() + (target ? " TARGET " : " other ") + x.exception().referenceType().name() + " thread=" + x.thread().name());
                            List<StackFrame> frames = x.thread().frames();
                            if (target) {
                                try {
                                    StackFrame f = frames.get(0);
                                    sb.append(" path=").append(f.getValue(f.visibleVariableByName("path"))).append(" n=").append(f.getValue(f.visibleVariableByName("n")));
                                } catch (AbsentInformationException noVars) { sb.append(" (no local var info)"); }
                            }
                            for (int i = 0; i < Math.min(4, frames.size()); i++) {
                                Location fl = frames.get(i).location();
                                sb.append("\n[watch]    at ").append(fl.declaringType().name()).append('.').append(fl.method().name()).append('(').append(fl.sourceName()).append(':').append(fl.lineNumber()).append(')');
                            }
                            System.out.println(sb);
                        }
                    } else if (e instanceof VMDisconnectEvent || e instanceof VMDeathEvent) {
                        throw new VMDisconnectedException();
                    }
                }
                set.resume();
            }
        } catch (VMDisconnectedException done) {
            System.out.println("[watch] NoNodeException throw sites: " + counts);
        }
    }
}
