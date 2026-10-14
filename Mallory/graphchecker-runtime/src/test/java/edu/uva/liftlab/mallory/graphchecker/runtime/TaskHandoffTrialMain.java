package edu.uva.liftlab.mallory.graphchecker.runtime;

/** Separate JVM so the trace writer starts on this fixture's own file. */
public final class TaskHandoffTrialMain {
    private TaskHandoffTrialMain() { }

    public static void main(String[] args) throws Exception {
        Object server = new Object();
        Object sameCarrier = new Object();
        MessageDoors.registerSource(server, "test", "server", "task-server", 0);
        if (MessageDoors.prepareTask("executor.submit", sameCarrier) != null) {
            throw new AssertionError("unrooted caller made a task ticket");
        }
        Thread ambient = new Thread(() -> {
            if (MessageDoors.prepareTask("executor.submit", sameCarrier) != null) {
                throw new AssertionError("unrooted worker made a task ticket");
            }
            MessageDoors.targetCheck("task-ambient", server, "healthy");
        });
        ambient.start();
        ambient.join();
        long request = MessageDoors.beginRequest(server, "test-task-handoff");
        for (int i = 0; i < 100; i++) {
            MessageDoors.enterRegion("R.deep." + i, "deep-call." + i,
                    i, server);
        }
        Object first = MessageDoors.prepareTask("executor.submit", sameCarrier);
        Object second = MessageDoors.prepareTask("executor.submit", sameCarrier);
        MessageDoors.prepareTask("executor.submit", sameCarrier); // rejected
        Thread worker = new Thread(() -> {
            long firstClaim = MessageDoors.claimTask(first, "EXECUTOR_TASK", "worker");
            MessageDoors.enterRegion("R.worker", "worker", 0);
            MessageDoors.targetCheck("task-first", null, "healthy");
            Object nested = MessageDoors.prepareTask("executor.submit", new Object());
            Thread child = new Thread(() -> {
                long nestedClaim = MessageDoors.claimTask(nested,
                        "EXECUTOR_TASK", "nested-worker");
                MessageDoors.enterRegion("R.nested", "nested", 0);
                MessageDoors.targetCheck("task-nested", null, "healthy");
                MessageDoors.exitRegion("R.nested");
                MessageDoors.endTask(nestedClaim);
            });
            child.start();
            try { child.join(); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new AssertionError(interrupted);
            }
            MessageDoors.exitRegion("R.worker");
            MessageDoors.endTask(firstClaim);
            if (MessageDoors.claimTask(first, "EXECUTOR_TASK", "duplicate") != 0L) {
                throw new AssertionError("one ticket claimed twice");
            }
            long secondClaim = MessageDoors.claimTask(second, "EXECUTOR_TASK", "worker");
            MessageDoors.enterRegion("R.worker", "worker", 0);
            MessageDoors.targetCheck("task-second", null, "healthy");
            MessageDoors.exitRegion("R.worker");
            MessageDoors.endTask(secondClaim);
        });
        worker.start();
        worker.join();
        for (int i = 99; i >= 0; i--) {
            MessageDoors.exitRegion("R.deep." + i);
        }
        MessageDoors.endRequest(request, "test-task-handoff");
    }
}
