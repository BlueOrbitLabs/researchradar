"""Tests for the persistence repository layer (Phase 9)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence  # noqa: E402


class PersistenceAvailabilityTest(unittest.TestCase):
    def test_is_persistent_false_without_client(self):
        with patch.object(persistence, "_supabase_client", None):
            with patch.object(persistence, "_get_client", return_value=None):
                self.assertFalse(persistence.is_persistent())

    def test_load_bookmarks_returns_empty_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertEqual(persistence.load_bookmarks("user-1"), [])

    def test_load_bookmarks_returns_empty_without_user_id(self):
        with patch.object(persistence, "_get_client", return_value=MagicMock()):
            self.assertEqual(persistence.load_bookmarks(None), [])

    def test_save_bookmark_returns_false_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertFalse(persistence.save_bookmark("user-1", {"url": "https://x.com"}))

    def test_save_bookmark_returns_false_without_user_id(self):
        with patch.object(persistence, "_get_client", return_value=MagicMock()):
            self.assertFalse(persistence.save_bookmark(None, {"url": "https://x.com"}))


class PersistenceBookmarkTest(unittest.TestCase):
    def test_save_bookmark_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_bookmark("user-1", {"url": "https://x.com", "title": "Test"})
            self.assertTrue(result)
            mock_client.table.assert_called_with("bookmarks")

    def test_remove_bookmark_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.remove_bookmark_persistent("user-1", "https://x.com")
            self.assertTrue(result)

    def test_load_bookmarks_returns_data(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"article_url": "https://x.com", "article_title": "Test"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_bookmarks("user-1")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["article_url"], "https://x.com")


class PersistenceFollowTest(unittest.TestCase):
    def test_follow_source_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.follow_source("user-1", "Nature", "https://nature.com/feed")
            self.assertTrue(result)
            mock_client.table.assert_called_with("followed_sources")

    def test_unfollow_source_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.unfollow_source("user-1", "Nature")
            self.assertTrue(result)

    def test_load_followed_sources_returns_set(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"source_name": "Nature"}, {"source_name": "BBC"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_followed_sources("user-1")
            self.assertEqual(result, {"Nature", "BBC"})


class PersistenceInterestTest(unittest.TestCase):
    def test_load_interests_returns_list(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"topic": "Health & Medicine"}, {"topic": "AI & Technology"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_interests("user-1")
            self.assertEqual(result, ["Health & Medicine", "AI & Technology"])

    def test_save_interests_replaces_all(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_interests("user-1", ["Health & Medicine", "AI & Technology"])
            self.assertTrue(result)


class PersistencePreferenceTest(unittest.TestCase):
    def test_load_preferences_returns_defaults_without_data(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_preferences("user-1")
            self.assertEqual(result, {"preferences": [], "disabled_subtypes": []})

    def test_save_preferences_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_preferences("user-1", ["New research & journal publications"], ["pref::subtype"])
            self.assertTrue(result)


class PersistenceFeedbackTest(unittest.TestCase):
    def test_load_negative_feedback_returns_set(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"feedback_key": "Health::BBC"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_negative_feedback("user-1")
            self.assertEqual(result, {"Health::BBC"})

    def test_save_negative_feedback_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_negative_feedback("user-1", "Health::BBC")
            self.assertTrue(result)


class PersistenceErrorHandlingTest(unittest.TestCase):
    def test_save_bookmark_handles_exception(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_bookmark("user-1", {"url": "https://x.com"})
            self.assertFalse(result)

    def test_load_bookmarks_handles_exception(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_bookmarks("user-1")
            self.assertEqual(result, [])

    def test_follow_source_handles_exception(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.follow_source("user-1", "Nature")
            self.assertFalse(result)


class PersistenceUserIsolationTest(unittest.TestCase):
    def test_different_users_get_different_data(self):
        mock_client = MagicMock()
        # Simulate different data for different users
        def side_effect(*args, **kwargs):
            return mock_client
        with patch.object(persistence, "_get_client", return_value=mock_client):
            # User 1
            mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"article_url": "https://user1.com"}])
            r1 = persistence.load_bookmarks("user-1")
            # User 2
            mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"article_url": "https://user2.com"}])
            r2 = persistence.load_bookmarks("user-2")
            self.assertNotEqual(r1, r2)


class PersistenceLocalConfigTest(unittest.TestCase):
    def test_load_local_config_returns_defaults_without_data(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_local_config("user-1")
            self.assertEqual(result, {"city": "", "region": "", "interests": []})

    def test_save_local_config_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_local_config("user-1", "Hyderabad", "Telangana", ["Health"])
            self.assertTrue(result)


class PersistenceSubtopicTest(unittest.TestCase):
    def test_load_subtopics_groups_by_topic(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"topic": "Health", "subtopic": "Epidemiology"},
                  {"topic": "Health", "subtopic": "Vaccines"},
                  {"topic": "AI", "subtopic": "ML"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_subtopics("user-1")
            self.assertEqual(result, {"Health": ["Epidemiology", "Vaccines"], "AI": ["ML"]})

    def test_save_subtopics_handles_empty(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.save_subtopics("user-1", {})
            self.assertTrue(result)


class PersistenceAlertTest(unittest.TestCase):
    def test_load_alerts_returns_list(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"keyword": "CRISPR"}, {"keyword": "climate"}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.load_alerts("user-1")
            self.assertEqual(result, ["CRISPR", "climate"])

    def test_remove_alert_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.remove_alert("user-1", "CRISPR")
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PersistenceAuthTest(unittest.TestCase):
    def test_sign_up_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = MagicMock(user=MagicMock(id="user-123"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_up("test@example.com", "password123")
            self.assertTrue(result["success"])
            self.assertEqual(result["user_id"], "user-123")

    def test_sign_up_handles_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_up.side_effect = Exception("Email already registered")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_up("test@example.com", "password123")
            self.assertFalse(result["success"])
            self.assertIsNone(result["user_id"])

    def test_sign_in_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.return_value = MagicMock(user=MagicMock(id="user-123"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_in("test@example.com", "password123")
            self.assertTrue(result["success"])
            self.assertEqual(result["user_id"], "user-123")

    def test_sign_in_handles_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_in("test@example.com", "wrong")
            self.assertFalse(result["success"])
            self.assertIsNone(result["user_id"])

    def test_sign_out_calls_supabase(self):
        mock_client = MagicMock()
        mock_client.auth.sign_out.return_value = None
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_out()
            self.assertTrue(result)

    def test_sign_out_handles_failure(self):
        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("Network error")
        with patch.object(persistence, "_get_client", return_value=mock_client):
            result = persistence.sign_out()
            self.assertFalse(result)

    def test_get_current_user_id_returns_id(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-123"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            uid = persistence.get_current_user_id()
            self.assertEqual(uid, "user-123")

    def test_get_current_user_id_returns_none_without_client(self):
        with patch.object(persistence, "_get_client", return_value=None):
            self.assertIsNone(persistence.get_current_user_id())

    def test_get_current_user_email_returns_email(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(email="test@example.com"))
        with patch.object(persistence, "_get_client", return_value=mock_client):
            email = persistence.get_current_user_email()
            self.assertEqual(email, "test@example.com")
