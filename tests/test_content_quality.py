"""Fixture-based tests for the content-quality gate, relevance and briefing.

Run with:  python3 -m unittest discover -s tests -v
No network access and no Streamlit runtime are required.

These tests use controlled fixtures. Real-source calibration is a separate,
manually run script (see the Phase 1B report) because live APIs are not
deterministic.
"""

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_quality as cq  # noqa: E402
import feed_strategy as fs  # noqa: E402

TODAY = date(2026, 10, 24)

HEALTH = {
    "keywords": ["health", "medicine", "healthcare", "public health", "clinical",
                 "medical", "hospital"],
    "subtopics": ["Public health", "Epidemiology", "Health economics",
                  "Clinical research", "Mental health", "Nutrition",
                  "Global health", "Vaccines", "Health policy"],
}


def article(title, url="https://example.org/a", summary="", date="2026-10-20",
            source="OpenAlex", topic="Health & Medicine", relevance=0.5, **extra):
    record = {"title": title, "url": url, "summary": summary, "date": date,
              "source": source, "topic": topic, "relevance": relevance}
    record.update(extra)
    return record


def score(record, topic="Health & Medicine", **kwargs):
    kwargs.setdefault("discipline_scoped", bool(record.get("discipline_scoped")))
    return cq.relevance_score(record, topic,
                              subtopics=HEALTH["subtopics"],
                              keywords=HEALTH["keywords"], **kwargs)


class GateTest(unittest.TestCase):
    def test_generic_landing_pages_are_rejected(self):
        cases = [
            "LibGuides: Health & Medicine: Health & Medicine",
            "LibGuides: Health & Medicine: Health & Medicine - Home",
            "Health & Medicine",
            "Subject Guide: Health & Medicine",
            "Category: Public health",
            "Search results for health",
        ]
        for title in cases:
            ok, reason = cq.validate(article(title), "Health & Medicine")
            self.assertFalse(ok, title)
            self.assertIn(reason, {"generic_title", "topic_page"})

    def test_journal_issue_pages_are_rejected(self):
        record = article("Journal of Health Economics",
                         container="Journal of Health Economics")
        ok, reason = cq.validate(record, "Health & Medicine")
        self.assertFalse(ok)
        self.assertEqual(reason, "journal_page")

    def test_promotional_listings_are_rejected(self):
        cases = [
            "Acme Health to present at the Annual Investor Conference",
            "Health-tech firm announces pricing of public offering",
            "Nasdaq: HLTX shares rise after earnings call",
        ]
        for title in cases:
            ok, reason = cq.validate(article(title), "AI & Technology")
            self.assertFalse(ok, title)
            self.assertEqual(reason, "promotional_listing")

    def test_reference_works_are_not_feed_articles(self):
        for title in ("Short textbook of public health medicine in the tropics",
                      "Oxford Handbook of Clinical Medicine",
                      "Encyclopedia of Health Economics"):
            ok, reason = cq.validate(article(title), "Health & Medicine")
            self.assertFalse(ok, title)
            self.assertEqual(reason, "reference_work")

    def test_invalid_and_missing_urls_are_rejected(self):
        for url, expected in (("", "missing_url"),
                              ("not a url", "invalid_url"),
                              ("ftp://example.org/x", "invalid_url")):
            ok, reason = cq.validate(article("A real article about vaccines", url=url))
            self.assertFalse(ok, url)
            self.assertEqual(reason, expected)

    def test_missing_metadata_is_handled_safely(self):
        # Non-dicts, empty titles, missing sources and unknown fields must be
        # rejected without raising.
        for record in (None, "text", {}, {"title": ""},
                       {"title": "A valid sounding title about health",
                        "url": "https://example.org/x"}):
            ok, reason = cq.validate(record, "Health & Medicine")
            self.assertFalse(ok, record)
            self.assertTrue(reason)

    def test_old_research_remains_eligible(self):
        record = article(
            "Long-term outcomes of childhood vaccination programmes",
            summary="A historical cohort analysis of clinical vaccination records "
                    "and public health outcomes over four decades.",
            date="1998-06-01", source="PubMed", discipline_scoped=True)
        ok, _ = cq.validate(record, "Health & Medicine")
        self.assertTrue(ok, "old research must not be rejected for being old")
        self.assertGreaterEqual(score(record), cq.RELEVANCE["relevant"])


class RelevanceTest(unittest.TestCase):
    def test_exact_topic_phrase_can_be_high(self):
        record = article(
            "Health & Medicine: evidence for a new clinical framework",
            summary="A review of medicine and public health practice.")
        self.assertEqual(cq.relevance_label(score(record)), "high")

    def test_single_shared_keyword_is_never_high(self):
        record = article("Hospital opens new wing", summary="")
        value = score(record)
        self.assertLess(value, cq.RELEVANCE["high"])
        self.assertNotEqual(cq.relevance_label(value), "high")

    def test_unrelated_article_has_no_label(self):
        record = article("Local football club wins the regional final",
                         summary="Sports coverage from the weekend.")
        value = score(record)
        self.assertEqual(value, 0.0)
        self.assertIsNone(cq.relevance_label(value))

    def test_career_piece_is_down_ranked_for_research_topics(self):
        record = article("How to build a career in public health",
                         summary="Tips for job interviews and promotions.")
        value = score(record, lifestyle_penalty=True)
        self.assertLess(value, cq.RELEVANCE["relevant"])
        # Careers is the field itself, so the penalty must not apply there.
        plain = score(record, topic="Careers", lifestyle_penalty=False)
        self.assertGreaterEqual(plain, value)

    def test_discipline_floor_gives_relevant_but_never_high(self):
        terse = article("Temocillin dosing in paediatric infection",
                        summary="", source="PubMed", discipline_scoped=True)
        value = score(terse)
        self.assertGreaterEqual(value, cq.RELEVANCE["discipline_floor"])
        self.assertLess(value, cq.RELEVANCE["high"])
        self.assertEqual(cq.relevance_label(value), "relevant")

    def test_thresholds_are_configurable(self):
        record = article("Hospital opens new wing")
        value = score(record)
        saved = cq.RELEVANCE["high"]
        try:
            cq.RELEVANCE["high"] = value
            self.assertEqual(cq.relevance_label(value), "high")
        finally:
            cq.RELEVANCE["high"] = saved

    def test_missing_relevance_metadata_does_not_crash(self):
        for bad in (None, "", "abc", []):
            self.assertIsNone(cq.relevance_label(bad))


class DiagnosticsTest(unittest.TestCase):
    """Diagnostics stay server-side and are emitted through ``logging``."""

    def test_rejections_are_logged_with_their_reason(self):
        with self.assertLogs("owlume.quality", level="INFO") as captured:
            kept, report = cq.filter_articles(
                [article("LibGuides: Health & Medicine: Health & Medicine")],
                "Health & Medicine")
        self.assertEqual(kept, [])
        self.assertEqual(report["generic_title"], 1)
        self.assertIn("rejected (generic_title)",
                      "\n".join(captured.output))

    def test_down_ranked_scores_are_logged(self):
        with self.assertLogs("owlume.quality", level="DEBUG") as captured:
            score(article("Hospital opens new wing"))
        self.assertIn("down-ranked", "\n".join(captured.output))


class DuplicateTest(unittest.TestCase):
    def test_duplicate_doi_is_collapsed(self):
        a = article("Vaccine effectiveness in older adults",
                    url="https://journal.example/1",
                    doi="10.1000/ABC")
        b = article("Vaccine effectiveness in older adults",
                    url="https://mirror.example/2",
                    doi="https://doi.org/10.1000/abc")
        self.assertEqual(len(fs.dedupe_articles([a, b])), 1)

    def test_duplicate_url_is_collapsed(self):
        a = article("Climate risk and coastal cities",
                    url="https://example.org/story?utm_source=x")
        b = article("Climate risk and coastal cities (updated)",
                    url="https://www.example.org/story/")
        self.assertEqual(len(fs.dedupe_articles([a, b])), 1)

    def test_same_title_different_publishers_keeps_corroboration(self):
        a = article("Central bank raises interest rates sharply",
                    url="https://a.example/x", source="Reuters")
        b = article("Central bank raises interest rates sharply",
                    url="https://b.example/y", source="BBC")
        pool = fs.dedupe_articles([a, b])
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["sources"], ["BBC", "Reuters"])


class BriefingTest(unittest.TestCase):
    def make_pool(self):
        return [
            article("New clinical guidance on hypertension management",
                    url="https://example.org/1", date="2026-10-23",
                    source="WHO", relevance=0.6),
            article("Vaccination programme expands across the region",
                    url="https://example.org/2", date="2026-10-20",
                    source="NIH", relevance=0.45),
            article("Mental health services receive new funding",
                    url="https://example.org/3", date="2026-10-18",
                    source="BBC", relevance=0.35),
            # Below the briefing relevance floor.
            article("Hospital opens new wing", url="https://example.org/4",
                    date="2026-10-22", source="BBC", relevance=0.10),
            # Outside the 7-day window.
            article("Old clinical guidance on hypertension management",
                    url="https://example.org/5", date="2026-01-05",
                    source="WHO", relevance=0.6),
            # Generic page that the gate must reject.
            article("LibGuides: Health & Medicine: Health & Medicine",
                    url="https://libguides.example/health", date="2026-10-21",
                    source="LibGuides", relevance=0.9),
            # Duplicate URL of the first item.
            article("New clinical guidance on hypertension management",
                    url="https://example.org/1?utm_source=feed",
                    date="2026-10-23", source="WHO", relevance=0.6),
            # No usable date.
            article("Uncertain date health record", url="https://example.org/6",
                    date="", source="BBC", relevance=0.5),
        ]

    def test_counts_match_the_eligible_set(self):
        result = cq.briefing_articles(self.make_pool(), today=TODAY)
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["publishers"], 3)
        self.assertEqual(result["window_days"], 7)
        titles = [a["title"] for a in result["items"]]
        self.assertFalse(any(t.startswith("LibGuides") for t in titles))
        self.assertEqual(len(set(a["url"].split("?")[0] for a in result["items"])), 3)

    def test_rejection_reasons_are_recorded_for_diagnostics(self):
        result = cq.briefing_articles(self.make_pool(), today=TODAY)
        self.assertGreaterEqual(result["rejected"]["generic_title"], 1)
        self.assertGreaterEqual(result["rejected"]["outside_window"], 1)
        self.assertGreaterEqual(result["rejected"]["low_relevance"], 1)
        self.assertGreaterEqual(result["rejected"]["duplicate"], 1)
        self.assertGreaterEqual(result["rejected"]["unknown_date"], 1)

    def test_empty_pool_returns_zero_counts(self):
        result = cq.briefing_articles([], today=TODAY)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["publishers"], 0)
        self.assertEqual(result["items"], [])


class FeedStrategyDistinctnessTest(unittest.TestCase):
    def test_four_strategies_select_distinct_results(self):
        pool = []
        for i in range(6):
            pool.append(article(f"Health economics study number {i}",
                                url=f"https://example.org/h{i}",
                                date="2026-10-23", relevance=0.5,
                                source=f"Health Journal {i}",
                                topic="Health Economics"))
        outside_titles = ["History of cartography", "Museum curation practices",
                          "Ancient trade routes", "Sound design in cinema",
                          "Philosophy of memory", "Urban gardening movements",
                          "Medieval manuscript studies", "Language and migration",
                          "Theatre in wartime", "Photography and archives"]
        for i, title in enumerate(outside_titles):
            pool.append(article(title, url=f"https://example.org/o{i}",
                                date="2026-10-23", relevance=0.4,
                                source=f"Arts Review {i}",
                                topic="Arts & Culture"))
        pool = fs.dedupe_articles(pool)

        for_you = fs.rank_for_you(pool, ["Health Economics"], {}, today=datetime(2026, 10, 24))
        my_fields = fs.rank_my_fields(pool, ["Health Economics"], {}, today=datetime(2026, 10, 24))
        emerging = fs.rank_emerging(pool, ["Health Economics"], {}, today=datetime(2026, 10, 24))
        broaden = fs.rank_broaden(pool, ["Health Economics"], {},
                                  outside_topics=["Arts & Culture"],
                                  today=datetime(2026, 10, 24))

        self.assertTrue(my_fields and emerging and for_you and broaden)
        self.assertTrue(all(a["topic"] == "Health Economics" for a in my_fields))
        self.assertTrue(all(a["topic"] == "Arts & Culture" for a in broaden))
        self.assertTrue(any(a["topic"] == "Arts & Culture" for a in for_you))
        self.assertTrue({a["title"] for a in my_fields}.isdisjoint(
            {a["title"] for a in broaden}))
        # Emerging only admits dated, recent records (freshness is a claim).
        self.assertTrue(all(fs.parse_date(a["date"]) is not None for a in emerging))

    def test_for_you_discovery_is_a_minority(self):
        pool = []
        for i in range(20):
            pool.append(article(f"User field research report {i}",
                                url=f"https://example.org/u{i}", relevance=0.5,
                                source=f"User Journal {i}",
                                topic="Health Economics"))
        for i in range(10):
            pool.append(article(f"Outside field research report {i}",
                                url=f"https://example.org/o{i}", relevance=0.5,
                                source=f"Outside Journal {i}",
                                topic="Arts & Culture"))
        feed = fs.rank_for_you(pool, ["Health Economics"], {},
                               today=datetime(2026, 10, 24))
        discovery = [a for a in feed if a["topic"] == "Arts & Culture"]
        self.assertGreater(len(discovery), 0)
        self.assertLessEqual(len(discovery),
                             fs.CONFIG["for_you"]["discovery_slots"])
        self.assertGreater(len(feed) - len(discovery), len(discovery))

    def test_low_relevance_is_excluded_from_every_feed(self):
        pool = [
            article("Solid health economics evidence", url="https://example.org/good",
                    relevance=0.5, topic="Health Economics"),
            article("Barely related mention", url="https://example.org/weak",
                    relevance=0.05, topic="Health Economics"),
        ]
        for ranker in (fs.rank_for_you, fs.rank_my_fields, fs.rank_emerging,
                       fs.rank_broaden):
            titles = [a["title"] for a in ranker(pool, ["Health Economics"], {},
                                                 today=datetime(2026, 10, 24))]
            self.assertNotIn("Barely related mention", titles, ranker.__name__)


class RetrievalFailureTest(unittest.TestCase):
    def test_one_failed_adapter_preserves_other_topics(self):
        def loader(topic, subtopics):
            if topic == "Broken":
                raise RuntimeError("adapter unavailable")
            return [article(f"Valid research output on health topic {topic}",
                            url=f"https://example.org/{topic}",
                            relevance=0.5, topic=topic)]

        pool, errors = fs.build_pool(loader, ["Working", "Broken"])
        self.assertEqual([a["topic"] for a in pool], ["Working"])
        self.assertEqual(len(errors), 1)

    def test_build_pool_drops_generic_pages_from_any_loader(self):
        def loader(topic, subtopics):
            return [
                article("LibGuides: Health & Medicine: Health & Medicine",
                        url="https://libguides.example/health",
                        relevance=0.9, topic=topic),
                article(f"A specific study about {topic} outcomes",
                        url=f"https://example.org/{topic}",
                        relevance=0.5, topic=topic),
            ]

        pool, _ = fs.build_pool(loader, ["Cardiology"])
        self.assertEqual([a["url"] for a in pool],
                         ["https://example.org/Cardiology"])


if __name__ == "__main__":
    unittest.main()


class BriefingGroupingTest(unittest.TestCase):
    def make_pool(self):
        return [
            {"title": "New malaria vaccine shows 70% efficacy in trial",
             "url": "https://a.org/1", "summary": "A trial reports efficacy.",
             "date": "2026-10-22", "source": "OpenAlex", "topic": "Health Economics",
             "relevance": 0.8},
            {"title": "Malaria vaccine trial reports 70 percent efficacy",
             "url": "https://b.org/2", "summary": "Results from a malaria vaccine study.",
             "date": "2026-10-22", "source": "PubMed", "topic": "Health Economics",
             "relevance": 0.75},
            {"title": "Central bank raises interest rates",
             "url": "https://c.org/3", "summary": "Rates rise again.",
             "date": "2026-10-23", "source": "Reuters", "topic": "Policy & Government",
             "relevance": 0.7},
        ]

    def test_grouping_reduces_items(self):
        result = cq.briefing_articles(self.make_pool(), today=TODAY, limit=10)
        # Two malaria articles should be grouped into one.
        self.assertLessEqual(len(result["items"]), 2)
        self.assertIn("groups", result)

    def test_preferences_change_briefing_order(self):
        r1 = cq.briefing_articles(self.make_pool(), today=TODAY, limit=10,
                                  preferences=["New research & journal publications"])
        r2 = cq.briefing_articles(self.make_pool(), today=TODAY, limit=10,
                                  preferences=["Current affairs & world events"])
        # Both return valid results
        self.assertTrue(len(r1["items"]) > 0)
        self.assertTrue(len(r2["items"]) > 0)
