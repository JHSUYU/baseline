package org.apache.solr.cloud;

import org.apache.solr.common.cloud.ZkStateReader;

public class ZkController {
    private final Container cc;
    public final ZkStateReader zkStateReader;

    public ZkController(String home, ZkStateReader reader) {
        cc = new Container(home);
        zkStateReader = reader;
    }

    public static class Container {
        private final String home;

        Container(String home) { this.home = home; }

        public String getSolrHome() { return home; }
    }
}
