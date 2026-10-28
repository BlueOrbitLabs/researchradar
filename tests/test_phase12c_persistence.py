"""Phase 12c tests: alerts, local config, discover follow/unfollow persistence."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence  # noqa: E402


def _mock_client(uid="user-1"):
    m = MagicMock()
    m.auth.get_user.return_value = MagicMock(user=MagicMock(id=uid))
    m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    m.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    m.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    m.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    m.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return m


class AlertPersistenceTest(unittest.TestCase):
    def test_save_alert_calls_supabase(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_alert("user-1", "CRISPR"))
            m.table.assert_called_with("alerts")

    def test_remove_alert_calls_supabase(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.remove_alert("user-1", "CRISPR"))

    def test_load_alerts_returns_list(self):
        m = _mock_client()
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"keyword": "CRISPR"}, {"keyword": "climate"}])
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertEqual(persistence.load_alerts("user-1"), ["CRISPR", "climate"])

    def test_duplicate_alert_upsert_no_error(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_alert("user-1", "CRISPR"))
            self.assertTrue(persistence.save_alert("user-1", "CRISPR"))

    def test_alert_rejects_mismatched_user(self):
        m = _mock_client("user-A")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_alert("user-B", "x"))
            self.assertEqual(persistence.load_alerts("user-B"), [])


class LocalConfigPersistenceTest(unittest.TestCase):
    def test_save_local_config_calls_supabase(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_local_config("user-1", "Hyderabad", "Telangana", ["Health"]))
            m.table.assert_called_with("local_config")

    def test_load_local_config_returns_data(self):
        m = _mock_client()
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"city": "Hyderabad", "region": "Telangana", "interests": ["Health"]}])
        with patch.object(persistence, "_get_client", return_value=m):
            res = persistence.load_local_config("user-1")
            self.assertEqual(res["city"], "Hyderabad")
            self.assertEqual(res["region"], "Telangana")
            self.assertEqual(res["interests"], ["Health"])

    def test_clear_config_persists_empty(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.save_local_config("user-1", "", "", []))

    def test_local_config_rejects_mismatched_user(self):
        m = _mock_client("user-A")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_local_config("user-B", "c", "r", []))
            self.assertEqual(persistence.load_local_config("user-B"), {"city": "", "region": "", "interests": []})


class FollowedSourcePersistenceTest(unittest.TestCase):
    def test_follow_source_persists_name_and_url(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.follow_source("user-1", "Nature", "https://nature.com/feed"))
            m.table.assert_called_with("followed_sources")

    def test_unfollow_source_calls_delete(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.unfollow_source("user-1", "Nature"))

    def test_load_followed_sources_returns_set(self):
        m = _mock_client()
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"source_name": "Nature"}, {"source_name": "BBC"}])
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertEqual(persistence.load_followed_sources("user-1"), {"Nature", "BBC"})

    def test_duplicate_follow_upsert(self):
        m = _mock_client()
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertTrue(persistence.follow_source("user-1", "Nature"))
            self.assertTrue(persistence.follow_source("user-1", "Nature"))

    def test_follow_rejects_mismatched_user(self):
        m = _mock_client("user-A")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.follow_source("user-B", "Nature"))
            self.assertEqual(persistence.load_followed_sources("user-B"), set())

    def test_follow_failure_returns_false(self):
        m = _mock_client()
        m.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.follow_source("user-1", "Nature"))


class LoadStateSemanticsTest(unittest.TestCase):
    def test_empty_db_clears_stale_state(self):
        # load functions return [] / empty sets; app assigns unconditionally now.
        m = _mock_client()
        m.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertEqual(persistence.load_interests("user-1"), [])
            self.assertEqual(persistence.load_alerts("user-1"), [])
            self.assertEqual(persistence.load_followed_sources("user-1"), set())


class PersistenceFailureFeedbackTest(unittest.TestCase):
    def test_save_alert_failure_returns_false(self):
        m = _mock_client()
        m.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_alert("user-1", "x"))

    def test_save_local_config_failure_returns_false(self):
        m = _mock_client()
        m.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")
        with patch.object(persistence, "_get_client", return_value=m):
            self.assertFalse(persistence.save_local_config("user-1", "c", "r", []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
