package edu.uva.liftlab.graphchecker.causynth;

import org.junit.Test;
import soot.G;
import soot.Scene;
import soot.SootClass;
import soot.options.Options;

import java.nio.file.Paths;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/** A dependency class at HIERARCHY must be upgraded before getMethods(). */
public final class ProtobufSignatureResolutionTest {
    @Test public void hierarchyOnlyDependencyExposesGettersAfterUpgrade() throws Exception {
        G.reset();
        String fixtureDir = Paths.get(MessageWithGetter.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI()).toString();
        Options.v().set_soot_classpath(fixtureDir);
        Options.v().set_allow_phantom_refs(true);
        String name = MessageWithGetter.class.getName();
        SootClass hierarchyOnly = Scene.v().forceResolve(name, SootClass.HIERARCHY);
        assertEquals(SootClass.HIERARCHY, hierarchyOnly.resolvingLevel());

        SootClass signatures = SeedBackwardStaticAnalyzer
                .messageClassWithSignatures(name);
        assertNotNull(signatures);
        assertTrue(signatures.resolvingLevel() >= SootClass.SIGNATURES);
        assertTrue(signatures.getMethods().stream()
                .anyMatch(method -> method.getName().equals("getKeyId")));
    }
}

/** Compiled dependency bytecode, deliberately first loaded at HIERARCHY. */
final class MessageWithGetter {
    public int getKeyId() { return 7; }
}
