package edu.uva.liftlab.graphchecker.runtime;

/** Source attribution bridge for the optional HDFS SASL adapter. */
public final class MalloryOriginalHdfsSourceRoots {
    private MalloryOriginalHdfsSourceRoots() { }

    /**
     * Associate a handshake or streamer object with the exact source already
     * active on this thread. No new source is invented if the turn is vacant.
     */
    public static boolean aliasCurrent(Object alias) {
        SourceRef source = RuntimeTraceContext.currentSource();
        if (source == null) return false;
        CausynthTraceRecorder.registerSource(alias, source.kind(),
                source.role(), source.id(), source.epoch());
        return true;
    }
}
