package example.tiny;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import org.greygraph.baseline.agent.Hook;

/** Two-process protocol fixture: B asks A, and the check runs on B. */
public final class Node {
    private Node() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("role A or B");
        if ("A".equals(args[0])) serveA();
        else if ("B".equals(args[0])) serveB();
        else throw new IllegalArgumentException(args[0]);
    }

    private static void serveA() throws Exception {
        try (ServerSocket server = new ServerSocket(5051)) {
            System.out.println("READY A");
            while (true) {
                try (Socket peer = server.accept()) {
                    String request = new BufferedReader(new InputStreamReader(
                            peer.getInputStream(), StandardCharsets.UTF_8))
                            .readLine();
                    if (request == null) continue;
                    Hook.messageReceive("req:" + request);
                    Hook.messageSend("resp:" + request);
                    OutputStream output = peer.getOutputStream();
                    output.write(("OK " + request + "\n").getBytes(
                            StandardCharsets.UTF_8));
                    output.flush();
                }
            }
        }
    }

    private static void serveB() throws Exception {
        try (ServerSocket server = new ServerSocket(5052)) {
            System.out.println("READY B");
            while (true) {
                try (Socket trigger = server.accept()) {
                    String request = new BufferedReader(new InputStreamReader(
                            trigger.getInputStream(), StandardCharsets.UTF_8))
                            .readLine();
                    if (request == null) continue;
                    boolean fatal = true;
                    try (Socket peer = new Socket("adhocfuzz-tiny-a", 5051)) {
                        Hook.messageSend("req:" + request);
                        OutputStream output = peer.getOutputStream();
                        output.write((request + "\n").getBytes(
                                StandardCharsets.UTF_8));
                        output.flush();
                        String answer = new BufferedReader(new InputStreamReader(
                                peer.getInputStream(), StandardCharsets.UTF_8))
                                .readLine();
                        if (answer != null) {
                            Hook.messageReceive("resp:" + request);
                            fatal = !("OK " + request).equals(answer);
                        }
                    } catch (Exception unavailable) {
                        fatal = true;
                    }
                    Hook.target("example/tiny/Node#responseCheck", fatal);
                    OutputStream reply = trigger.getOutputStream();
                    reply.write((fatal ? "FAIL\n" : "OK\n").getBytes(
                            StandardCharsets.UTF_8));
                    reply.flush();
                }
            }
        }
    }
}
