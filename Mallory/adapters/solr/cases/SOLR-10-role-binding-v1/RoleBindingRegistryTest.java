/** Run with javac/javac -source 8 and java -ea; no Solr JVM is started. */
public final class RoleBindingRegistryTest {
  public static void main(String[] args) {
    RoleBindingRegistry roles = new RoleBindingRegistry();
    Object first = new Object();
    Object second = new Object();
    Object duplicateOnSameActor = new Object();
    String site = RoleBindingRegistry.SITE;

    assert !roles.atDoor(first, "node2", 0, site).bound;
    roles.decision(first, "DONT_KNOW", "node2", 0, "election-a");
    assert !roles.atDoor(first, "node2", 0, site).bound;
    roles.decision(first, "YES", "node2", 0, "election-a");
    RoleBindingRegistry.Resolution one = roles.atDoor(first, "node2", 0, site);
    assert one.bound && one.roleOrdinal == 1 && "node2".equals(one.physicalNode);
    assert RoleBindingRegistry.matches(one, RoleBindingRegistry.ROLE, site, 1);
    assert !RoleBindingRegistry.matches(one, RoleBindingRegistry.ROLE, site, 2);
    assert !RoleBindingRegistry.matches(one, RoleBindingRegistry.ROLE, "other-site", 1);
    assert !roles.atDoor(first, "node3", 0, site).bound;

    roles.decision(second, "YES", "node1", 0, "election-b");
    assert "ambiguous_physical_leader".equals(roles.atDoor(second, "node1", 0, site).reason);
    assert "ambiguous_physical_leader".equals(roles.atDoor(first, "node2", 0, site).reason);
    roles.decision(first, "NO", "node2", 0, "election-a");
    RoleBindingRegistry.Resolution migrated = roles.atDoor(second, "node1", 0, site);
    assert migrated.bound && migrated.roleOrdinal == 2;
    assert "node1".equals(migrated.physicalNode) && migrated.physicalEpoch == 0;

    roles.decision(duplicateOnSameActor, "YES", "node1", 0, "election-b");
    assert roles.atDoor(duplicateOnSameActor, "node1", 0, site).bound;
    roles.decision(first, "YES", "node1", 1, "election-c");
    assert "ambiguous_physical_leader".equals(roles.atDoor(first, "node1", 1, site).reason);
    roles.exit(second);
    roles.exit(duplicateOnSameActor);
    RoleBindingRegistry.Resolution restarted = roles.atDoor(first, "node1", 1, site);
    assert restarted.bound && restarted.roleOrdinal == 4;
    roles.exit(first);
    assert !roles.atDoor(first, "node1", 1, site).bound;

    roles.decision(first, "YES", "unknown", 0, "election-d");
    assert !roles.atDoor(first, "unknown", 0, site).bound;
    roles.decision(first, "YES", "node4", 0, null);
    assert !roles.atDoor(first, "node4", 0, site).bound;
    System.out.println("RoleBindingRegistryTest passed");
  }
}
