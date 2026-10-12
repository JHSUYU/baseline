package edu.uva.liftlab.crashfuzz.runtime;

/** Stable actor identity for replay across fresh embedded-cluster runs. */
final class OccurrenceIdentity {
    private OccurrenceIdentity() {}

    static String stable(String address) {
        int nodeEnd = address.indexOf('/');
        int siteStart = address.lastIndexOf("/<");
        if (nodeEnd < 0 || siteStart <= nodeEnd) return address;
        String actor = address.substring(nodeEnd + 1, siteStart);
        if (actor.startsWith("BP-") && actor.contains(" heartbeating to ")) {
            actor = "BPServiceActor heartbeating";
        }
        actor = actor.replaceAll("@[0-9a-fA-F]{3,}", "@instance")
                .replaceAll("(?i)\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\b", "uuid")
                .replaceAll("\\bBP-[0-9]+-[^\\s:]+-[0-9]+\\b", "BP-instance")
                .replaceAll("\\bblk_[0-9]+_[0-9]+\\b", "blk-instance")
                .replaceAll("((?:[0-9]{1,3}\\.){3}[0-9]{1,3}):[0-9]{2,5}\\b", "$1:port");
        return address.substring(0, nodeEnd + 1) + actor
                + address.substring(siteStart);
    }
}
