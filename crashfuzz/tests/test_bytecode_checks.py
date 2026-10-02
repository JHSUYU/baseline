import unittest

from adhoc_crashfuzz.bytecode_checks import map_direct_throw
from adhoc_crashfuzz.signatures import agent_method


JAVAP = """public class example.Check {
  public void check();
    descriptor: ()V
    Code:
       0: aload_0
       1: ifnonnull     12
       4: new           #2
       7: dup
       8: invokespecial #3
      11: athrow
      12: return
    LineNumberTable:
      line 10: 0
      line 11: 4
      line 12: 12
}
"""


class BytecodeCheckTests(unittest.TestCase):
    def test_direct_guard_and_exact_throw_line(self):
        method = agent_method("<example.Check: void check()>")
        self.assertEqual("example/Check#check()V", method)
        self.assertEqual({
            "guard": method + "#B1", "throw": method + "#L11",
            "guard_offset": 1, "throw_offset": 11,
        }, map_direct_throw(method, 11, JAVAP))
        self.assertIsNone(map_direct_throw(method, 12, JAVAP))

    def test_array_signature(self):
        self.assertEqual("example/Check#scan([BI)[Ljava/lang/String;",
                         agent_method(
                             "<example.Check: java.lang.String[] scan(byte[],int)>"))


if __name__ == "__main__":
    unittest.main()
