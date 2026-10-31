"""Static checks for migrations/002_atomic_replacement.sql (Phase 12e)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIGRATION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations", "002_atomic_replacement.sql",
)


class AtomicMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MIGRATION) as f:
            cls.sql = f.read()

    def test_file_exists(self):
        self.assertTrue(os.path.exists(MIGRATION))

    def test_security_invoker(self):
        self.assertGreaterEqual(self.sql.count("SECURITY INVOKER"), 2)

    def test_no_security_definer(self):
        self.assertNotIn("SECURITY DEFINER", self.sql)

    def test_safe_search_path(self):
        self.assertEqual(self.sql.count("SET search_path = public, pg_temp"), 2)

    def test_auth_uid_checks(self):
        self.assertGreaterEqual(self.sql.count("auth.uid() IS NULL"), 2)
        self.assertGreaterEqual(self.sql.count("auth.uid()"), 6)

    def test_grants_to_authenticated(self):
        self.assertIn("GRANT EXECUTE ON FUNCTION public.replace_user_interests(text[]) TO authenticated;", self.sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION public.replace_user_subtopics(jsonb) TO authenticated;", self.sql)

    def test_revokes_from_anon_public(self):
        self.assertIn("REVOKE EXECUTE ON FUNCTION public.replace_user_interests(text[]) FROM anon, public;", self.sql)
        self.assertIn("REVOKE EXECUTE ON FUNCTION public.replace_user_subtopics(jsonb) FROM anon, public;", self.sql)

    def test_no_credentials(self):
        low = self.sql.lower()
        for bad in ["password", "secret", "api_key", "token", "eyJ", "service_role"]:
            self.assertNotIn(bad, low)

    def test_null_interests_raises(self):
        self.assertIn("p_topics IS NULL", self.sql)
        self.assertIn("RAISE EXCEPTION", self.sql)

    def test_null_subtopics_raises(self):
        self.assertIn("p_subtopics IS NULL", self.sql)

    def test_subtopics_type_validation(self):
        self.assertIn("jsonb_typeof(p_subtopics) <> 'array'", self.sql)

    def test_validation_before_delete_interests(self):
        # Ensure the NULL check appears before the DELETE in the interests function.
        idx_null = self.sql.find("p_topics IS NULL")
        idx_del = self.sql.find("DELETE FROM public.user_interests")
        self.assertTrue(idx_null != -1 and idx_del != -1 and idx_null < idx_del)

    def test_validation_before_delete_subtopics(self):
        idx_null = self.sql.find("p_subtopics IS NULL")
        idx_del = self.sql.find("DELETE FROM public.user_subtopics")
        self.assertTrue(idx_null != -1 and idx_del != -1 and idx_null < idx_del)

    def test_empty_array_clears(self):
        # array_length / jsonb_array_length guard uses > 0, so empty clears.
        self.assertIn("array_length(p_topics, 1) > 0", self.sql)
        self.assertIn("jsonb_array_length(p_subtopics) > 0", self.sql)

    def test_interests_rejects_null_elements(self):
        self.assertIn("p_topics must not contain null elements", self.sql)

    def test_interests_rejects_empty_whitespace(self):
        self.assertIn("p_topics must not contain empty or whitespace-only values", self.sql)

    def test_interests_validation_before_delete(self):
        idx_null = self.sql.find("p_topics IS NULL")
        idx_elem = self.sql.find("p_topics must not contain null elements")
        idx_ws = self.sql.find("p_topics must not contain empty or whitespace-only values")
        idx_del = self.sql.find("DELETE FROM public.user_interests")
        self.assertTrue(idx_null != -1 and idx_null < idx_del)
        self.assertTrue(idx_elem != -1 and idx_elem < idx_del)
        self.assertTrue(idx_ws != -1 and idx_ws < idx_del)

    def test_subtopics_rejects_non_object(self):
        self.assertIn("p_subtopics elements must be objects", self.sql)

    def test_subtopics_rejects_missing_props(self):
        self.assertIn("p_subtopics elements must have topic and subtopic", self.sql)

    def test_subtopics_rejects_non_string(self):
        self.assertIn("topic and subtopic must be strings", self.sql)

    def test_subtopics_rejects_empty_whitespace(self):
        self.assertIn("topic and subtopic must not be empty or whitespace-only", self.sql)

    def test_subtopics_validation_before_delete(self):
        idx_null = self.sql.find("p_subtopics IS NULL")
        idx_type = self.sql.find("p_subtopics must be a JSON array")
        idx_obj = self.sql.find("p_subtopics elements must be objects")
        idx_del = self.sql.find("DELETE FROM public.user_subtopics")
        self.assertTrue(idx_null != -1 and idx_null < idx_del)
        self.assertTrue(idx_type != -1 and idx_type < idx_del)
        self.assertTrue(idx_obj != -1 and idx_obj < idx_del)

    def test_empty_array_clears_interests(self):
        self.assertIn("array_length(p_topics, 1) > 0", self.sql)

    def test_empty_array_clears_subtopics(self):
        self.assertIn("jsonb_array_length(p_subtopics) > 0", self.sql)

    def test_uses_on_conflict(self):
        self.assertIn("ON CONFLICT", self.sql)


if __name__ == "__main__":
    unittest.main(verbosity=2)
