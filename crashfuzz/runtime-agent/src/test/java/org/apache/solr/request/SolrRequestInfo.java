package org.apache.solr.request;

public class SolrRequestInfo {
    private static final ThreadLocal<SolrRequestInfo> CURRENT = new ThreadLocal<>();
    private final Request req;

    private SolrRequestInfo(String home) { req = new Request(home); }

    public static void setCurrent(String home) {
        if (home == null) CURRENT.remove();
        else CURRENT.set(new SolrRequestInfo(home));
    }

    public static SolrRequestInfo getRequestInfo() { return CURRENT.get(); }

    public Request getReq() { return req; }

    public static class Request {
        private final Core core;
        public Request(String home) { core = new Core(home); }
        public Core getCore() { return core; }
    }

    public static class Core {
        private final Container container;
        public Core(String home) { container = new Container(home); }
        public Container getCoreContainer() { return container; }
    }

    public static class Container {
        private final String home;
        public Container(String home) { this.home = home; }
        public String getSolrHome() { return home; }
    }
}
