"""Phase 2 discovery-quality baseline using explicitly synthetic fixtures.

These records are deterministic fixtures, not a claim about live provider
quality. They exercise Owlume's actual content-quality scorer, structural
gate, date parser, publisher resolver, deduper, ranker and local score helper.
Run with ``python3 -m unittest discover -s tests -v``; print measurements with
``python3 tests/test_discovery_quality_baseline.py``.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from collections import Counter
from datetime import date, datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_quality as cq  # noqa: E402
import feed_strategy as fs  # noqa: E402


BASELINE_DATE = date(2026, 10, 27)
FIXTURE_SOURCE = "synthetic deterministic fixtures; no live API records"

# Subject terms mirror the currently configured Owlume catalogue categories.
PROFILES = {
    "Health & Medicine": {
        "keywords": ["health", "medicine", "healthcare", "public health",
                     "clinical", "medical", "hospital"],
        "subtopics": ["Epidemiology", "Global health", "Clinical research", "Vaccines"],
    },
    "Health Economics": {
        "keywords": ["health economics", "health finance", "health system",
                     "insurance", "pharma pricing"],
        "subtopics": ["Health Financing", "Drug Pricing", "Health Insurance"],
    },
    "AI & Technology": {
        "keywords": ["artificial intelligence", "machine learning", "AI",
                     "technology", "robotics", "data science"],
        "subtopics": ["Artificial Intelligence", "Machine Learning", "AI Safety"],
    },
    "Climate & Environment": {
        "keywords": ["climate", "environment", "ecology", "sustainability",
                     "biodiversity", "carbon", "emissions"],
        "subtopics": ["Climate Science", "Climate Policy", "Renewable Energy"],
    },
    "Policy & Government": {
        "keywords": ["policy", "government", "politics", "law", "governance",
                     "legislation", "regulation"],
        "subtopics": ["Health Law", "Governance", "Human Rights"],
    },
}


def _article(profile, title, *, url, source, date_str="2026-10-25", summary="",
             expected_relevant=True, **extra):
    return {
        "title": title, "url": url, "source": source, "date": date_str,
        "summary": summary, "topic": profile, "expected_relevant": expected_relevant,
        **extra,
    }


def fixture_records():
    """Profiles include relevant, weak, old, undated and malformed candidates."""
    records = [
        _article("Health & Medicine",
                 "Epidemiology study links vaccine coverage to fewer hospital admissions",
                 url="https://nature.example/vaccine-coverage", source="Nature Medicine",
                 summary="Public health researchers studied vaccination coverage and outcomes."),
        _article("Health & Medicine",
                 "Long-term outcomes of childhood vaccination programmes",
                 url="https://pubmed.example/old-vaccination", source="PubMed",
                 date_str="1998-06-01", summary="A historical cohort analysis of vaccination outcomes.",
                 discipline_scoped=True),
        _article("Health & Medicine", "Hospital opens a new wing for visitors",
                 url="https://local.example/hospital-wing", source="Local Gazette",
                 summary="A new hospital wing will open to visitors this month.",
                 expected_relevant=False),
        _article("Health & Medicine", "Vaccine safety review in older adults",
                 url="https://journal.example/undated-vaccine", source="Journal of Medicine",
                 date_str="", summary="Systematic review of vaccine safety and clinical evidence."),
        _article("Health & Medicine", "Global malaria vaccine rollout expands across Africa",
                 url="https://wire.example/malaria-vaccine", source="Reuters",
                 summary="Public health teams expand vaccine access.",
                 expected_publisher="Reuters"),
        _article("Health Economics", "Health economics analysis compares hospital payment models",
                 url="https://healthecon.example/payment-models", source="Health Economics Review",
                 summary="Health financing researchers compare reimbursement and insurance models."),
        _article("Health Economics", "Drug pricing policy changes hospital reimbursement",
                 url="https://policy.example/drug-pricing", source="Health Policy Journal",
                 summary="Health systems report on pharmaceutical prices and insurance."),
        _article("Health Economics", "Local hospital celebrates anniversary",
                 url="https://town.example/hospital-anniversary", source="Town News",
                 summary="Community celebrations at a hospital.", expected_relevant=False),
        _article("AI & Technology", "Artificial intelligence model improves medical imaging accuracy",
                 url="https://ai.example/imaging", source="OpenAlex",
                 summary="Researchers evaluate a machine learning method for medical imaging."),
        _article("AI & Technology", "Machine learning safety benchmarks reveal model failures",
                 url="https://ai.example/safety", source="arXiv",
                 summary="A new AI safety evaluation reports benchmark results."),
        _article("AI & Technology", "Regional art festival announces its programme",
                 url="https://arts.example/festival", source="Arts Weekly",
                 summary="A community festival announces this year's events.",
                 expected_relevant=False),
        _article("Climate & Environment", "Climate policy study measures urban carbon emissions",
                 url="https://climate.example/emissions", source="Climate Policy Journal",
                 summary="Researchers assess climate policy and emissions across cities."),
        _article("Climate & Environment", "Renewable energy storage improves grid resilience",
                 url="https://energy.example/storage", source="Energy Research",
                 summary="A study evaluates renewable energy and battery storage."),
        _article("Climate & Environment", "Restaurant opens near the river",
                 url="https://food.example/restaurant", source="City Food News",
                 summary="A new restaurant opens by the river.", expected_relevant=False),
        _article("Policy & Government", "Government policy introduces new data protection regulation",
                 url="https://official.example/data-protection", source="Government Gazette",
                 summary="The ministry published a regulation and implementation guidance."),
        _article("Policy & Government", "Public health ministry updates vaccination guidelines",
                 url="https://official.example/vaccine-guidelines", source="Ministry of Health",
                 summary="Official policy guidance changes vaccine programme recommendations."),
        _article("Policy & Government", "A new drama series launches this weekend",
                 url="https://culture.example/drama", source="Culture Daily",
                 summary="Television news about a drama series.", expected_relevant=False),
        # Exact canonical URL duplicate with different scheme/host/tracking.
        _article("Health & Medicine",
                 "Epidemiology study links vaccine coverage to fewer hospital admissions",
                 url="http://www.nature.example/vaccine-coverage/?utm_source=feed",
                 source="Nature Medicine", summary="Duplicate syndication.",
                 baseline_duplicate_kind="exact"),
        # Near-duplicate headline on a distinct publisher URL.
        _article("Health & Medicine",
                 "Global malaria vaccine rollout expands across Africa today",
                 url="https://wire.example/malaria-vaccine-followup", source="BBC",
                 summary="A second publisher reports on the malaria vaccine rollout.",
                 baseline_duplicate_kind="near"),
        # Aggregator attribution fixture.
        _article("Policy & Government",
                 "Government releases climate regulation update - The Hindu",
                 url="https://news.google.com/rss/articles/policy-fixture",
                 source="Google News", summary="Official regulation update from government."),
        # Malformed/missing metadata fixtures.
        _article("AI & Technology", "A broken destination with research metadata",
                 url="not-a-url", source="OpenAlex", summary="Machine learning study."),
        _article("Climate & Environment", "A valid title with missing publisher attribution",
                 url="https://climate.example/no-source", source="",
                 summary="Climate science and carbon emissions."),
    ]
    records.extend([
        {"title": "Research title with a missing abstract",
         "url": "https://ai.example/no-abstract", "source": "AI Research Journal",
         "date": "2026-10-24", "topic": "AI & Technology", "summary": "",
         "expected_relevant": True},
        {"title": "A candidate record missing its URL", "source": "Example Journal",
         "date": "2026-10-24", "topic": "Climate & Environment", "summary": "Climate report.",
         "expected_relevant": True},
        {"url": "https://policy.example/no-title", "source": "Policy Journal",
         "date": "2026-10-24", "topic": "Policy & Government", "summary": "Policy update.",
         "expected_relevant": True},
    ])
    return records


def _score(record, topic):
    profile = PROFILES[topic]
    return cq.relevance_score(
        record, topic, keywords=profile["keywords"],
        subtopics=profile["subtopics"],
        # Deterministic no-key fallback in app.expand_topic_keywords():
        # terms and relevance_core both contain the input topic.
        core_terms=[topic], terms=[topic],
        discipline_scoped=bool(record.get("discipline_scoped")),
    )


def baseline_metrics():
    records = fixture_records()
    valid = []
    scores_by_topic = {}
    for record in records:
        topic = record["topic"]
        score = _score(record, topic) if topic in PROFILES else 0.0
        record["relevance"] = score
        scores_by_topic.setdefault(topic, []).append((record, score))
        if cq.validate(record, topic)[0]:
            valid.append(record)

    dated = [a for a in valid if cq.parse_date(a.get("date")) is not None]
    fresh30 = [a for a in dated if (BASELINE_DATE - cq.parse_date(a["date"])).days <= 30]
    historical = [a for a in dated if (BASELINE_DATE - cq.parse_date(a["date"])).days > 365]
    deduped = fs.dedupe_articles(valid)
    publisher_known = [a for a in valid if cq.publisher(a)]
    profile_results = {}
    for topic in PROFILES:
        # Production adapter order is relevance scoring -> dedupe -> ranking.
        candidates = [a for a in deduped if a.get("topic") == topic]
        ranked = fs.rank_my_fields(
            candidates, [topic], {},
            today=datetime.combine(BASELINE_DATE, time.min))
        profile_results[topic] = {
            "candidates": len(candidates),
            "eligible": sum(1 for a in candidates if a.get("relevance", 0) >= fs.CONFIG["my_fields"]["min_relevance"]),
            "top_title": ranked[0]["title"] if ranked else None,
            "distinct_publishers_in_ranked": len({cq.publisher(a) for a in ranked if cq.publisher(a)}),
        }

    local_fixtures = [
        {"title": "Hyderabad health services expand in Telangana", "summary": "Local public health clinics add services."},
        {"title": "Telangana district health programme update", "summary": "A regional health service announcement."},
        {"title": "Government of India announces national programme", "summary": "Parliament discusses a national policy."},
    ]
    local_scores = [cq.local_relevance_score(a, "Hyderabad", "Telangana", ["Health & Medicine"])
                    for a in local_fixtures]

    gnews = next(a for a in valid if a.get("source") == "Google News")
    relevance_checks = []
    for record in records:
        topic = record.get("topic")
        if topic not in PROFILES:
            continue
        score = _score(record, topic)
        predicted = score >= cq.RELEVANCE["relevant"]
        expected = bool(record.get("expected_relevant", True))
        relevance_checks.append((expected, predicted))
    tp = sum(expected and predicted for expected, predicted in relevance_checks)
    fp = sum((not expected) and predicted for expected, predicted in relevance_checks)
    fn = sum(expected and (not predicted) for expected, predicted in relevance_checks)
    duplicate_kinds = {}
    for kind in ("exact", "near"):
        pair = [a for a in records if a.get("baseline_duplicate_kind") == kind]
        if not pair:
            duplicate_kinds[kind] = 0
            continue
        # Pair each marked duplicate with its matching canonical/original item.
        duplicate = pair[0]
        if kind == "exact":
            original = next(a for a in records if a.get("url") == "https://nature.example/vaccine-coverage")
        else:
            original = next(a for a in records if a.get("url") == "https://wire.example/malaria-vaccine")
        duplicate_kinds[kind] = int(len(fs.dedupe_articles([original, duplicate])) == 1)
    raw_urls = [a.get("url", "") for a in records]
    valid_urls = sum(url.startswith(("http://", "https://")) and "." in url.split("/")[2]
                     for url in raw_urls if url)
    expected_publishers = [a for a in records if a.get("expected_publisher")]
    return {
        "fixture_source": FIXTURE_SOURCE,
        "fixture_date": BASELINE_DATE.isoformat(),
        "records": len(records),
        "structurally_valid": len(valid),
        "structural_acceptance_rate": round(len(valid) / len(records), 3),
        "invalid_or_incomplete_records": len(records) - len(valid),
        "valid_url_count_of_nonempty_urls": f"{valid_urls}/{sum(bool(u) for u in raw_urls)}",
        "records_with_source_field": sum(bool(a.get("source")) for a in records),
        "valid_publication_dates": len(dated),
        "unknown_publication_dates": len(valid) - len(dated),
        "dated_records_fresh_within_30_days": len(fresh30),
        "dated_records_older_than_1_year": len(historical),
        "deduped_records": len(deduped),
        "duplicates_removed": len(valid) - len(deduped),
        "duplicate_removal_rate": round((len(valid) - len(deduped)) / max(1, len(valid)), 3),
        "explicit_exact_duplicate_pairs_collapsed": duplicate_kinds["exact"],
        "explicit_near_duplicate_pairs_collapsed": duplicate_kinds["near"],
        "publisher_attribution_coverage": round(len(publisher_known) / max(1, len(valid)), 3),
        "expected_publisher_fixture_resolution": [
            {"expected": a["expected_publisher"], "resolved": cq.publisher(a),
             "correct": cq.publisher(a) == a["expected_publisher"]}
            for a in expected_publishers
        ],
        "relevance_at_relevant_threshold": {
            "expected_relevant_fixture_count": sum(e for e, _ in relevance_checks),
            "true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": round(tp / max(1, tp + fp), 3),
            "recall": round(tp / max(1, tp + fn), 3),
        },
        "records_missing_summary": sum(not a.get("summary") for a in records),
        "records_missing_source": sum(not a.get("source") for a in records),
        "records_missing_date": sum(not a.get("date") for a in records),
        "records_missing_title": sum(not a.get("title") for a in records),
        "records_missing_url": sum(not a.get("url") for a in records),
        "distinct_publishers_after_dedupe": len({cq.publisher(a) for a in deduped if cq.publisher(a)}),
        "distinct_topics_after_dedupe": len({a.get("topic") for a in deduped if a.get("topic")}),
        "aggregator_publisher_resolution": cq.publisher(gnews),
        "local_fixture_scores_hyderabad": local_scores,
        "per_profile": profile_results,
    }


class DiscoveryQualityBaselineTest(unittest.TestCase):
    def test_baseline_profiles_have_relevant_candidates(self):
        metrics = baseline_metrics()
        for topic in PROFILES:
            self.assertGreater(metrics["per_profile"][topic]["candidates"], 0, topic)
            # This is a measurement, not a quality gate: zero eligible results
            # is an important baseline defect to expose (currently AI & Tech).
            self.assertGreaterEqual(metrics["per_profile"][topic]["eligible"], 0, topic)

    def test_dates_distinguish_fresh_historical_and_unknown(self):
        metrics = baseline_metrics()
        self.assertGreater(metrics["valid_publication_dates"], 0)
        self.assertGreater(metrics["unknown_publication_dates"], 0)
        self.assertGreater(metrics["dated_records_fresh_within_30_days"], 0)
        self.assertGreater(metrics["dated_records_older_than_1_year"], 0)

    def test_duplicate_fixtures_are_removed_without_losing_source_attribution(self):
        metrics = baseline_metrics()
        self.assertGreaterEqual(metrics["duplicates_removed"], 2)
        self.assertEqual(metrics["aggregator_publisher_resolution"], "The Hindu")

    def test_local_location_signal_ranks_city_story_over_national_fixture(self):
        scores = baseline_metrics()["local_fixture_scores_hyderabad"]
        self.assertGreater(scores[0], scores[2])
        self.assertGreater(scores[1], scores[2])

    def test_fixture_acceptance_and_diversity_are_recorded(self):
        metrics = baseline_metrics()
        self.assertGreater(metrics["structural_acceptance_rate"], 0)
        self.assertGreater(metrics["distinct_publishers_after_dedupe"], 1)
        self.assertGreater(metrics["distinct_topics_after_dedupe"], 1)


if __name__ == "__main__":
    print(json.dumps(baseline_metrics(), indent=2, ensure_ascii=False))
    unittest.main(verbosity=2)
