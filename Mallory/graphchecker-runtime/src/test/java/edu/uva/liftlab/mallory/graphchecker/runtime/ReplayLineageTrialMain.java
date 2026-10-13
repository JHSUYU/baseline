package edu.uva.liftlab.mallory.graphchecker.runtime;

/** A fresh-JVM replay fixture with a caller-chosen, trial-specific RPC ID. */
public final class ReplayLineageTrialMain {
    private ReplayLineageTrialMain() { }

    public static void main(String[] args) {
        if (args.length != 2) throw new IllegalArgumentException("correlation and trace path");
        System.setProperty("mallory.graphchecker.trace.file", args[1]);
        Object client = new Object();
        Object server = new Object();
        Object next = new Object();
        MessageDoors.registerNode(client, "TEST", "CLIENT", "client");
        MessageDoors.registerNode(server, "TEST", "SERVER", "server");
        MessageDoors.registerNode(next, "TEST", "SERVER", "next");
        MessageDoors.startRecording();
        long request = MessageDoors.beginRequest(client, "operation");
        MessageDoors.enterRegion("R.client", "client-entry", 0, client);
        MessageDoors.Outbound first = MessageDoors.prepareOutbound(
                "RPC", args[0], "0", MessageDoors.REQUEST, client, null);
        MessageDoors.sent(first);
        MessageDoors.exitRegion("R.client");
        MessageDoors.endRequest(request, "operation");

        MessageDoors.Inbound inbound = MessageDoors.inbound(first.trace, "",
                "RPC", args[0], "0", MessageDoors.REQUEST, server, false);
        MessageDoors.enterRegion("R.server", "server-entry", 0, server);
        MessageDoors.FaultDoorHit serverHit = MessageDoors.faultDoorHit("server-io", server);
        MessageDoors.Outbound second = MessageDoors.prepareOutbound(
                "RPC", args[0] + ":forward", "0", MessageDoors.REQUEST, server, null);
        MessageDoors.sent(second);
        MessageDoors.exitRegion("R.server");
        MessageDoors.endInbound(inbound);

        MessageDoors.Inbound forwarded = MessageDoors.inbound(second.trace, "",
                "RPC", args[0] + ":forward", "0", MessageDoors.REQUEST, next, false);
        MessageDoors.enterRegion("R.next", "next-entry", 0, next);
        MessageDoors.FaultDoorHit nextHit = MessageDoors.faultDoorHit("next-io", next);
        MessageDoors.targetCheck("target", next, "FALSE");
        MessageDoors.exitRegion("R.next");
        MessageDoors.endInbound(forwarded);
        MessageDoors.stopRecording();
        System.out.println(serverHit.occurrenceId);
        System.out.println(serverHit.replayOccurrenceId);
        System.out.println(nextHit.occurrenceId);
        System.out.println(nextHit.replayOccurrenceId);
    }
}
