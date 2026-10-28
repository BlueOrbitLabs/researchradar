"""Phase 3 tests for Owlume's normalized article record and dedupe merge."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feed_strategy as fs  # noqa: E402


class ArticleNormalizationTest(unittest.TestCase):
    def test_record_has_stable_id_and_both_url_forms(self):
        a = fs.normalize_article({
            "title": "Climate policy reduces carbon emissions",
            "url": "https://www.publisher.example/story/?utm_source=feed#top",
            "source": "Publisher", "topic": "Climate & Environment",
        }, retrieved_at="2026-10-27T10:00:00+00:00")
        b = fs.normalize_article({
            "title": "Another syndicated headline",
            "url": "http://publisher.example/story/",
            "source": "Publisher", "topic": "Climate & Environment",
        }, retrieved_at="2026-10-27T11:00:00+00:00")
        self.assertEqual(a["original_url"], "https://www.publisher.example/story/?utm_source=feed#top")
        self.assertEqual(a["canonical_url"], "https://publisher.example/story")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["retrieved_at"], "2026-10-27T10:00:00+00:00")

    def test_doi_identity_and_publication_retrieval_dates_are_separate(self):
        record = fs.normalize_article({
            "title": "A controlled trial of intervention A",
            "url": "https://doi.org/10.1234/EXAMPLE.1",
            "doi": "https://doi.org/10.1234/Example.1",
            "date": "25 Oct 2026", "date_source": "published",
            "source": "Example Journal", "summary": "Trial abstract.",
        }, retrieved_at="2026-10-27T12:00:00+00:00")
        self.assertEqual(record["doi"], "10.1234/example.1")
        self.assertEqual(record["publication_date"], "25 Oct 2026")
        self.assertEqual(record["date"], "25 Oct 2026")  # compatibility alias
        self.assertNotEqual(record["publication_date"], record["retrieved_at"])

    def test_updated_feed_date_is_not_promoted_to_publication_date(self):
        record = fs.normalize_article({
            "title": "An article updated by its publisher",
            "url": "https://publisher.example/updated",
            "date": "27 Oct 2026", "date_source": "updated",
            "updated_at": "27 Oct 2026", "source": "Publisher",
        }, retrieved_at="2026-10-27T12:00:00+00:00")
        self.assertEqual(record["date"], "27 Oct 2026")
        self.assertEqual(record["publication_date"], "")
        self.assertEqual(record["date_source"], "updated")
        self.assertEqual(record["updated_at"], "27 Oct 2026")
        self.assertNotEqual(record["updated_at"], record["retrieved_at"])

    def test_metadata_aliases_and_status_are_normalized(self):
        record = fs.normalize_article({
            "title": "A new machine learning method",
            "url": "https://example.org/ml", "source": "OpenAlex",
            "topic": "AI & Technology", "image_url": "https://img.example/ml.jpg",
            "retrieved_via": "OpenAlex", "summary": "An abstract.",
            "matched_interests": ["AI & Technology"],
            "matched_subtopics": ["Machine Learning"],
            "extraction_status": "abstract",
        })
        self.assertEqual(record["image"], "https://img.example/ml.jpg")
        self.assertEqual(record["source_adapter"], "openalex")
        self.assertEqual(record["content_type"], "research")
        self.assertEqual(record["matched_interests"], ["AI & Technology"])
        self.assertEqual(record["matched_subtopics"], ["Machine Learning"])
        self.assertEqual(record["extraction_status"], "abstract")
        self.assertTrue(record["metadata_status"]["summary"])
        self.assertTrue(record["metadata_status"]["image"])

    def test_duplicate_merge_preserves_richer_metadata_and_both_source_links(self):
        sparse = fs.normalize_article({
            "title": "Policy review of climate reporting rules",
            "url": "https://journal.example/policy", "source": "Journal",
            "topic": "Policy & Government", "date_source": "unknown",
        }, retrieved_at="2026-10-27T10:00:00+00:00")
        richer = fs.normalize_article({
            "title": "Policy review of climate reporting rules (updated)",
            "url": "https://www.journal.example/policy/?utm_medium=rss",
            "source": "Journal", "topic": "Policy & Government",
            "date": "26 Oct 2026", "publication_date": "26 Oct 2026",
            "date_source": "published", "summary": "A detailed policy abstract.",
            "image": "https://img.example/policy.jpg", "extraction_status": "abstract",
        }, retrieved_at="2026-10-27T10:01:00+00:00")
        merged = fs.dedupe_articles([sparse, richer])
        self.assertEqual(len(merged), 1)
        item = merged[0]
        self.assertEqual(item["summary"], "A detailed policy abstract.")
        self.assertEqual(item["image"], "https://img.example/policy.jpg")
        self.assertEqual(item["publication_date"], "26 Oct 2026")
        self.assertEqual(item["date_source"], "published")
        self.assertGreaterEqual(len(item["source_links"]), 2)
        self.assertTrue(item["metadata_status"]["publication_date"])

    def test_empty_and_non_dict_records_are_safe(self):
        self.assertEqual(fs.normalize_article(None), {})
        self.assertEqual(fs.dedupe_articles([None, "bad", {}]), [])

    def test_pool_attaches_matched_interest_and_subtopic_metadata(self):
        def loader(topic, _subtopics):
            return [{
                "title": "Vaccine study evaluates public health outcomes",
                "url": "https://health.example/vaccine-study",
                "summary": "Epidemiology and vaccine coverage results.",
                "source": "Health Journal", "topic": topic,
                "date": "2026-10-26", "relevance": 0.8,
            }]

        pool, errors = fs.build_pool(
            loader, ["Health & Medicine"],
            {"Health & Medicine": ["Vaccines", "Epidemiology"]},
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["retrieval_topic"], "Health & Medicine")
        self.assertEqual(pool[0]["matched_interests"], ["Health & Medicine"])
        self.assertIn("Epidemiology", pool[0]["matched_subtopics"])
        self.assertTrue(pool[0]["id"])
        self.assertTrue(pool[0]["metadata_status"]["publisher"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
