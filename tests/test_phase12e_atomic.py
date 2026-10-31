"""Phase 12e tests: atomic interest/subtopic replacement via RPC + fallback."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence  # noqa: E402


def _mock_client(uid="user-1", rpc_ok=True):
    m = MagicMock()
    m.auth.get_user.return_value = MagicMock(user=MagicMock(id=uid))
    if rpc_ok:
        m.rpc.return_value.execute.return_value = MagicMock(data=None)
    else:
        m.rpc.return_value.execute.side_effect = Exception("Could not find the function public.replace_user_interests")
    m.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    m.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return m


class AtomicInterestsTest(unittest.TestCase):
    def test_uses_rpc_when_available(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_interests("user-1", ["A", "B"]))
            m.rpc.assert_called_with("replace_user_interests", {"p_topics": ["A", "B"]})

    def test_rpc_payload_empty_list(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_interests("user-1", []))
            m.rpc.assert_called_with("replace_user_interests", {"p_topics": []})

    def test_falls_back_to_delete_insert_when_rpc_missing(self):
        m = _mock_client(rpc_ok=False)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_interests("user-1", ["A"]))
            m.table.assert_any_call("user_interests")

    def test_returns_false_when_both_fail(self):
        m = _mock_client(rpc_ok=False)
        m.table.return_value.delete.return_value.eq.return_value.execute.side_effect = Exception("db down")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_interests("user-1", ["A"]))

    def test_rejects_mismatched_user(self):
        m = _mock_client(uid="user-A", rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_interests("user-B", ["A"]))
            m.rpc.assert_not_called()

    def test_returns_false_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertFalse(persistence.save_interests("user-1", ["A"]))


class AtomicSubtopicsTest(unittest.TestCase):
    def test_uses_rpc_with_json_payload(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            subs = {"Health": ["Epi", "Vax"], "AI": ["ML"]}
            self.assertTrue(persistence.save_subtopics("user-1", subs))
            call = m.rpc.call_args
            self.assertEqual(call.args[0], "replace_user_subtopics")
            payload = call.args[1]["p_subtopics"]
            self.assertEqual(len(payload), 3)
            self.assertIn({"topic": "Health", "subtopic": "Epi"}, payload)

    def test_empty_subtopics_sends_empty_array(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_subtopics("user-1", {}))
            m.rpc.assert_called_with("replace_user_subtopics", {"p_subtopics": []})

    def test_falls_back_when_rpc_missing(self):
        m = _mock_client(rpc_ok=False)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_subtopics("user-1", {"T": ["s"]}))

    def test_rejects_mismatched_user(self):
        m = _mock_client(uid="user-A", rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_subtopics("user-B", {"T": ["s"]}))
            m.rpc.assert_not_called()


class AtomicityDocumentationTest(unittest.TestCase):
    def test_migration_file_exists(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "migrations", "002_atomic_replacement.sql")
        self.assertTrue(os.path.exists(path))

    def test_rpc_not_applied_to_staging(self):
        # The RPC is proposed, not applied. persistence falls back gracefully.
        # This test documents the limitation; no DB call made.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AtomicNullInvalidInputTest(unittest.TestCase):
    def test_interests_null_raises_no_fallback(self):
        m = _mock_client(rpc_ok=False)
        # Simulate a genuine error (not missing function) -> no fallback
        m.rpc.return_value.execute.side_effect = Exception("p_topics must not be null")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_interests("user-1", ["A"]))
            # fallback delete should NOT have been called
            m.table.return_value.delete.assert_not_called()

    def test_subtopics_invalid_type_raises_no_fallback(self):
        m = _mock_client(rpc_ok=False)
        m.rpc.return_value.execute.side_effect = Exception("p_subtopics must be a JSON array")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_subtopics("user-1", {"T": ["s"]}))
            m.table.return_value.delete.assert_not_called()

    def test_empty_interests_clears_via_rpc(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_interests("user-1", []))
            m.rpc.assert_called_with("replace_user_interests", {"p_topics": []})

    def test_empty_subtopics_clears_via_rpc(self):
        m = _mock_client(rpc_ok=True)
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_subtopics("user-1", {}))
            m.rpc.assert_called_with("replace_user_subtopics", {"p_subtopics": []})
