package edu.uva.liftlab.mallory.graphchecker.weave;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.lang.reflect.InvocationTargetException;
import java.util.ArrayList;
import java.util.List;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/**
 * Runs one original JUnit 4 test with its runner, rules, setup and teardown.
 * The recording window opens before JUnit starts cluster setup and closes
 * after it tears the cluster down.
 */
public final class JUnitTrialRunner {
    private JUnitTrialRunner() { }

    public static void main(String[] args) throws Throwable {
        if (args.length < 2 || args.length > 3) {
            throw new IllegalArgumentException("usage: JUnitTrialRunner <class> <method> [parameter-index]");
        }
        String method = args[1];
        String index = args.length == 3 ? args[2] : "";
        if (index.isEmpty() && method.endsWith("]")) {
            int opening = method.lastIndexOf('[');
            if (opening > 0) {
                index = method.substring(opening + 1, method.length() - 1);
                method = method.substring(0, opening);
            }
        }
        Class<?> clazz = Class.forName(args[0], true,
                Thread.currentThread().getContextClassLoader());
        String selected = index.isEmpty() ? method
                : selectParameterized(clazz, method, Integer.parseInt(index));
        Object anchor = new Object();
        MessageDoors.registerNode(anchor, "EXTERNAL_APP", "CLIENT",
                clazz.getName() + "#" + selected);
        MessageDoors.startRecording();
        long root = MessageDoors.beginRequest(anchor, selected);
        try {
            Result result = new JUnitCore().run(Request.method(clazz, selected));
            Throwable failure = null;
            for (Failure item : result.getFailures()) {
                if (failure == null) failure = item.getException();
                else failure.addSuppressed(item.getException());
            }
            if (result.getRunCount() != 1 || result.getIgnoreCount() != 0) {
                IllegalStateException count = new IllegalStateException(
                        "JUnit ran " + result.getRunCount() + " and ignored "
                                + result.getIgnoreCount() + " tests");
                if (failure == null) failure = count;
                else failure.addSuppressed(count);
            }
            if (failure != null) throw failure;
        } finally {
            MessageDoors.endRequest(root, selected);
            MessageDoors.stopRecording();
        }
    }

    private static String selectParameterized(Class<?> clazz, String method,
                                              int index) {
        if (index < 0) throw new IllegalArgumentException("negative parameter index");
        List<String> methods = new ArrayList<>();
        gather(Request.aClass(clazz).getRunner().getDescription(), method, methods);
        if (index >= methods.size()) {
            throw new IllegalArgumentException("parameter " + index + " absent from "
                    + clazz.getName() + "#" + method);
        }
        return methods.get(index);
    }

    private static void gather(Description description, String method,
                               List<String> names) {
        if (description.getChildren().isEmpty()) {
            String name = description.getMethodName();
            if (name != null && name.startsWith(method + "[")) names.add(name);
            return;
        }
        for (Description child : description.getChildren()) gather(child, method, names);
    }
}
