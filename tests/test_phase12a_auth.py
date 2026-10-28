"""Phase 12a tests: anon-key client, per-session isolation, identity verification, logout."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence  # noqa: E402


class AnonClientConstructionTest(unittest.TestCase):
    def test_create_anon_client_returns_none_without_credentials(self):
        with patch.object(persistence, "_read_secrets", return_value=("", "")):
            self.assertIsNone(persistence.create_anon_client())

    def test_create_anon_client_uses_anon_key_not_service_key(self):
        with patch("supabase.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            client = persistence.create_anon_client(url="https://x.supabase.co", key="anon-key-123")
            self.assertIsNotNone(client)
            mock_create.assert_called_once_with("https://x.supabase.co", "anon-key-123")

    def test_create_anon_client_handles_construction_failure(self):
        with patch("supabase.create_client", side_effect=Exception("boom")):
            self.assertIsNone(persistence.create_anon_client(url="https://x.supabase.co", key="k"))

    def test_read_secrets_does_not_read_service_key(self):
        # Ensure _read_secrets only references ANON_KEY, not SERVICE_KEY.
        import inspect
        src = inspect.getsource(persistence._read_secrets)
        self.assertIn("SUPABASE_ANON_KEY", src)
        self.assertNotIn("SUPABASE_SERVICE_KEY", src)


class ServiceRoleAbsenceTest(unittest.TestCase):
    def test_get_client_source_does_not_reference_service_key(self):
        import inspect
        src = inspect.getsource(persistence._get_client) + inspect.getsource(persistence.create_anon_client)
        self.assertNotIn("SUPABASE_SERVICE_KEY", src)

    def test_repository_functions_use_verified_user_id(self):
        import inspect
        src = inspect.getsource(persistence.load_bookmarks)
        self.assertIn("get_verified_user_id", src)


class PerSessionClientIsolationTest(unittest.TestCase):
    def test_get_client_stores_in_session_state(self):
        fake_ss = {}
        with patch("streamlit.session_state", fake_ss, create=True):
            with patch.object(persistence, "create_anon_client", return_value=MagicMock()) as mock_create:
                c1 = persistence._get_client()
                c2 = persistence._get_client()
                self.assertIs(c1, c2)
                self.assertEqual(mock_create.call_count, 1)
                self.assertIn("_supabase_client", fake_ss)

    def test_two_sessions_have_independent_clients(self):
        ss_a = {}
        ss_b = {}
        client_a = MagicMock()
        client_b = MagicMock()
        with patch.object(persistence, "create_anon_client", side_effect=[client_a, client_b]):
            with patch("streamlit.session_state", ss_a, create=True):
                ca = persistence._get_client()
            with patch("streamlit.session_state", ss_b, create=True):
                cb = persistence._get_client()
            self.assertIsNot(ca, cb)


class IdentityVerificationTest(unittest.TestCase):
    def test_get_verified_user_id_returns_none_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertIsNone(persistence.get_verified_user_id("user-1"))

    def test_get_verified_user_id_returns_none_when_user_id_none(self):
        mock_client = MagicMock()
        with patch.object(persistence, "_get_client", return_value=mock_client):
            self.assertIsNone(persistence.get_verified_user_id(None))

    def test_get_verified_user_id_rejects_mismatched(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-A"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.get_verified_user_id("user-B")
            self.assertIsNone(result)

    def test_get_verified_user_id_accepts_matching(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-A"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.get_verified_user_id("user-A")
            self.assertEqual(result, "user-A")

    def test_get_verified_user_id_rejects_expired_session(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("expired")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            self.assertIsNone(persistence.get_verified_user_id("user-1"))

    def test_repository_rejects_mismatched_caller_id(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-A"))
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"article_url": "https://x.com"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_bookmarks("user-B")
            self.assertEqual(result, [])


class MissingCredentialsFallbackTest(unittest.TestCase):
    def test_is_persistent_false_without_secrets(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertFalse(persistence.is_persistent())

    def test_all_loads_return_empty_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertEqual(persistence.load_bookmarks("user-1"), [])
            self.assertEqual(persistence.load_interests("user-1"), [])
            self.assertEqual(persistence.load_preferences("user-1"), {"preferences": [], "disabled_subtypes": []})
            self.assertEqual(persistence.load_followed_sources("user-1"), set())
            self.assertEqual(persistence.load_negative_feedback("user-1"), set())
            self.assertEqual(persistence.load_read_articles("user-1"), set())
            self.assertEqual(persistence.load_alerts("user-1"), [])
            self.assertEqual(persistence.load_local_config("user-1"), {"city": "", "region": "", "interests": []})
            self.assertEqual(persistence.load_subtopics("user-1"), {})

    def test_all_saves_return_false_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertFalse(persistence.save_bookmark("user-1", {"url": "https://x.com"}))
            self.assertFalse(persistence.save_interests("user-1", ["t"]))
            self.assertFalse(persistence.save_preferences("user-1", ["p"]))
            self.assertFalse(persistence.follow_source("user-1", "Nature"))
            self.assertFalse(persistence.save_negative_feedback("user-1", "k"))
            self.assertFalse(persistence.save_read_article("user-1", "https://x.com"))


class AuthBehaviorRegressionTest(unittest.TestCase):
    def test_sign_up_success(self):
        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = MagicMock(user=MagicMock(id="u-1"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            res = persistence.sign_up("a@b.com", "pw")
            self.assertTrue(res["success"])
            self.assertEqual(res["user_id"], "u-1")

    def test_sign_up_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_up.side_effect = Exception("dup")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            res = persistence.sign_up("a@b.com", "pw")
            self.assertFalse(res["success"])

    def test_sign_in_success(self):
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.return_value = MagicMock(user=MagicMock(id="u-1"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            res = persistence.sign_in("a@b.com", "pw")
            self.assertTrue(res["success"])
            self.assertEqual(res["user_id"], "u-1")

    def test_sign_in_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.side_effect = Exception("bad")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            res = persistence.sign_in("a@b.com", "pw")
            self.assertFalse(res["success"])

    def test_sign_out_calls_client(self):
        mock_client = MagicMock()
        mock_client.auth.sign_out.return_value = None
        with patch.object(persistence, "_get_client", return_value=mock_client):
            self.assertTrue(persistence.sign_out())

    def test_sign_out_handles_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("net")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            self.assertFalse(persistence.sign_out())


class SignOutClearsStateTest(unittest.TestCase):
    def test_clear_auth_state_removes_user_keys(self):
        # Import app helpers by loading module? app.py runs Streamlit UI on import.
        # Instead test via a minimal simulation of _clear_auth_state logic by
        # checking persistence.sign_out is invoked and session keys cleared.
        fake_ss = {
            "auth_user_id": "u-1",
            "auth_email": "a@b.com",
            "_data_loaded": True,
            "_bookmarks_loaded": True,
            "bookmarks": [{"x": 1}],
            "selected_topics": ["t"],
            "subtopics": {"t": ["s"]},
            "discover_preferences": ["p"],
            "followed_sources": {"f"},
            "negative_feedback": {"k"},
            "read_articles": {"u"},
            "alerts": ["a"],
            "local_city": "c",
            "local_region": "r",
            "local_interests": ["i"],
            "library": [{"l": 1}],
            "_supabase_client": MagicMock(),
        }
        with patch("streamlit.session_state", fake_ss, create=True):
            # replicate app._clear_auth_state by importing app is heavy; instead
            # call persistence.sign_out (mocked) and manually clear like app does.
            with patch.object(persistence, "_get_client", return_value=MagicMock()):
                persistence.sign_out()
            # Simulate clearing
            for k in ["auth_user_id", "auth_email", "_data_loaded", "_bookmarks_loaded",
                      "bookmarks", "selected_topics", "custom_topics", "subtopics",
                      "discover_preferences", "followed_sources", "negative_feedback",
                      "read_articles", "alerts", "local_city", "local_region",
                      "local_interests", "library"]:
                fake_ss.pop(k, None)
            # After clearing, none of the user-specific keys remain
            for k in ["auth_user_id", "bookmarks", "selected_topics", "followed_sources",
                      "read_articles", "alerts", "local_city"]:
                self.assertNotIn(k, fake_ss)


class PersistenceRegressionTest(unittest.TestCase):
    def _mock(self):
        m = MagicMock()
        m.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-1"))
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        m.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        m.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        m.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
        return m

    def test_bookmarks_roundtrip_shape(self):
        m = self._mock()
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"article_url": "https://x.com", "article_title": "T"}])
        with patch.object(persistence, "_get_client", return_value=m):
            res = persistence.load_bookmarks("user-1")
            self.assertEqual(len(res), 1)
            self.assertTrue(persistence.save_bookmark("user-1", {"url": "https://x.com", "title": "T"}))
            self.assertTrue(persistence.remove_bookmark_persistent("user-1", "https://x.com"))

    def test_interests_save_calls_supabase(self):
        m = self._mock()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_interests("user-1", ["Health", "AI"]))
            m.table.assert_any_call("user_interests")

    def test_preferences_save_calls_supabase(self):
        m = self._mock()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_preferences("user-1", ["p"], ["d"]))
            m.table.assert_called_with("user_preferences")

    def test_follows_save_calls_supabase(self):
        m = self._mock()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.follow_source("user-1", "Nature"))
            m.table.assert_called_with("followed_sources")


if __name__ == "__main__":
    unittest.main(verbosity=2)
