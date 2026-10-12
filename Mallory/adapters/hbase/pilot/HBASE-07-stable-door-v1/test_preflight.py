import importlib.util
import pathlib
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("hbase07_preflight", _HERE / "preflight.py")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class PreflightTest(unittest.TestCase):
    def _events(self, duplicate=False, wrong_token=False):
        region = "client:0:" + _MOD.TARGET_REGION + ":root:1"
        token = "run:task:5"
        rows = [
            dict(seq=1, type="REGION_ENTER", node="client", site=_MOD.TARGET_REGION,
                 occurrence=region),
            dict(seq=2, type="SEND", node="client", port=_MOD.RPC_METHOD,
                 occurrence=region, correlation=token),
            dict(seq=3, type="RECV", node="master0", port=_MOD.RPC_METHOD,
                 correlation=token, thread_id=42),
            dict(seq=4, type="DOOR_OBSERVED", node="master0", site=_MOD.SERVER_DOOR,
                 context="wrong" if wrong_token else token, thread_id=42),
            dict(seq=5, type="TARGET_CHECK", node="client", site=_MOD.TARGET_CHECK,
                 occurrence=region, thread_id=1),
        ]
        if duplicate:
            rows.insert(4, dict(seq=4, type="RECV", node="master0",
                                port=_MOD.RPC_METHOD, correlation=token, thread_id=41))
        return rows

    def test_unique_transport_join(self):
        result = _MOD.inspect_events(self._events())
        self.assertTrue(result["all_first_attempts_unique"])
        self.assertEqual(result["target_invocations"][0]["request_attempts_before_target"], 1)
        self.assertEqual(result["target_invocations"][0]["requests"][0]
                         ["client_method_ordinal"], 1)

    def test_ambiguous_or_untransported_call_rejected(self):
        for events in (self._events(duplicate=True), self._events(wrong_token=True)):
            with self.subTest(events=events):
                self.assertFalse(_MOD.inspect_events(events)["all_first_attempts_unique"])


if __name__ == "__main__":
    unittest.main()
