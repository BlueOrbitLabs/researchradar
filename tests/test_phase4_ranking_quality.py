"""Phase 4 regression tests for freshness, relevance, provenance and ranking."""

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_quality as cq  # noqa: E402
import feed_strategy as fs  # noqa: E402

TODAY = datetime(2026, 10, 27)


def article(title, *, url, topic="Health & Medicine", source="Example Journal",
            date_str="2026-10-25", summary="", relevance=0.8, **extra):
    return {"title": title, "url": url, "topic": topic, "source": source,
            "date": date_str, "summary": summary, "relevance": relevance, **extra}


class DateAndFreshnessRegressionTest(unittest.TestCase):
    def test_missing_malformed_and_partial_dates(self):
        self.assertIsNone(cq.parse_date(""))
        self.assertIsNone(cq.parse_date("not-a-date"))
        self.assertEqual(cq.parse_date("2026-10"), date(2026, 10, 1))
        self.assertEqual(cq.parse_date("2026"), date(2026, 1, 1))
        self.assertIsNone(fs.parse_date("not-a-date"))
        self.assertIsNotNone(fs.parse_date("2026-10"))

    def test_update_only_date_is_not_freshness_or_briefing_publication_date(self):
        record = fs.normalize_article(article(
            "A recently updated but publication-undated study",
            url="https://example.org/updated-only", date_str="27 Oct 2026",
            date_source="updated", updated_at="27 Oct 2026"))
        pub_date = cq.publication_date_value(record)
        self.assertEqual(pub_date, "")
        self.assertEqual(fs.freshness(pub_date, TODAY), fs.UNKNOWN_FRESHNESS)
        self.assertEqual(fs.rank_emerging([record], [record["topic"]], {}, today=TODAY), [])
        brief = cq.briefing_articles([record], today=TODAY.date())
        self.assertEqual(brief["items"], [])

    def test_old_relevant_foundational_research_remains_in_my_fields(self):
        old = article(
            "Long-term outcomes of childhood vaccination programmes",
            url="https://pubmed.example/foundational", date_str="1998-06-01",
            source="PubMed", summary="Historical cohort analysis of vaccine programmes.",
            relevance=0.8, discipline_scoped=True)
        ranked = fs.rank_my_fields([old], ["Health & Medicine"], {}, today=TODAY)
        self.assertEqual([a["title"] for a in ranked], [old["title"]])
        self.assertEqual(fs.freshness(cq.publication_date_value(old), TODAY), fs.KNOWN_FRESHNESS_FLOOR)

    def test_freshness_does_not_overpower_stronger_subject_relevance(self):
        old_core = article(
            "Long-term outcomes of childhood vaccination programmes",
            url="https://nature.example/foundational", date_str="1998-06-01",
            source="Nature Medicine", relevance=0.9,
            summary="A foundational cohort study of vaccination programmes.")
        new_partial = article(
            "A recent update on health services",
            url="https://bbc.example/recent", date_str="2026-10-27",
            source="BBC", relevance=0.35,
            summary="A recent news item with a weaker subject match.")
        ranked = fs.rank_for_you([new_partial, old_core], ["Health & Medicine"], {}, today=TODAY)
        self.assertEqual(ranked[0]["url"], old_core["url"])

    def test_recent_irrelevant_article_does_not_clear_relevance_floor(self):
        irrelevant = article(
            "Regional football club wins the weekend final",
            url="https://sports.example/win", topic="Health & Medicine",
            source="Sports Daily", date_str="2026-10-27", relevance=0.1,
            summary="Local sports coverage.")
        self.assertEqual(fs.freshness(cq.publication_date_value(irrelevant), TODAY), 1.0)
        self.assertEqual(fs.rank_for_you([irrelevant], ["Health & Medicine"], {}, today=TODAY), [])
        self.assertEqual(fs.rank_my_fields([irrelevant], ["Health & Medicine"], {}, today=TODAY), [])

    def test_future_publication_is_not_a_recent_emerging_development(self):
        future = article("A study of vaccine coverage and health outcomes",
                         url="https://example.org/future", date_str="2026-11-01",
                         relevance=0.8)
        self.assertEqual(fs.rank_emerging([future], [future["topic"]], {}, today=TODAY), [])


class SourceQualityRegressionTest(unittest.TestCase):
    def test_provider_name_alone_does_not_raise_publisher_credibility(self):
        for provider in ("OpenAlex", "PubMed", "arXiv", "DOAJ", "NBER", "Crossref"):
            with self.subTest(provider=provider):
                self.assertEqual(fs.source_quality({"source": provider}), fs.UNKNOWN_QUALITY)
                self.assertEqual(fs.source_quality({"source": "Unknown Outlet",
                                                    "retrieved_via": provider}),
                                 fs.UNKNOWN_QUALITY)

    def test_known_publisher_name_remains_a_heuristic_signal(self):
        self.assertGreater(fs.source_quality({"source": "Nature Medicine"}), 0.8)
        self.assertIsNone(fs.source_quality({"source": "Unknown Outlet"}))

    def test_publisher_matches_use_name_boundaries_not_substrings(self):
        self.assertIsNone(fs.source_quality({"source": "Whole Foods Market"}))

    def test_government_domain_evidence_requires_a_domain_field(self):
        self.assertIsNone(fs.source_quality({"source": "Example Outlet"}))
        self.assertGreater(fs.source_quality({"source": "Example Outlet",
                                              "publisher_domain": "agency.gov"}), 0.8)

    def test_unknown_credibility_is_omitted_not_scored_as_neutral(self):
        self.assertIsNone(fs.source_quality({"source": "Unverified New Outlet"}))
        self.assertEqual(fs._weighted({"relevance": 0.7, "quality": None},
                                      {"relevance": 0.5, "quality": 0.5}), 0.7)


class DuplicateConflictRegressionTest(unittest.TestCase):
    def test_same_doi_different_urls_merges_and_retains_original_links(self):
        a = article("Trial of intervention A", url="https://index.example/record",
                    source="OpenAlex", date_str="2026-10-20", summary="",
                    doi="10.1234/example.1", source_adapter="openalex",
                    content_type_source="heuristic")
        b = article("Trial of intervention A", url="https://nature.example/article",
                    source="Nature Medicine", date_str="2026-10-21",
                    summary="A more complete trial abstract.", doi="10.1234/example.1",
                    source_adapter="pubmed", content_type="research",
                    content_type_source="provider", extraction_status="abstract")
        merged = fs.dedupe_articles([a, b])
        self.assertEqual(len(merged), 1)
        record = merged[0]
        self.assertEqual(record["source"], "Nature Medicine")
        self.assertEqual(record["summary"], "A more complete trial abstract.")
        self.assertEqual(record["publication_date"], "2026-10-21")
        self.assertEqual(record["content_type_source"], "provider")
        self.assertEqual({link["url"] for link in record["source_links"]},
                         {a["url"], b["url"]})
        self.assertEqual(len(record["id"]), 32)

    def test_conflicting_published_dates_are_recorded_not_silently_lost(self):
        a = article("Policy analysis of carbon reporting", url="https://a.example/policy",
                    topic="Policy & Government", date_str="2026-10-20",
                    doi="10.1234/policy.2", source="Example Journal")
        b = article("Policy analysis of carbon reporting", url="https://b.example/policy",
                    topic="Policy & Government", date_str="2026-10-21",
                    doi="10.1234/policy.2", source="Other Journal")
        merged = fs.dedupe_articles([a, b])[0]
        self.assertEqual(merged["publication_date"], "2026-10-20")
        self.assertEqual(len(merged.get("date_conflicts", [])), 2)
        self.assertEqual({x["source"] for x in merged["date_conflicts"]},
                         {"Example Journal", "Other Journal"})

    def test_distinct_similar_titles_remain_separate(self):
        one = article("Climate policy effects on coastal cities", url="https://a.example/1",
                      topic="Climate & Environment", relevance=0.6)
        two = article("Coastal city adaptation finance under climate risk", url="https://b.example/2",
                      topic="Climate & Environment", relevance=0.6)
        self.assertEqual(len(fs.dedupe_articles([one, two])), 2)

    def test_missing_source_summary_topic_and_subtype_are_safe(self):
        sparse = fs.normalize_article({"title": "An article with sparse fields",
                                       "url": "https://example.org/sparse"})
        self.assertEqual(sparse["source"], "")
        self.assertEqual(sparse["summary"], "")
        self.assertEqual(sparse["topic"], "")
        self.assertEqual(sparse["matched_interests"], [])
        self.assertEqual(sparse["matched_subtopics"], [])
        self.assertEqual(sparse["_subtypes"] if "_subtypes" in sparse else [], [])
        self.assertFalse(sparse["metadata_status"]["publisher"])

    def test_dedupe_output_has_unique_ids_and_valid_record_shapes(self):
        rows = [
            article("Unique vaccine study findings for older adults", url="https://x.example/a",
                    doi="10.1234/x.1"),
            article("Unique vaccine study findings for older adults", url="https://y.example/b",
                    doi="10.1234/x.1", summary="Abstract."),
            article("Independent climate policy report for cities", url="https://z.example/c",
                    topic="Climate & Environment"),
        ]
        output = fs.dedupe_articles(rows)
        self.assertEqual(len(output), 2)
        self.assertEqual(len({a["id"] for a in output}), len(output))
        for record in output:
            self.assertTrue(record["original_url"])
            self.assertTrue(record["canonical_url"])
            self.assertIn(record["date_source"], {"published", "updated", "unknown"})
            self.assertIsInstance(record["metadata_status"], dict)

    def test_pool_drops_malformed_records_and_keeps_sparse_valid_record(self):
        good = article("Vaccine trial evaluates coverage in older adults",
                       url="https://health.example/trial", relevance=0.8,
                       summary="", source="Health Journal")
        bad_url = article("Vaccine trial evaluates coverage in older adults",
                          url="javascript:alert(1)", relevance=0.8)
        missing_source = article("Vaccine trial evaluates coverage in older adults",
                                 url="https://health.example/no-source", source="",
                                 relevance=0.8)
        pool, errors = fs.build_pool(lambda *_: [good, bad_url, missing_source],
                                     ["Health & Medicine"])
        self.assertEqual(errors, [])
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["summary"], "")
        self.assertEqual(pool[0]["matched_interests"], ["Health & Medicine"])

    def test_local_news_remains_out_of_general_pool_and_separate(self):
        called = []

        def loader(topic, _subs):
            called.append(topic)
            return [article("A valid local health story for residents",
                            url=f"https://example.org/{topic.replace(' ', '-')}",
                            topic=topic, relevance=0.8)]

        pool, errors = fs.build_pool(
            loader, ["Health & Medicine", "Local News & Community"],
            discovery_topics=["Arts & Culture", "Local News & Community"])
        self.assertEqual(errors, [])
        self.assertNotIn("Local News & Community", called)
        self.assertTrue(all(a["topic"] != "Local News & Community" for a in pool))


class RelevanceAliasExperimentTest(unittest.TestCase):
    """Deterministic curated multiword aliases; no per-article model calls."""

    KEYWORDS = ["artificial intelligence", "machine learning", "AI",
                "technology", "robotics", "data science"]
    SUBTOPICS = ["Artificial Intelligence", "Machine Learning", "AI Safety"]

    def score(self, title, summary=""):
        return cq.explain_relevance(
            {"title": title, "summary": summary}, "AI & Technology",
            keywords=self.KEYWORDS, subtopics=self.SUBTOPICS,
            core_terms=["AI & Technology"], terms=["AI & Technology"])

    def test_curated_ai_alias_rescues_fixture_false_negative(self):
        result = self.score(
            "Artificial intelligence model improves medical imaging accuracy",
            "Researchers evaluate a machine learning method for medical imaging.")
        self.assertTrue(result["signals"]["alias_title"])
        self.assertGreaterEqual(result["score"], cq.RELEVANCE["relevant"])

    def test_phase2_ai_candidate_count_improves_without_false_positive_fixture(self):
        # Same fixture case that scored 0.225 before the alias experiment.
        result = self.score(
            "Artificial intelligence model improves medical imaging accuracy",
            "Researchers evaluate a machine learning method for medical imaging.")
        self.assertGreaterEqual(result["score"], cq.RELEVANCE["relevant"])
        unrelated = self.score("Regional arts festival announces a new programme",
                               "Community events and performances are planned.")
        self.assertEqual(unrelated["score"], 0.0)

    def test_machine_learning_alias_in_summary_is_relevant_but_not_high(self):
        result = self.score("A new safety benchmark for computational systems",
                            "The machine learning benchmark exposes model failure modes.")
        self.assertTrue(result["signals"]["alias_summary"])
        self.assertGreaterEqual(result["score"], cq.RELEVANCE["relevant"])
        self.assertLess(result["score"], cq.RELEVANCE["high"])

    def test_unrelated_item_gets_no_alias_boost(self):
        result = self.score("Regional arts festival announces a new programme",
                            "Community events and performances are planned.")
        self.assertFalse(result["signals"]["alias_title"])
        self.assertFalse(result["signals"]["alias_summary"])
        self.assertEqual(result["score"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
