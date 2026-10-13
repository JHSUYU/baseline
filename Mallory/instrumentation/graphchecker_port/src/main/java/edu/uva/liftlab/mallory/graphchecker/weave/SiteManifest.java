package edu.uva.liftlab.mallory.graphchecker.weave;

import com.google.gson.Gson;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Declarative selected sites. Class and JVM descriptor disambiguate overloads. */
public final class SiteManifest {
    public List<Region> regions = new ArrayList<>();
    public List<Target> targets = new ArrayList<>();
    public List<Coverage> coverage = new ArrayList<>();
    public List<Frames> frames = new ArrayList<>();
    public List<Door> doors = new ArrayList<>();
    /** Static MAY accesses only; execution emits a gap until exact mediation exists. */
    public List<StateCandidate> stateCandidates = new ArrayList<>();
    /** Optional full SHA-256 of the exact Soot dependency classpath string. */
    public String sootDependencyClasspathSha256;
    /** NONE, MALLORY_PROBE, or MALLORY_GC_FAULT_PLAN. */
    public String faultController = "NONE";

    public static SiteManifest read(Path path) throws IOException {
        try (Reader input = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            SiteManifest result = new Gson().fromJson(input, SiteManifest.class);
            if (result == null) throw new IllegalArgumentException("empty site manifest");
            if (result.regions == null) result.regions = new ArrayList<>();
            if (result.targets == null) result.targets = new ArrayList<>();
            if (result.coverage == null) result.coverage = new ArrayList<>();
            if (result.frames == null) result.frames = new ArrayList<>();
            if (result.doors == null) result.doors = new ArrayList<>();
            if (result.stateCandidates == null) result.stateCandidates = new ArrayList<>();
            result.validate();
            return result;
        }
    }

    private void validate() {
        if (sootDependencyClasspathSha256 != null
                && !sootDependencyClasspathSha256.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("sootDependencyClasspathSha256 must be lowercase SHA-256");
        }
        for (Region region : regions) {
            region.validate();
            if (empty(region.regionId)) throw new IllegalArgumentException("missing regionId");
            if (region.sourceOwner != null
                    && !"CURRENT".equals(region.sourceOwner)
                    && !"THIS".equals(region.sourceOwner)) {
                throw new IllegalArgumentException("sourceOwner must be CURRENT or THIS");
            }
        }
        for (Target target : targets) {
            target.validate();
            if (empty(target.siteId)) throw new IllegalArgumentException("missing target siteId");
            if (target.line <= 0) throw new IllegalArgumentException("target requires source line");
            if (!"BRANCH".equals(target.kind) && !"SWITCH".equals(target.kind)
                    && !"THROW".equals(target.kind)) {
                throw new IllegalArgumentException("target kind must be BRANCH, SWITCH or THROW");
            }
        }
        for (Coverage site : coverage) {
            site.validate();
            if (empty(site.siteId)) throw new IllegalArgumentException("missing coverage siteId");
        }
        for (Frames site : frames) site.validate();
        if (!"NONE".equals(faultController) && !"MALLORY_PROBE".equals(faultController)
                && !"MALLORY_GC_FAULT_PLAN".equals(faultController)) {
            throw new IllegalArgumentException("unsupported faultController: " + faultController);
        }
        for (Door site : doors) {
            site.validate();
            if (site.line <= 0 || empty(site.siteId) || empty(site.callee)) {
                throw new IllegalArgumentException("door needs line, siteId and callee");
            }
        }
        for (StateCandidate site : stateCandidates) {
            site.validate();
            if (site.line <= 0 || site.unitIndex == null || empty(site.siteId)
                    || empty(site.field) || (!"READ".equals(site.access)
                    && !"WRITE".equals(site.access))) {
                throw new IllegalArgumentException("state candidate needs exact site, field and access");
            }
        }
    }

    private static boolean empty(String value) { return value == null || value.isEmpty(); }

    public static class MethodSite {
        public String clazz;
        public String method;
        public String descriptor;
        /** Optional jtp-entry Jimple unit index, before this weave adds probes. */
        public Integer unitIndex;

        void validate() {
            if (empty(clazz) || empty(method) || empty(descriptor)) {
                throw new IllegalArgumentException("site needs class, method and JVM descriptor");
            }
        }

        public boolean matches(String className, String methodName, String jvmDescriptor) {
            return clazz.equals(className) && method.equals(methodName)
                    && descriptor.equals(jvmDescriptor);
        }
    }

    public static final class Region extends MethodSite {
        public String regionId;
        /** CURRENT scope, or a registered source alias on the method receiver. */
        public String sourceOwner;
    }

    public static final class Target extends MethodSite {
        public String kind;
        public int line;
        public String siteId;
        public String exceptionClass;
    }

    public static final class Coverage extends MethodSite {
        public String siteId;
        /** Zero selects legacy method entry; positive selects one branch at this line. */
        public int line;
    }

    /** Every original call in this method gets balanced execution frames. */
    public static final class Frames extends MethodSite { }

    /** Exact source line plus exact Soot callee signature, such as <A: void send()> . */
    public static final class Door extends MethodSite {
        public int line;
        public String callee;
        public String siteId;
        public String exceptionClass;
    }

    public static final class StateCandidate extends MethodSite {
        public int line;
        public String siteId;
        public String access;
        public String field;
        public boolean staticField;
    }
}
