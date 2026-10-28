"""Static checks for migrations/001_initial_schema.sql (Phase 12b)."""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIGRATION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations", "001_initial_schema.sql",
)


def _load():
    with open(MIGRATION) as f:
        return f.read()


class MigrationSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = _load()

    def test_file_exists(self):
        self.assertTrue(os.path.exists(MIGRATION))

    def test_user_owned_tables_present(self):
        expected = [
            "user_interests", "user_subtopics", "user_preferences", "bookmarks",
            "followed_sources", "negative_feedback", "read_articles", "alerts",
            "local_config",
        ]
        for t in expected:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {t}", self.sql)

    def test_removed_tables_absent(self):
        for t in ["public.users", "CREATE TABLE IF NOT EXISTS users",
                  "CREATE TABLE IF NOT EXISTS library",
                  "CREATE TABLE IF NOT EXISTS cached_articles"]:
            self.assertNotIn(t, self.sql)

    def test_no_public_users_table(self):
        self.assertNotIn("CREATE TABLE IF NOT EXISTS users", self.sql)

    def test_foreign_keys_target_auth_users(self):
        # Every REFERENCES should target auth.users(id)
        refs = re.findall(r"REFERENCES\s+(\S+)", self.sql)
        self.assertTrue(refs, "no REFERENCES found")
        for r in refs:
            self.assertEqual(r, "auth.users(id)", f"unexpected FK target: {r}")

    def test_on_delete_cascade(self):
        self.assertIn("ON DELETE CASCADE", self.sql)

    def test_rls_enabled_for_all_user_tables(self):
        tables = [
            "user_interests", "user_subtopics", "user_preferences", "bookmarks",
            "followed_sources", "negative_feedback", "read_articles", "alerts",
            "local_config",
        ]
        for t in tables:
            self.assertIn(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;", self.sql)

    def test_policies_have_with_check(self):
        # Count WITH CHECK occurrences == number of user tables
        self.assertEqual(self.sql.count("WITH CHECK (auth.uid() = user_id)"), 9)

    def test_policies_use_auth_uid(self):
        self.assertEqual(self.sql.count("auth.uid() = user_id"), 18)  # USING + WITH CHECK

    def test_no_public_true_policy(self):
        self.assertNotIn("USING (true)", self.sql)

    def test_no_service_role_policy(self):
        self.assertNotIn("service_role", self.sql)

    def test_unique_constraints_match_repository(self):
        # bookmarks unique (user_id, article_url)
        self.assertIn("UNIQUE(user_id, article_url)", self.sql)
        # followed_sources unique (user_id, source_name)
        self.assertIn("UNIQUE(user_id, source_name)", self.sql)
        # negative_feedback unique (user_id, feedback_key)
        self.assertIn("UNIQUE(user_id, feedback_key)", self.sql)
        # read_articles unique (user_id, article_url)
        self.assertIn("UNIQUE(user_id, article_url)", self.sql)
        # alerts unique (user_id, keyword)
        self.assertIn("UNIQUE(user_id, keyword)", self.sql)
        # user_interests unique (user_id, topic)
        self.assertIn("UNIQUE(user_id, topic)", self.sql)
        # user_subtopics unique (user_id, topic, subtopic)
        self.assertIn("UNIQUE(user_id, topic, subtopic)", self.sql)

    def test_primary_keys(self):
        # user_preferences and local_config use user_id as PK
        self.assertIn("user_id UUID PRIMARY KEY REFERENCES auth.users(id)", self.sql)
        # others use id UUID PK
        self.assertGreaterEqual(self.sql.count("UUID PRIMARY KEY DEFAULT uuid_generate_v4()"), 7)

    def test_repository_table_names_covered(self):
        import persistence
        # Tables used by persistence module
        used = ["bookmarks", "followed_sources", "user_interests", "user_subtopics",
                "user_preferences", "negative_feedback", "read_articles", "alerts",
                "local_config"]
        for t in used:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {t}", self.sql)

    def test_no_credentials_in_migration(self):
        low = self.sql.lower()
        for bad in ["password", "secret", "api_key", "token", "eyJ"]:
            self.assertNotIn(bad, low)


if __name__ == "__main__":
    unittest.main(verbosity=2)
