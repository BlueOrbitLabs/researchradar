"""Fixture-based tests for Owlume's four feed strategies.

Run with:  python3 -m unittest discover -s tests -v
No network access and no Streamlit runtime are required.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feed_strategy as fs  # noqa: E402

TODAY = datetime(2026, 10, 24)


def art(title, url="", source="OpenAlex", date="2026-10-20", topic="Health Economics",
        relevance=0.5, summary="", **extra):
    record = {"title": title, "url": url or f"https://example.org/{abs(hash(title))}",
              "summary": summary, "date": date, "source": source,
              "topic": topic, "relevance": relevance}
    record.update(extra)
    return record


def titles(articles):
    return [a["title"] for a in articles]


class RankingBasicsTest(unittest.TestCase):
    # 1. Interests influence My Fields ranking
    def test_my_fields_prefers_user_interests(self):
        pool = [
            art("Health financing reform in low-income countries",
                topic="Health Economics", relevance=0.9),
            art("Celebrity fashion trends this season",
                topic="Arts & Culture", relevance=0.9),
        ]
        ranked = fs.rank_my_fields(pool, ["Health Economics"], {}, today=TODAY)
        self.assertEqual(titles(ranked),
                         ["Health financing reform in low-income countries"])

    # 2. Custom interests work exactly as supplied
    def test_custom_interest_is_retrievable(self):
        pool = [
            art("Fungal networks in temperate forests", topic="Mycology",
                relevance=0.8),
            art("Quarterly earnings beat expectations", topic="Finance & Markets",
                relevance=0.8),
        ]
        ranked = fs.rank_my_fields(pool, ["Mycology"], {}, today=TODAY)
        self.assertEqual(titles(ranked), ["Fungal networks in temperate forests"])

    # 3. Selected subtopics improve precision
    def test_subtopic_match_increases_score(self):
        pool = [
            art("Hospital reimbursement models compared",
                topic="Health Economics", relevance=0.6,
                summary="A review of payment systems."),
            art("Hospital reimbursement and health system financing",
                topic="Health Economics", relevance=0.6,
                summary="Health financing and insurance design."),
        ]
        subs = {"Health Economics": ["Health financing"]}
        ranked = fs.rank_my_fields(pool, ["Health Economics"], subs, today=TODAY)
        self.assertIn("financing", ranked[0]["title"].lower())

    # 4. Information preferences influence content-type selection
    def test_research_preference_prioritises_research(self):
        pool = [
            art("Election results reshape regional politics",
                source="The Hindu", topic="Policy & Government", relevance=0.6),
            art("A randomised trial of a new malaria vaccine",
                source="The Hindu", topic="Policy & Government", relevance=0.6),
        ]
        with_pref = fs.rank_my_fields(
            pool, ["Policy & Government"], {},
            preferences=["New research & journal publications"], today=TODAY)
        self.assertTrue(with_pref[0]["title"].startswith("A randomised trial"))

    def test_unselected_preferences_do_not_apply(self):
        article = art("A randomised trial of a new vaccine")
        self.assertEqual(fs.preference_match(article, []), 0.0)
        self.assertEqual(fs.preference_match(article, ["Practical explainers & background knowledge"]), 0.0)

    # 5. For You combines interest relevance with modest discovery
    def test_for_you_includes_discovery_but_keeps_strong_matches_on_top(self):
        pool = [
            art("Health system financing reform", topic="Health Economics",
                relevance=0.95),
            art("Ancient trade routes re-examined", topic="World Affairs",
                relevance=0.6),
        ]
        ranked = fs.rank_for_you(pool, ["Health Economics"], {}, today=TODAY)
        self.assertEqual(ranked[0]["title"], "Health system financing reform")
        self.assertIn("Ancient trade routes re-examined", titles(ranked),
                      "a modest amount of outside-interest discovery is expected")

    # 6. Emerging applies a distinct strategy
    def test_emerging_is_not_my_fields_sorted_by_date(self):
        pool = [
            art("Landmark health financing study", source="OpenAlex",
                date="2019-05-01", topic="Health Economics", relevance=0.9),
            art("Central bank raises interest rates sharply", source="Reuters",
                date="2026-10-23", topic="Finance & Markets", relevance=0.25),
            art("Central bank raises interest rates again", source="BBC",
                date="2026-10-23", topic="Finance & Markets", relevance=0.25),
        ]
        my_fields = fs.rank_my_fields(pool, ["Health Economics"], {}, today=TODAY)
        emerging = fs.rank_emerging(pool, ["Health Economics"], {}, today=TODAY)
        self.assertEqual(my_fields[0]["title"], "Landmark health financing study")
        self.assertIn("Central bank", emerging[0]["title"])
        self.assertNotEqual(titles(my_fields)[:1], titles(emerging)[:1])

    def test_corroboration_rewards_multiple_sources(self):
        pool = [
            art("Central bank raises interest rates", source="Reuters"),
            art("Central bank raises interest rates again", source="BBC"),
            art("Unrelated botanical survey of alpine moss", source="DOAJ"),
        ]
        scores = fs.corroboration_scores(pool)
        self.assertGreater(scores[id(pool[0])], 0.0)
        self.assertEqual(scores[id(pool[2])], 0.0)

    def test_emerging_gives_a_small_nudge_to_user_fields(self):
        pool = [
            art("Outside field development report", topic="Arts & Culture",
                source="BBC", date="2026-10-23", relevance=0.5),
            art("User field development report", topic="Health Economics",
                source="BBC", date="2026-10-23", relevance=0.5),
        ]
        ranked = fs.rank_emerging(pool, ["Health Economics"], {}, today=TODAY)
        self.assertEqual(ranked[0]["topic"], "Health Economics")

    def test_emerging_puts_corroborated_developments_first(self):
        pool = [
            art("Narrow laboratory note on enzyme kinetics", topic="Health Economics",
                source="OpenAlex", date="2026-10-23", relevance=0.95),
            art("Central bank raises interest rates sharply", topic="Policy & Government",
                source="Reuters", date="2026-10-22", relevance=0.2),
            art("Central bank raises interest rates again", topic="Policy & Government",
                source="BBC", date="2026-10-22", relevance=0.2),
        ]
        emerging = fs.rank_emerging(pool, ["Health Economics"], {}, today=TODAY)
        for_you = fs.rank_for_you(pool, ["Health Economics"], {}, today=TODAY)
        self.assertIn("Central bank", emerging[0]["title"])
        self.assertEqual(for_you[0]["title"], "Narrow laboratory note on enzyme kinetics")

    # 7. Broaden returns material outside primary interests
    def test_broaden_prefers_outside_topics(self):
        pool = [art(f"Health economics paper {i}", topic="Health Economics")
                for i in range(10)]
        outside_titles = [
            "History of cartography", "Museum curation practices",
            "Ancient trade routes", "Sound design in cinema",
            "Philosophy of memory", "Urban gardening movements",
            "Medieval manuscript studies", "Language and migration",
            "Theatre in wartime", "Photography and archives",
        ]
        pool += [art(title, topic="Arts & Culture") for title in outside_titles]
        ranked = fs.rank_broaden(fs.dedupe_articles(pool), ["Health Economics"], {},
                                 outside_topics=["Arts & Culture"], today=TODAY)
        self.assertTrue(ranked)
        self.assertTrue(all(a["topic"] == "Arts & Culture" for a in ranked))

    def test_broaden_falls_back_to_accessible_in_interest_items(self):
        pool = [art("Explainer: how health financing works",
                    topic="Health Economics", summary="A beginner's guide") ]
        ranked = fs.rank_broaden(pool, ["Health Economics"], {},
                                 outside_topics=["Arts & Culture"], today=TODAY)
        self.assertEqual(len(ranked), 1)

    # 12. Missing metadata does not crash ranking
    def test_missing_metadata_is_tolerated(self):
        sparse = {"title": "Only a title", "url": "https://example.org/x",
                  "topic": "Health Economics"}
        for ranker in (fs.rank_for_you, fs.rank_my_fields, fs.rank_emerging):
            result = ranker([sparse], ["Health Economics"], {}, today=TODAY)
            self.assertEqual(len(result), 1, ranker.__name__)
        self.assertEqual(len(fs.rank_broaden([sparse], [], {}, today=TODAY)), 1)

    # 14. Empty pools yield empty feeds
    def test_empty_pool_returns_empty_feed(self):
        for ranker in (fs.rank_for_you, fs.rank_my_fields, fs.rank_emerging, fs.rank_broaden):
            self.assertEqual(ranker([], ["Health Economics"], {}, today=TODAY), [])


class DedupeTest(unittest.TestCase):
    # 8. DOI duplicates collapse
    def test_doi_duplicates_collapse(self):
        a = art("Health financing in India", url="https://doi.org/10.1016/j.health.2026.01",
                doi="10.1016/j.health.2026.01")
        b = art("Health financing in India (preprint)",
                url="https://doi.org/10.1016/J.HEALTH.2026.01",
                doi="10.1016/J.HEALTH.2026.01")
        self.assertEqual(len(fs.dedupe_articles([a, b])), 1)

    # 9. Canonical URL duplicates collapse
    def test_canonical_url_duplicates_collapse(self):
        a = art("Quantum sensors reach new precision",
                url="https://www.example.com/news/quantum-sensors?utm_source=x")
        b = art("Different headline, same page",
                url="http://example.com/news/quantum-sensors/")
        self.assertEqual(len(fs.dedupe_articles([a, b])), 1)

    # 10. Title fallback catches near-duplicates without over-collapsing
    def test_title_fallback(self):
        a = art("Global malaria vaccine rollout expands across Africa")
        b = art("Global malaria vaccine rollout expands across Africa today")
        c = art("Global shipping rates fall as demand cools")
        deduped = fs.dedupe_articles([a, b, c])
        self.assertEqual(len(deduped), 2)

    def test_distinct_articles_are_kept(self):
        articles = [art("Health financing reform"), art("Fungal networks in forests"),
                    art("Central bank raises rates")]
        self.assertEqual(len(fs.dedupe_articles(articles)), 3)

    def test_merge_keeps_richest_fields(self):
        a = art("Same story headline about water policy", summary="", date="")
        b = art("Same story headline about water policy today", summary="Filled",
                date="2026-10-01")
        merged = fs.dedupe_articles([a, b])[0]
        self.assertEqual(merged["summary"], "Filled")
        self.assertEqual(merged["date"], "2026-10-01")

    def test_merge_remembers_distinct_sources_for_corroboration(self):
        a = art("Global malaria vaccine rollout expands across Africa",
                url="https://a.example/story", source="Reuters")
        b = art("Global malaria vaccine rollout expands across Africa",
                url="https://b.example/story", source="BBC")
        deduped = fs.dedupe_articles([a, b])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["sources"], ["BBC", "Reuters"])
        scores = fs.corroboration_scores(deduped)
        self.assertGreater(scores[id(deduped[0])], 0.0)

    def test_generic_words_do_not_fake_corroboration(self):
        pool = [
            art("Cyclotron expansion to accelerate precision medicine", source="Reuters"),
            art("School of medicine hosts regional education summit", source="BBC"),
        ]
        scores = fs.corroboration_scores(pool)
        self.assertEqual(scores[id(pool[0])], 0.0)
        self.assertEqual(scores[id(pool[1])], 0.0)

    def test_aggregator_locales_do_not_fake_corroboration(self):
        pool = [
            art("Global malaria vaccine rollout expands across Africa - The Hindu",
                source="Google News"),
            art("Global malaria vaccine rollout expands across Africa today - The Hindu",
                source="Google News India"),
        ]
        scores = fs.corroboration_scores(pool)
        self.assertEqual(scores[id(pool[0])], 0.0)

    def test_same_story_from_two_publishers_counts_as_corroboration(self):
        pool = [
            art("Global malaria vaccine rollout expands across Africa - The Hindu",
                source="Google News"),
            art("Global malaria vaccine rollout expands across Africa - Reuters",
                source="Google News India"),
        ]
        scores = fs.corroboration_scores(pool)
        self.assertGreater(scores[id(pool[0])], 0.0)


class DiversityTest(unittest.TestCase):
    # 11. Publisher/topic caps when enough candidates exist
    def test_publisher_cap(self):
        pool = [art(f"Story number {i} about markets", source="Times of India",
                    topic=f"Topic {i}") for i in range(10)]
        ranked = fs.rank_for_you(pool, [f"Topic {i}" for i in range(10)], {}, today=TODAY)
        self.assertLessEqual(len(ranked), fs.CONFIG["for_you"]["max_per_source"])

    def test_topic_cap(self):
        pool = [art(f"Health story {i}", source=f"Source {i}", topic="Health Economics")
                for i in range(10)]
        ranked = fs.rank_my_fields(pool, ["Health Economics"], {}, today=TODAY)
        self.assertLessEqual(len(ranked), fs.CONFIG["my_fields"]["max_per_topic"])

    def test_caps_do_not_apply_when_candidates_are_scarce(self):
        pool = [art("Single story", source="Source A", topic="Health Economics")]
        self.assertEqual(len(fs.rank_for_you(pool, ["Health Economics"], {}, today=TODAY)), 1)

    def test_aggregator_cap_counts_real_publishers(self):
        # Twelve stories arrive via Google News but from twelve outlets: the
        # per-publisher cap must not collapse the feed as if they were one source.
        pool = [art(f"Story number {i} about markets - Outlet {i}",
                    source="Google News", topic=f"Topic {i}") for i in range(12)]
        ranked = fs.rank_for_you(pool, [f"Topic {i}" for i in range(12)], {}, today=TODAY)
        self.assertEqual(len(ranked), 12)

    def test_aggregator_cap_still_limits_a_repeating_publisher(self):
        pool = [art(f"Story number {i} about markets - Same Outlet",
                    source="Google News", topic=f"Topic {i}") for i in range(12)]
        ranked = fs.rank_for_you(pool, [f"Topic {i}" for i in range(12)], {}, today=TODAY)
        self.assertLessEqual(len(ranked), fs.CONFIG["for_you"]["max_per_source"])


class RetrievalTest(unittest.TestCase):
    # 13. A failed loader does not discard other topics
    def test_failed_source_preserves_other_results(self):
        def loader(topic, subtopics):
            if topic == "Broken Topic":
                raise RuntimeError("adapter unavailable")
            return [art(f"{topic} article", topic=topic)]

        pool, errors = fs.build_pool(
            loader, ["Working Topic", "Broken Topic"],
            discovery_topics=["Discovery Topic"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["topic"], "Broken Topic")
        self.assertEqual(sorted(a["topic"] for a in pool),
                         ["Discovery Topic", "Working Topic"])

    def test_total_failure_returns_empty_pool_with_errors(self):
        def loader(topic, subtopics):
            raise RuntimeError("offline")

        pool, errors = fs.build_pool(loader, ["A", "B"])
        self.assertEqual(pool, [])
        self.assertEqual(len(errors), 2)

    def test_build_pool_deduplicates_across_topics(self):
        def loader(topic, subtopics):
            return [art("Shared story about water policy",
                        url="https://example.com/water", topic=topic)]

        pool, errors = fs.build_pool(loader, ["A", "B"])
        self.assertEqual(len(pool), 1)
        self.assertEqual(errors, [])

    def test_discovery_topics_are_bounded_and_outside_interests(self):
        catalogue = ["Health Economics", "Arts & Culture", "World Affairs",
                     "Science & Research", "Local News & Community"]
        picks = fs.choose_discovery_topics(
            catalogue, ["Health Economics"], limit=2, seed=fs.stable_seed("x"))
        self.assertEqual(len(picks), 2)
        self.assertNotIn("Health Economics", picks)
        self.assertNotIn("Local News & Community", picks)
        # deterministic
        self.assertEqual(picks, fs.choose_discovery_topics(
            catalogue, ["Health Economics"], limit=2, seed=fs.stable_seed("x")))


class SearchTest(unittest.TestCase):
    # 16. Search filters the rendered feed without reordering it
    def test_search_preserves_order(self):
        feed = [art("Alpha story about vaccines"), art("Beta story about vaccines"),
                art("Gamma story about markets")]
        result = fs.search_articles(feed, "VACCINES")
        self.assertEqual(titles(result), ["Alpha story about vaccines",
                                          "Beta story about vaccines"])

    def test_empty_search_returns_feed_unchanged(self):
        feed = [art("A"), art("B")]
        self.assertEqual(fs.search_articles(feed, ""), feed)

    def test_search_matches_summary(self):
        feed = [art("Headline", summary="Contains a unique phrase zebracorn")]
        self.assertEqual(len(fs.search_articles(feed, "zebracorn")), 1)


class PreferenceAndProfileTest(unittest.TestCase):
    def test_grants_preference_matches_opportunities(self):
        article = art("Call for proposals: research fellowship in public health")
        self.assertEqual(
            fs.preference_match(article, ["Grants, fellowships & opportunities"]), 1.0)
        self.assertEqual(fs.infer_content_type(article), "grants")

    def test_local_preference_does_not_drive_general_feed(self):
        self.assertEqual(
            fs.preference_match(art("City council approves new park"),
                                ["Local news & community updates"]), 0.0)

    def test_profile_is_a_soft_signal(self):
        research = art("A randomised trial of treatment X", source="OpenAlex")
        news = art("Election results announced", source="Reuters")
        self.assertGreater(fs.profile_affinity(research, "PhD Scholar / Researcher"),
                           fs.profile_affinity(news, "PhD Scholar / Researcher"))
        self.assertGreater(fs.profile_affinity(news, "Competitive Exam Aspirant"),
                           fs.profile_affinity(research, "Competitive Exam Aspirant"))

    def test_profile_never_excludes_content(self):
        pool = [art("Election results announced", topic="Policy & Government")]
        ranked = fs.rank_my_fields(pool, ["Policy & Government"], {},
                                   role="PhD Scholar / Researcher", today=TODAY)
        self.assertEqual(len(ranked), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
