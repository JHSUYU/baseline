package edu.uva.liftlab.graphchecker.causynth;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Keeps the original folded catalog's ordering and whole-row equality. */
public final class FoldedUnionMembershipTest {
    @Test
    @SuppressWarnings("unchecked")
    public void keepsOwnDuplicatesAndAddsOnlyNewFoldedRows() throws Exception {
        Map<String, Object> first = row("site", "a", "value", 1);
        Map<String, Object> equalCopy = row("value", 1, "site", "a");
        Map<String, Object> second = row("site", "b", "value", 2);
        Map<String, Object> third = row("site", "c", "value", 3);
        List<Map<String, Object>> own = Arrays.asList(first, equalCopy, second);
        List<Map<String, Object>> folded = Arrays.asList(equalCopy, third,
                row("site", "c", "value", 3));

        StaticProgram.RegionRow owner = skeleton("owner", own);
        StaticProgram.RegionRow child = skeleton("child", folded);
        StaticProgram program = new StaticProgram();
        program.skeletons.put(child.regionId, child);
        Function<StaticProgram.RegionRow, Collection<Map<String, Object>>>
                catalog = region -> region.outputs;

        Method method = RuntimeSelectedRegionFinalizer.class.getDeclaredMethod(
                "foldedUnion", StaticProgram.class,
                StaticProgram.RegionRow.class, List.class, Function.class);
        method.setAccessible(true);
        List<Map<String, Object>> actual = (List<Map<String, Object>>)
                method.invoke(null, program, owner,
                        Collections.singletonList(child.regionId), catalog);

        // The former implementation used ArrayList.contains on whole rows.
        List<Map<String, Object>> reference = new ArrayList<>(own);
        for (Map<String, Object> item : folded) {
            if (!reference.contains(item)) reference.add(item);
        }
        assertEquals(reference, actual);
        assertEquals(4, actual.size());
        assertEquals(first, actual.get(0));
        assertEquals(equalCopy, actual.get(1));
        assertEquals(second, actual.get(2));
        assertEquals(third, actual.get(3));
    }

    private static StaticProgram.RegionRow skeleton(String id,
                                                     List<Map<String, Object>> outputs) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("schemaVersion", RuntimeSelectedRegionFinalizer.REGION_SCHEMA_VERSION);
        row.put("kind", RuntimeSelectedRegionFinalizer.SKELETON_KIND);
        row.put("regionId", id);
        row.put("rootMethod", "<" + id + ": void run()>");
        row.put("anchorMethod", "<" + id + ": void run()>");
        row.put("methods", Collections.singletonList("<" + id + ": void run()>"));
        row.put("outputs", outputs);
        return StaticProgram.regionRows(Collections.singletonList(row),
                RuntimeSelectedRegionFinalizer.SKELETON_KIND, "fixture").get(0);
    }

    private static Map<String, Object> row(Object... cells) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < cells.length; index += 2) {
            result.put((String) cells[index], cells[index + 1]);
        }
        return result;
    }
}
