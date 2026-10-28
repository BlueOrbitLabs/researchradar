"""Owlume feed strategies — pure, deterministic ranking logic.

This module contains no Streamlit imports and performs no network I/O, so the
four feed strategies can be tested with controlled article fixtures.

Article record schema (produced by the existing adapters in ``app.py``)::

    {
        "title": str,
        "url": str,
        "summary": str,
        "date": str,            # e.g. "2026-10-01" or "01 Oct 2026" (may be "")
        "source": str,          # adapter / publisher label
        "topic": str,           # interest this candidate was retrieved for
        "relevance": float,     # 0..1 from app.score_relevance()
        # optional, only when a provider genuinely supplies it:
        "doi": str, "content_type": str,
    }

Not every adapter supplies a DOI, a content type or an open-access flag. Where a
signal is missing the ranking code omits it rather than inventing a value.
``content_type`` is *inferred* from source/title/summary text when absent and is
treated as a weak signal only.

All tunable weights live in ``CONFIG`` below.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import content_quality as cq

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — every weight used by the rankers lives here.
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = {
    # For You: balanced relevance + preference match, with light discovery.
    "for_you": {
        "relevance": 0.35,
        "subtopic": 0.15,
        "preference": 0.15,
        "freshness": 0.20,
        "quality": 0.10,
        "profile": 0.05,
        "discovery_penalty": 0.72,   # outside-interest items rank slightly lower
        "max_per_source": 3,
        "max_per_topic": 6,
        "limit": 25,
        # Discovery is deliberately a minority of the feed (about 4 items) and
        # must be current: old papers are not useful discovery.
        "discovery_slots": 4,
        "discovery_max_per_topic": 2,
        "discovery_max_age_days": 180,
        "min_relevance": 0.30,
    },
    # My Fields: strongest interest signal, subtopics matter most.
    "my_fields": {
        "relevance": 0.45,
        "subtopic": 0.15,
        "preference": 0.15,
        "freshness": 0.12,
        "quality": 0.08,
        "profile": 0.05,
        "max_per_source": 3,
        "max_per_topic": 8,           # a 2-topic feed should not stop at 8 items
        "max_per_topic_filtered": 8,  # single-interest view may be more focused
        "limit": 25,
        "min_relevance": 0.30,
    },
    # Emerging: recency + cross-source corroboration + source quality.
    "emerging": {
        "freshness": 0.35,
        "corroboration": 0.25,
        "quality": 0.20,
        "relevance": 0.15,
        "preference": 0.05,
        "interest_bonus": 0.08,  # small nudge toward the user's own fields
        "max_per_source": 3,
        "max_per_topic": 6,
        "limit": 25,
        "min_relevance": 0.25,
        # A "recent development" must actually be recent and dated. Undated
        # records are excluded rather than presented as new.
        "max_age_days": 45,
    },
    # Broaden: quality + accessibility of material outside the user's interests.
    "broaden": {
        "freshness": 0.40,
        "quality": 0.25,
        "preference": 0.20,
        "relevance": 0.15,
        "max_per_source": 2,
        "max_per_topic": 6,
        "limit": 25,
        "min_outside_before_fallback": 8,
        "fallback_limit": 6,
        "min_relevance": 0.20,
    },
}

# Freshness buckets: (max age in days, score). Unknown/invalid publication date
# is omitted from the weighted score rather than represented as invented recency.
FRESHNESS_BUCKETS = [(7, 1.0), (30, 0.9), (90, 0.75), (180, 0.6),
                     (365, 0.45), (730, 0.3)]
KNOWN_FRESHNESS_FLOOR = 0.2
UNKNOWN_FRESHNESS = None

# Source-quality tiers (heuristic, documented rather than claimed as fact).
QUALITY_TIERS = {
    0.85: (
        # Named publishers / institutions only. Index/adapter names are not
        # credibility evidence; unknown publishers remain at UNKNOWN_QUALITY.
        "who", "nih", "nature", "science", ".gov", ".edu",
        "lancet", "jstor", "ssrn",
    ),
    0.65: (
        "the hindu", "bbc", "reuters", "guardian", "economist", "new york times",
        "indian express", "hindustan times", "mint", "business standard",
        "deccan herald", "times of india", "the wire", "scroll", "frontline",
        "pib", "associated press", "financial times", "washington post",
    ),
}
UNKNOWN_QUALITY = None
MISSING_QUALITY = None

# Onboarding preference labels -> content types they reward.
PREFERENCE_TYPES = {
    "New research & journal publications": {"research"},
    "Emerging trends & breakthroughs": {"research", "industry"},
    "Current affairs & world events": {"news", "policy"},
    "Government policies & official reports": {"policy"},
    "Industry & professional developments": {"industry"},
    "Grants, fellowships & opportunities": {"grants"},
    "Exam-relevant current affairs": {"news", "policy"},
    "Practical explainers & background knowledge": {"explainer"},
    "Organisations & institutions": {"research", "policy", "industry"},
    "General knowledge beyond my usual interests": {"explainer", "research", "news"},
    # Local news is intentionally excluded from the general feed strategies.
    "Local news & community updates": set(),
}

# Critical words that make a content type unambiguous.
TYPE_PATTERNS = {
    "grants": re.compile(
        r"\b(grant|grants|fellowship|scholarship|funding call|call for proposals?|"
        r"award|bursary|studentship|apply now|applications? (open|invited))\b",
        re.I),
    "policy": re.compile(
        r"\b(policy|policies|government|ministry|regulat\w*|legislation|bill|"
        r"parliament|congress|white paper|official report|framework|"
        r"directive|scheme|budget)\b", re.I),
    "research": re.compile(
        r"\b(study|studies|trial|randomi[sz]ed|cohort|meta-analysis|systematic review|"
        r"journal|preprint|dataset|hypothesis|empirical|peer-reviewed|et al\.?)\b",
        re.I),
    "explainer": re.compile(
        r"\b(explain(er|ed|s)?|what is|what are|how to|how does|primer|"
        r"beginner'?s guide|introduction to|overview|background(er)?)\b", re.I),
    "industry": re.compile(
        r"\b(industry|market|company|companies|startup|earnings|revenue|"
        r"merger|acquisition|product launch|sector|manufactur\w*)\b", re.I),
    "organisation": re.compile(
        r"\b(organization|organisation|institution|agency|foundation|ngo|"
        r"university|institute|council|committee|who|unicef|united nations|"
        r"world health|red cross|oxfam)\b", re.I),
}

RESEARCH_SOURCES = ("openalex", "pubmed", "europe pmc", "arxiv", "doaj",
                    "crossref", "nber", "doi.org")


# ─────────────────────────────────────────────────────────────────────────────
# Discovery Baskets — central taxonomy for the 11 discovery preferences.
# Each basket defines subtypes, source types, query terms, classification
# signals and ranking hints. Baskets are adapted to user interests at
# retrieval time via adapt_basket() — never hardcoded per field.
# ─────────────────────────────────────────────────────────────────────────────
DISCOVERY_BASKETS = {
    "new_research": {
        "id": "new_research",
        "display_name": "New research & journal publications",
        "preference": "New research & journal publications",
        "subtypes": ["original_research", "systematic_review", "meta_analysis",
                     "working_paper", "preprint", "clinical_study", "journal_issue"],
        "source_types": ["journal", "repository", "institution"],
        "content_types": {"research"},
        "query_terms": ["study", "trial", "research", "journal", "paper",
                        "publication", "preprint", "review"],
        "classification_signals": ["study", "trial", "cohort", "meta-analysis",
                                  "systematic review", "journal", "preprint",
                                  "peer-reviewed", "et al"],
        "ranking": {"relevance": 0.40, "freshness": 0.20, "quality": 0.25,
                    "preference": 0.15},
    },
    "emerging_trends": {
        "id": "emerging_trends",
        "display_name": "Emerging trends & breakthroughs",
        "preference": "Emerging trends & breakthroughs",
        "subtypes": ["breakthrough", "novel_method", "emerging_area",
                     "innovation", "new_application", "practice_change"],
        "source_types": ["journal", "repository", "news", "industry"],
        "content_types": {"research", "industry"},
        "query_terms": ["breakthrough", "novel", "emerging", "innovation",
                        "new method", "discovery", "advance"],
        "classification_signals": ["breakthrough", "novel", "emerging",
                                  "innovation", "discovery", "first"],
        "ranking": {"freshness": 0.40, "relevance": 0.25, "quality": 0.20,
                    "preference": 0.15},
    },
    "current_affairs": {
        "id": "current_affairs",
        "display_name": "Current affairs & world events",
        "preference": "Current affairs & world events",
        "subtypes": ["major_development", "sector_news", "significant_event",
                     "economic", "political", "social", "scientific"],
        "source_types": ["news", "government", "institution"],
        "content_types": {"news", "policy"},
        "query_terms": ["news", "development", "event", "update", "latest"],
        "classification_signals": ["announced", "reported", "developments",
                                  "events", "latest"],
        "ranking": {"freshness": 0.45, "relevance": 0.25, "quality": 0.15,
                    "preference": 0.15},
    },
    "government_policy": {
        "id": "government_policy",
        "display_name": "Government policies & official reports",
        "preference": "Government policies & official reports",
        "subtypes": ["law", "regulation", "policy_change", "announcement",
                     "official_report", "guideline", "strategy", "consultation",
                     "programme"],
        "source_types": ["government", "institution", "news"],
        "content_types": {"policy"},
        "query_terms": ["policy", "regulation", "law", "government", "official",
                        "report", "guideline", "strategy", "directive"],
        "classification_signals": ["policy", "regulation", "law", "government",
                                  "ministry", "official", "directive", "bill"],
        "ranking": {"relevance": 0.35, "freshness": 0.25, "quality": 0.25,
                    "preference": 0.15},
    },
    "industry": {
        "id": "industry",
        "display_name": "Industry & professional developments",
        "preference": "Industry & professional developments",
        "subtypes": ["sector_development", "market_change", "professional_standard",
                     "new_tool", "industry_report", "workforce", "conference"],
        "source_types": ["news", "industry", "institution"],
        "content_types": {"industry"},
        "query_terms": ["industry", "market", "sector", "professional", "tool",
                        "service", "conference", "standard"],
        "classification_signals": ["industry", "market", "company", "startup",
                                  "sector", "professional", "tool", "service"],
        "ranking": {"freshness": 0.35, "relevance": 0.30, "quality": 0.20,
                    "preference": 0.15},
    },
    "grants": {
        "id": "grants",
        "display_name": "Grants, fellowships & opportunities",
        "preference": "Grants, fellowships & opportunities",
        "subtypes": ["research_grant", "funding_call", "fellowship",
                     "scholarship", "studentship", "postdoc", "award",
                     "competition", "application_deadline"],
        "source_types": ["government", "institution", "repository"],
        "content_types": {"grants"},
        "query_terms": ["grant", "fellowship", "scholarship", "funding",
                        "studentship", "postdoc", "award", "call for proposals",
                        "application"],
        "classification_signals": ["grant", "fellowship", "scholarship",
                                  "funding call", "call for proposals",
                                  "studentship", "postdoc", "award", "bursary",
                                  "apply now", "applications open"],
        "ranking": {"freshness": 0.30, "relevance": 0.30, "quality": 0.20,
                    "preference": 0.20},
    },
    "organisations": {
        "id": "organisations",
        "display_name": "Organisations & institutions",
        "preference": "Organisations & institutions",
        "subtypes": ["agency", "international_org", "university", "research_institute",
                     "ngo", "foundation", "think_tank", "professional_body",
                     "regulatory_body", "institutional_report"],
        "source_types": ["institution", "government", "organisation"],
        "content_types": {"organisation", "policy", "research"},
        "query_terms": ["organization", "institution", "agency", "university",
                        "institute", "foundation", "ngo", "think tank"],
        "classification_signals": ["organization", "organisation", "institution",
                                  "agency", "university", "institute",
                                  "foundation", "ngo", "who", "unicef"],
        "ranking": {"relevance": 0.35, "quality": 0.30, "freshness": 0.20,
                    "preference": 0.15},
    },
    "exam_relevant": {
        "id": "exam_relevant",
        "display_name": "Exam-relevant current affairs",
        "preference": "Exam-relevant current affairs",
        "subtypes": ["exam_news", "government_programme", "report", "index",
                     "statistic", "appointment", "science_development",
                     "economics_development"],
        "source_types": ["news", "government", "institution"],
        "content_types": {"news", "policy"},
        "query_terms": ["current affairs", "exam", "upsc", "report", "index",
                        "statistics", "appointment", "programme"],
        "classification_signals": ["current affairs", "report", "index",
                                  "statistics", "appointment", "programme",
                                  "scheme"],
        "ranking": {"relevance": 0.40, "freshness": 0.30, "quality": 0.15,
                    "preference": 0.15},
    },
    "explainers": {
        "id": "explainers",
        "display_name": "Practical explainers",
        "preference": "Practical explainers & background knowledge",
        "subtypes": ["concept_explainer", "how_to", "tutorial", "method",
                     "framework", "tool_guide", "evidence_answer"],
        "source_types": ["news", "institution", "repository"],
        "content_types": {"explainer"},
        "query_terms": ["explain", "what is", "how to", "guide", "primer",
                        "introduction", "overview", "tutorial"],
        "classification_signals": ["explain", "what is", "how to", "guide",
                                  "primer", "introduction", "overview",
                                  "tutorial", "background"],
        "ranking": {"relevance": 0.35, "quality": 0.30, "freshness": 0.15,
                    "preference": 0.20},
    },
    "general_knowledge": {
        "id": "general_knowledge",
        "display_name": "General knowledge beyond usual interests",
        "preference": "General knowledge beyond my usual interests",
        "subtypes": ["cross_topic_discovery", "major_development",
                     "broadly_significant", "cross_disciplinary"],
        "source_types": ["news", "institution", "journal"],
        "content_types": {"explainer", "research", "news"},
        "query_terms": ["discovery", "breakthrough", "major", "significant",
                        "world", "science", "history", "economics"],
        "classification_signals": [],  # matches by cross-topic, not keywords
        "ranking": {"relevance": 0.20, "freshness": 0.30, "quality": 0.30,
                    "preference": 0.20},
        "cross_topic": True,
    },
    "local_news": {
        "id": "local_news",
        "display_name": "Local news & community updates",
        "preference": "Local news & community updates",
        "subtypes": ["local_government", "community_event", "regional_service",
                     "local_initiative", "local_development"],
        "source_types": ["news", "government", "community"],
        "content_types": set(),  # handled by local news tab, not general feeds
        "query_terms": [],
        "classification_signals": [],
        "ranking": {},
        "local_only": True,
    },
}

# Map preference display name -> basket id
PREFERENCE_TO_BASKET = {b["preference"]: bid for bid, b in DISCOVERY_BASKETS.items()}


def get_basket(preference):
    """Return the basket config for a preference display name, or None."""
    bid = PREFERENCE_TO_BASKET.get(preference)
    return DISCOVERY_BASKETS.get(bid) if bid else None


def adapt_basket(basket, interest, subtopics=None, role=None):
    """Adapt a basket to a specific interest, producing query terms and hints.

    Returns a dict with:
      - query_terms: list of search terms (interest + subtype terms)
      - content_types: set of relevant content types
      - source_types: list of relevant source types
      - cross_topic: bool
    """
    if not basket:
        return {"query_terms": [interest], "content_types": set(),
                "source_types": [], "cross_topic": False}
    terms = [interest]
    for sub in (subtopics or [])[:3]:
        terms.append(f"{interest} {sub}")
    for qt in (basket.get("query_terms") or [])[:4]:
        terms.append(f"{interest} {qt}")
    return {
        "query_terms": terms,
        "content_types": set(basket.get("content_types") or set()),
        "source_types": list(basket.get("source_types") or []),
        "cross_topic": bool(basket.get("cross_topic")),
        "subtypes": list(basket.get("subtypes") or []),
    }


def all_baskets():
    """Return all basket configs as a list."""
    return list(DISCOVERY_BASKETS.values())


# Role -> affinity per content type. Soft signals, never restrictions.
ROLE_AFFINITY = {
    "phd": {"research": 1.0, "policy": 0.4, "explainer": 0.2, "organisation": 0.5},
    "researcher": {"research": 1.0, "policy": 0.4, "explainer": 0.2},
    "faculty": {"research": 0.8, "explainer": 0.6, "policy": 0.3},
    "educator": {"research": 0.8, "explainer": 0.6, "policy": 0.3},
    "student": {"research": 0.6, "explainer": 0.8, "news": 0.3},
    "exam": {"news": 0.9, "policy": 0.8, "research": 0.2},
    "professional": {"industry": 0.9, "research": 0.5, "news": 0.3, "organisation": 0.4},
    "curious": {"explainer": 0.9, "research": 0.4, "news": 0.2},
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "their", "have", "will", "about", "after", "before", "than", "they",
    "what", "when", "where", "which", "while", "your", "more", "most",
}



# ─────────────────────────────────────────────────────────────────────────────
# Basket adaptation helpers
# ─────────────────────────────────────────────────────────────────────────────
def classify_subtype(article, basket):
    """Classify an article into the best-matching subtype of a basket.

    Returns the subtype string or None if no signal matches. Uses the
    basket's classification_signals (regex word matching) against title +
    summary + source. Returns None for uncertain classifications.
    """
    if not basket:
        return None
    signals = basket.get("classification_signals") or []
    if not signals:
        return None
    haystack = " ".join(filter(None, [
        article.get("title"), article.get("summary"),
        article.get("source"), article.get("retrieved_via"),
    ])).lower()
    if not haystack:
        return None
    matches = [sig for sig in signals if sig.lower() in haystack]
    if not matches:
        return None
    # Return the first matching signal as the subtype proxy.
    return matches[0]


def basket_for_preference(preference):
    """Return the basket config for a preference display name."""
    return get_basket(preference)


def adapt_all_baskets(interests, preferences, subtopics=None, role=None):
    """Adapt all selected preference baskets to the user's interests.

    Returns a list of adapted basket dicts, each with query_terms,
    content_types, source_types, cross_topic, and the original basket.
    """
    result = []
    for pref in (preferences or []):
        basket = get_basket(pref)
        if not basket:
            continue
        for interest in (interests or []):
            adapted = adapt_basket(basket, interest,
                                   (subtopics or {}).get(interest, []),
                                   role)
            adapted["basket"] = basket
            adapted["interest"] = interest
            adapted["preference"] = pref
            result.append(adapted)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Metadata helpers
# ─────────────────────────────────────────────────────────────────────────────
def parse_date(value):
    """Best-effort date parsing. Returns a naive ``datetime`` or ``None``."""
    if isinstance(value, dict):
        value = cq.publication_date_value(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        try:
            return datetime(value.year, value.month, value.day)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidates = [text, text[:19], text[:10]]
    formats = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m", "%d %b %Y", "%d %B %Y",
               "%b %d, %Y", "%B %d, %Y", "%Y-%m", "%B %Y", "%b %Y", "%Y")
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        try:
            return datetime(int(match.group(0)), 1, 1)
        except ValueError:
            return None
    return None


def freshness(date_value, today=None):
    """Recency in [0.2, 1.0], or ``None`` when publication date is unknown."""
    parsed = parse_date(date_value)
    if parsed is None:
        return UNKNOWN_FRESHNESS
    today = today or datetime.now()
    if not isinstance(today, datetime):
        today = datetime(today.year, today.month, today.day)
    age_days = (today - parsed).total_seconds() / 86400.0
    if age_days < 0:
        return UNKNOWN_FRESHNESS
    for max_days, score in FRESHNESS_BUCKETS:
        if age_days <= max_days:
            return score
    return KNOWN_FRESHNESS_FLOOR


def source_quality(article):
    """Conservative publisher-name heuristic; an index is not publisher proof.

    ``retrieved_via`` is intentionally ignored. When publisher attribution is
    missing or unresolved, return UNKNOWN_QUALITY rather than trusting an
    aggregator/index label. This remains a weak ranking prior, not a factual
    source-quality verdict.
    """
    source = (cq.publisher(article) or "").strip().lower()
    if not source:
        return MISSING_QUALITY
    source_tokens = re.findall(r"[a-z0-9]+", source)
    source_domain = str(article.get("publisher_domain") or article.get("source_domain") or "").lower().strip()
    for score, needles in QUALITY_TIERS.items():
        for needle in needles:
            if needle.startswith("."):
                # A domain suffix is evidence only when supplied as a domain,
                # not merely as a substring of a publisher display name.
                if source_domain.endswith(needle):
                    return score
                continue
            needle_tokens = re.findall(r"[a-z0-9]+", needle.lower())
            if not needle_tokens:
                continue
            width = len(needle_tokens)
            if any(source_tokens[i:i + width] == needle_tokens
                   for i in range(len(source_tokens) - width + 1)):
                return score
    return UNKNOWN_QUALITY


def infer_content_type(article):
    """Infer a coarse content type from metadata text (weak signal)."""
    declared = (article.get("content_type") or "").strip().lower()
    if declared in {"research", "policy", "industry", "grants", "explainer", "news", "organisation"}:
        return declared

    haystack = " ".join(filter(None, [
        article.get("title"), article.get("summary"),
        article.get("source"), article.get("retrieved_via"),
    ])).lower()
    if not haystack:
        return "news"

    # Ordered: the most specific signals win over generic words.
    for kind in ("grants", "organisation", "policy", "research", "explainer", "industry"):
        if TYPE_PATTERNS[kind].search(haystack):
            return kind
    if any(research_source in haystack for research_source in RESEARCH_SOURCES):
        return "research"
    return "news"


def preference_match(article, preferences, user_topics=None):
    """Fraction of the user's selected information preferences this item fits.

    When "General knowledge beyond my usual interests" is selected, items
    whose topic is outside the user's interests get an additional boost so
    the preference genuinely introduces cross-topic discoveries rather than
    just matching content types.
    """
    prefs = [p for p in (preferences or []) if p]
    relevant = [p for p in prefs if PREFERENCE_TYPES.get(p)]
    if not relevant:
        return 0.0
    kind = infer_content_type(article)
    hits = sum(1 for p in relevant if kind in PREFERENCE_TYPES[p])
    base = hits / len(relevant)

    # Cross-topic boost for "General knowledge beyond my usual interests".
    if "General knowledge beyond my usual interests" in relevant:
        ut = set(user_topics or [])
        art_topic = (article.get("topic") or "").strip()
        if ut and art_topic and art_topic not in ut:
            # Cross-topic: quality can strengthen discovery only when there is
            # actual publisher evidence. Unknown source quality adds no bonus.
            quality = source_quality(article)
            if quality is not None:
                base = min(1.0, base + 0.3 * quality)
    return base


def profile_affinity(article, role):
    """Soft role/content-type affinity in [0, 1]."""
    role_key = (role or "").strip().lower()
    if not role_key:
        return 0.0
    for key, mapping in ROLE_AFFINITY.items():
        if key in role_key:
            return mapping.get(infer_content_type(article), 0.0)
    return 0.0


def subtopic_match(article, subtopics):
    """Share of selected subtopics reflected in the article text (0..1).

    Matching is word-based (not exact-phrase) so "Health financing" still
    matches "health system financing". All significant words must appear; a
    near miss on a multi-word subtopic counts half.
    """
    subs = [s for s in (subtopics or []) if s]
    if not subs:
        return 0.0
    text = ((article.get("title") or "") + " " + (article.get("summary") or "")).lower()
    if not text.strip():
        return 0.0
    hits = 0.0
    for sub in subs:
        words = title_key(sub)
        if not words:
            continue
        present = sum(1 for word in words if word in text)
        if present == len(words):
            hits += 1.0
        elif len(words) > 1 and present >= len(words) - 1:
            hits += 0.5
    return min(1.0, hits / len(subs) * 2)  # one strong hit already counts 2/len


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication (DOI -> canonical URL -> title similarity)
# ─────────────────────────────────────────────────────────────────────────────
TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref",
                   "source", "cmpid", "ocid", "at_medium", "at_campaign")


def extract_doi(article):
    """Return a normalised DOI if the record or its URL exposes one."""
    declared = (article.get("doi") or "").strip()
    if declared:
        return declared.lower().replace("https://doi.org/", "").replace("doi:", "").strip()
    url = (article.get("url") or "").lower()
    match = re.search(r"(10\.\d{4,9}/[^\s?#]+)", url)
    if match:
        return match.group(1).rstrip("/.")
    return ""


def canonical_url(url):
    """Strip scheme, 'www.', tracking params, fragments and trailing slashes."""
    if not url:
        return ""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not any(k.lower().startswith(p) for p in TRACKING_PARAMS)]
    path = parts.path.rstrip("/")
    return urlunsplit(("", host, path, urlencode(sorted(query)), "")).lstrip("/")


def _canonical_url_value(url):
    """Full URL form of the canonical identity key, for display/storage."""
    key = canonical_url(url)
    return f"https://{key}" if key else ""


def _stable_article_id(doi, canonical, title, source):
    """Stable id from DOI/URL identity, with title+publisher as last fallback."""
    if doi:
        identity = "doi:" + doi
    elif canonical:
        identity = "url:" + canonical
    else:
        identity = "title:" + " ".join(title_key(title)) + "|" + (source or "").lower().strip()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _retrieved_at_iso(value=None):
    """Normalize an existing retrieval timestamp or make a UTC retrieval time.

    This timestamp is deliberately separate from publication_date/date.
    """
    if value is None or value == "":
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value).strip()


def normalize_article(article, *, retrieved_at=None):
    """Return a copy using Owlume's canonical article record contract.

    Compatibility fields (`url` and `date`) remain intact for current UI and
    rankers. Original/canonical URLs, publication and retrieval timestamps,
    adapter provenance, classification provenance, matched-profile lists, and
    metadata/extraction status are added without fabricating article content.
    """
    if not isinstance(article, dict):
        return {}
    result = dict(article)
    result["title"] = str(result.get("title") or "").strip()
    result["summary"] = str(result.get("summary") or "").strip()
    result["source"] = str(result.get("source") or "").strip()
    result["topic"] = str(result.get("topic") or "").strip()
    result["date"] = str(result.get("date") or "").strip()
    raw_url = str(result.get("original_url") or result.get("url") or "").strip()
    if not result.get("url") and raw_url:
        result["url"] = raw_url
    result["original_url"] = raw_url

    canonical = str(result.get("canonical_url") or _canonical_url_value(raw_url)).strip()
    result["canonical_url"] = canonical

    doi = extract_doi(result)
    result["doi"] = doi

    # `date` is retained as the historical UI/ranker alias. An RSS updated
    # timestamp is explicitly not promoted to publication_date.
    date_source = (result.get("date_source") or "").strip().lower()
    pub_date = (result.get("publication_date") or "").strip()
    if not pub_date and date_source != "updated":
        pub_date = str(result.get("date") or "").strip()
    result["publication_date"] = pub_date
    if not result.get("date") and pub_date:
        result["date"] = pub_date
    result.setdefault("date_source", "published" if pub_date else (date_source or "unknown"))
    result["updated_at"] = str(result.get("updated_at") or "").strip()
    result["retrieval_topic"] = str(result.get("retrieval_topic") or result.get("topic") or "").strip()
    result["retrieved_at"] = _retrieved_at_iso(
        retrieved_at if retrieved_at is not None else result.get("retrieved_at"))

    source_adapter = (result.get("source_adapter") or result.get("adapter")
                      or result.get("retrieved_via") or "unknown")
    result["source_adapter"] = str(source_adapter).strip().lower().replace(" ", "_")
    adapters = list(result.get("source_adapters") or [])
    if result["source_adapter"] != "unknown" and result["source_adapter"] not in adapters:
        adapters.append(result["source_adapter"])
    result["source_adapters"] = adapters

    declared_type = str(result.get("content_type") or "").strip().lower()
    if declared_type in {"research", "policy", "industry", "grants", "explainer", "news", "organisation"}:
        result["content_type"] = declared_type
        result.setdefault("content_type_source", "provider")
    else:
        result["content_type"] = infer_content_type(result)
        result["content_type_source"] = "heuristic"

    image = (result.get("image") or result.get("image_url")
             or result.get("thumbnail_url") or result.get("top_image") or "")
    result["image"] = str(image).strip() if image else ""
    result["matched_interests"] = list(result.get("matched_interests") or [])
    result["matched_subtopics"] = list(result.get("matched_subtopics") or [])
    result["_subtypes"] = list(result.get("_subtypes") or [])
    result["source_links"] = list(result.get("source_links") or [])
    result["date_conflicts"] = list(result.get("date_conflicts") or [])
    if raw_url and not result["source_links"]:
        result["source_links"] = [{"source": result.get("source", ""), "url": raw_url}]

    if not result.get("extraction_status"):
        result["extraction_status"] = (
            "provider_excerpt" if result.get("summary") else "metadata_only")
    result["metadata_status"] = {
        "title": bool(result.get("title")),
        "url": bool(raw_url),
        "publisher": bool(result.get("source")),
        "publication_date": bool(pub_date),
        "updated_at": bool(result["updated_at"]),
        "summary": bool(result.get("summary")),
        "doi": bool(doi),
        "image": bool(result["image"]),
        "content_type": bool(result.get("content_type")),
        "source_adapter": result["source_adapter"] != "unknown",
    }
    result["id"] = str(result.get("id") or _stable_article_id(
        doi, canonical, result.get("title", ""), result.get("source", "")))
    return result


def title_key(title):
    """Normalised token set used for the title-similarity fallback."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


# Google News labels every item with the aggregator, not the publisher. The
# publisher is appended to the headline ("… - The Hindu"), so use that for
# corroboration counting — otherwise two locale variants of the same feed look
# like two independent sources. The single implementation lives in
# content_quality so the UI, briefing counts and ranking cannot disagree.
AGGREGATOR_SOURCES = cq.AGGREGATOR_SOURCES


def effective_source(article):
    """Publisher name usable for corroboration (unwraps Google News labels)."""
    return cq.publisher(article)


def story_title(article):
    """Headline without the publisher suffix added by news aggregators."""
    title = (article.get("title") or "").strip()
    if (article.get("source") or "").strip().lower() in AGGREGATOR_SOURCES and " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _titles_match(tokens_a, tokens_b, threshold=0.8):
    if len(tokens_a) < 4 or len(tokens_b) < 4:
        return False
    set_a, set_b = set(tokens_a), set(tokens_b)
    overlap = len(set_a & set_b) / len(set_a | set_b)
    return overlap >= threshold


def _merge(into, other):
    """Keep the richer record, preserving the strongest relevance score.

    Distinct publishers that carried the same story are remembered in a
    ``sources`` list. That is the evidence Emerging uses for corroboration;
    it is metadata only and never rendered as a claim of a confirmed trend.
    """
    # Normalize both sides first so aliases, URL identity, and metadata flags
    # are preserved consistently when adapters collide.
    into.update(normalize_article(into))
    other = normalize_article(other)
    into_date_record = {
        "publication_date": into.get("publication_date") or "",
        "source": into.get("source") or "",
        "source_adapter": into.get("source_adapter") or "unknown",
    }
    other_date_record = {
        "publication_date": other.get("publication_date") or "",
        "source": other.get("source") or "",
        "source_adapter": other.get("source_adapter") or "unknown",
    }
    provider_labels = {"openalex", "pubmed", "doaj", "crossref",
                       "europe pmc", "google news", "google news india"}
    into_source_is_index = (into.get("source") or "").strip().lower() in provider_labels
    other_source_is_index = (other.get("source") or "").strip().lower() in provider_labels
    if into_source_is_index and not other_source_is_index and other.get("source"):
        # Prefer a publisher identity over an index/aggregator label. This is
        # attribution cleanup, not a claim about the publisher's credibility.
        into["source"] = other["source"]
        into["source_adapter"] = other.get("source_adapter") or into.get("source_adapter")
    seen_sources = set(into.get("sources") or [])
    for article in (into, other):
        for name in (article.get("sources") or []) + [effective_source(article)]:
            if name:
                seen_sources.add(name)
    if len(seen_sources) > 1:
        into["sources"] = sorted(seen_sources)
    for field in ("date", "source", "doi", "content_type", "image", "retrieved_via",
                  "source_adapter", "canonical_url", "publication_date", "updated_at",
                  "date_source", "extraction_status", "content_type_source"):
        if not into.get(field) and other.get(field):
            into[field] = other[field]
    for field in ("matched_interests", "matched_subtopics", "_subtypes"):
        merged = list(into.get(field) or [])
        for value in other.get(field) or []:
            if value not in merged:
                merged.append(value)
        into[field] = merged
    adapters = list(into.get("source_adapters") or [])
    for adapter in other.get("source_adapters") or []:
        if adapter not in adapters:
            adapters.append(adapter)
    into["source_adapters"] = adapters
    # Keep the richest available abstract/snippet instead of permanently
    # retaining an empty or shorter first-seen record.
    if len(other.get("summary") or "") > len(into.get("summary") or ""):
        into["summary"] = other["summary"]
    if (other.get("content_type_source") == "provider"
            and into.get("content_type_source") != "provider"):
        into["content_type"] = other.get("content_type")
        into["content_type_source"] = "provider"
    current_pub = into.get("publication_date") or ""
    other_pub = other.get("publication_date") or ""
    if other_pub and current_pub and other_pub != current_pub:
        conflicts = list(into.get("date_conflicts") or [])
        for candidate in (into_date_record, other_date_record):
            if candidate["publication_date"] and candidate not in conflicts:
                conflicts.append(candidate)
        into["date_conflicts"] = conflicts
    if other_pub and (not current_pub or into.get("date_source") in {"updated", "unknown"}
                      or (into_source_is_index and not other_source_is_index)):
        into["publication_date"] = other_pub
        into["date"] = other_pub
        into["date_source"] = other.get("date_source", "published")
    statuses = {"metadata_only": 0, "feed_excerpt": 1, "provider_excerpt": 1,
                "abstract": 2, "full_text": 3}
    if statuses.get(other.get("extraction_status"), 0) > statuses.get(into.get("extraction_status"), 0):
        into["extraction_status"] = other["extraction_status"]
    links = list(into.get("source_links") or [])
    known_links = {entry.get("url") for entry in links if isinstance(entry, dict)}
    for entry in other.get("source_links") or []:
        if isinstance(entry, dict) and entry.get("url") and entry["url"] not in known_links:
            links.append(entry)
            known_links.add(entry["url"])
    into["source_links"] = links
    into["relevance"] = max(into.get("relevance", 0.0) or 0.0,
                            other.get("relevance", 0.0) or 0.0)
    into.update(normalize_article(into))
    return into


def dedupe_articles(articles):
    """Collapse duplicates by DOI, then canonical URL, then title similarity."""
    by_doi, by_url, seen_titles, out = {}, {}, [], []

    for article in articles or []:
        if not isinstance(article, dict):
            continue
        article = normalize_article(article)
        if not (article.get("title") or article.get("url")):
            continue
        doi = extract_doi(article)
        if doi and doi in by_doi:
            _merge(by_doi[doi], article)
            continue
        canon = canonical_url(article.get("url") or "")
        if canon and canon in by_url:
            _merge(by_url[canon], article)
            continue
        tokens = title_key(article.get("title") or "")
        duplicate = next((existing for tokens_existing, existing in seen_titles
                          if _titles_match(tokens, tokens_existing)), None)
        if duplicate is not None:
            _merge(duplicate, article)
            continue

        out.append(article)
        if doi:
            by_doi[doi] = article
        if canon:
            by_url[canon] = article
        seen_titles.append((tokens, article))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Diversity
# ─────────────────────────────────────────────────────────────────────────────
def apply_diversity(scored, max_per_source=3, max_per_topic=4, limit=25):
    """Greedily keep top-scored items while capping publisher/topic repetition.

    The cap counts *publishers*, not feed labels. Most items arrive via the
    Google News aggregator, so counting the raw ``source`` would treat every
    outlet as "Google News" and cap the whole feed at a handful of stories.
    """
    out, source_counts, topic_counts = [], {}, {}
    for score, article in scored:
        source = effective_source(article)
        topic = article.get("topic") or ""
        if source and source_counts.get(source, 0) >= max_per_source:
            continue
        if topic and topic_counts.get(topic, 0) >= max_per_topic:
            continue
        out.append(article)
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
        if topic:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(out) >= limit:
            break
    return out


def _weighted(features, weights):
    """Weighted mean over available signals; unknown metadata contributes none.

    Renormalizing over observed feature weights means missing credibility or
    publication-date evidence is neither assigned a fabricated score nor an
    implicit penalty.
    """
    available = [(weights.get(name, 0.0), value)
                 for name, value in features.items()
                 if value is not None and weights.get(name, 0.0) > 0]
    weight_sum = sum(weight for weight, _ in available)
    if not weight_sum:
        return 0.0
    return sum(weight * value for weight, value in available) / weight_sum


def _relevance(article):
    try:
        return max(0.0, min(1.0, float(article.get("relevance") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _eligible(pool, min_relevance):
    """Records that clear this feed's relevance floor.

    The structural gate already ran at adapter output; this is the documented
    ranking threshold, so a weak match can never appear in a personalised feed
    simply because the feed had few candidates.
    """
    return [a for a in (pool or []) if _relevance(a) >= min_relevance]


def _subtopic_for(article, subtopics_by_topic):
    topic = article.get("topic") or ""
    return subtopic_match(article, (subtopics_by_topic or {}).get(topic) or [])


def _personalisation_boost(article, reading_profile, followed_sources,
                           recent_sources=None, negative_feedback=None):
    """Soft, capped boost from reading history and followed sources.

    Returns a value in [0, 0.15] so personalisation nudges rather than
    dominates — a followed source or a repeatedly-read topic rises modestly,
    but the feed cannot be captured by a single source or interest.
    """
    boost = 0.0
    rp = reading_profile or {}
    topics = (rp.get("topics") or {}) if isinstance(rp, dict) else {}
    sources = (rp.get("sources") or {}) if isinstance(rp, dict) else {}
    art_topic = (article.get("topic") or "").strip()
    art_source = (article.get("source") or "").strip()
    if art_topic and art_topic in topics:
        affinity = min(1.0, topics[art_topic] / 5.0)
        boost += 0.08 * affinity
    if art_source and art_source in sources:
        affinity = min(1.0, sources[art_source] / 5.0)
        boost += 0.05 * affinity
    if followed_sources and art_source in (followed_sources or set()):
        boost += 0.04
    # Source-level novelty: penalise sources seen in the recent refresh.
    if recent_sources and art_source in (recent_sources or set()):
        boost -= 0.06
    # Negative feedback penalty.
    fb_key = f"{art_topic}::{art_source}"
    if negative_feedback and fb_key in (negative_feedback or set()):
        boost -= 0.25
    return min(0.15, max(-0.30, boost))


# ─────────────────────────────────────────────────────────────────────────────
# Feed A — For You
# ─────────────────────────────────────────────────────────────────────────────
def rank_for_you(pool, topics, subtopics, preferences=(), role=None, today=None,
                 reading_profile=None, followed_sources=None, recent_sources=None,
                 negative_feedback=None):
    """Balanced feed: relevance + preference fit + recency, plus discovery slots.

    Articles from outside the user's interests are included but scored with a
    ``discovery_penalty`` so they surface in modest numbers rather than dominate.
    """
    cfg = CONFIG["for_you"]
    user_topics = set(topics or [])
    today = today or datetime.now()
    if not isinstance(today, datetime):
        today = datetime(today.year, today.month, today.day)
    discovery_cutoff = cfg["discovery_max_age_days"]

    def is_current_discovery(article):
        published = parse_date(cq.publication_date_value(article))
        if published is None:
            return False
        age = (today - published).days
        return 0 <= age <= discovery_cutoff

    user_scored, discovery_scored = [], []
    for article in _eligible(pool, cfg["min_relevance"]):
        features = {
            "relevance": _relevance(article),
            "subtopic": _subtopic_for(article, subtopics),
            "preference": preference_match(article, preferences, user_topics),
            "freshness": freshness(cq.publication_date_value(article), today),
            "quality": source_quality(article),
            "profile": profile_affinity(article, role),
        }
        score = (_weighted(features, cfg)
                + _personalisation_boost(article, reading_profile, followed_sources, recent_sources,
                                      negative_feedback))
        outside = bool(user_topics) and (article.get("topic") or "") not in user_topics
        if outside:
            if not is_current_discovery(article):
                continue
            score *= cfg["discovery_penalty"]
            discovery_scored.append((score, article))
        else:
            user_scored.append((score, article))

    user_ranked = apply_diversity(user_scored, cfg["max_per_source"],
                                  cfg["max_per_topic"], cfg["limit"])
    # Discovery is a small, explicit part of For You — never half the feed.
    slots = cfg["discovery_slots"]
    discovery_ranked = apply_diversity(
        discovery_scored, cfg["max_per_source"],
        cfg["discovery_max_per_topic"], slots) if slots else []

    ranked = user_ranked + discovery_ranked
    score_by_id = {id(article): score
                   for score, article in user_scored + discovery_scored}
    ranked.sort(key=lambda article: score_by_id.get(id(article), 0.0), reverse=True)
    # Re-apply diversity across the combined list: a publisher must not exceed
    # the cap just because it appears in both the interest and discovery parts.
    return apply_diversity([(score_by_id[id(article)], article) for article in ranked],
                           cfg["max_per_source"], cfg["max_per_topic"],
                           cfg["limit"])


# ─────────────────────────────────────────────────────────────────────────────
# Feed B — My Fields
# ─────────────────────────────────────────────────────────────────────────────
def rank_my_fields(pool, topics, subtopics, preferences=(), role=None,
                   filter_topic=None, today=None, reading_profile=None,
                   followed_sources=None, recent_sources=None):
    """Interest-faithful feed; optionally restricted to a single interest."""
    cfg = CONFIG["my_fields"]
    user_topics = set(topics or [])
    has_gk = "General knowledge beyond my usual interests" in (preferences or [])
    if has_gk:
        # Include cross-topic articles (they'll be scored with the GK boost).
        candidates = list(_eligible(pool, cfg["min_relevance"]))
    else:
        candidates = [a for a in _eligible(pool, cfg["min_relevance"])
                      if not user_topics or (a.get("topic") or "") in user_topics]
    if filter_topic and filter_topic != "All":
        candidates = [a for a in candidates if (a.get("topic") or "") == filter_topic]

    scored = []
    for article in candidates:
        features = {
            "relevance": _relevance(article),
            "subtopic": _subtopic_for(article, subtopics),
            "preference": preference_match(article, preferences, user_topics),
            "freshness": freshness(cq.publication_date_value(article), today),
            "quality": source_quality(article),
            "profile": profile_affinity(article, role),
        }
        scored.append((_weighted(features, cfg)
                       + _personalisation_boost(article, reading_profile, followed_sources),
                      article))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    topic_cap = (cfg["max_per_topic_filtered"]
                 if filter_topic and filter_topic != "All" else cfg["max_per_topic"])
    return apply_diversity(scored, cfg["max_per_source"], topic_cap, cfg["limit"])


# ─────────────────────────────────────────────────────────────────────────────
# Feed C — Emerging Trends (presented as recent developments)
# ─────────────────────────────────────────────────────────────────────────────
# Two headlines are treated as the same story only when their *distinctive*
# tokens (topic words removed) overlap substantially. Requiring a Jaccard of
# 0.5 prevents generic words like "health" or "government" from faking
# corroboration, which is the main failure mode of a naive word-overlap count.
CORROBORATION_MIN_SHARED = 3
CORROBORATION_MIN_JACCARD = 0.5


def corroboration_scores(articles):
    """Share of *other distinct sources* covering a similar story.

    Sources recorded during deduplication (``sources``) always count. Beyond
    that, articles whose distinctive title tokens overlap substantially are
    treated as covering the same development. This is a corroboration signal,
    never a claim of a confirmed trend or of popularity.
    """
    topic_tokens = set()
    for article in articles:
        topic_tokens |= set(title_key(article.get("topic") or ""))
    token_sets = []
    for article in articles:
        token_sets.append(set(title_key(story_title(article))) - topic_tokens)

    scores = {}
    for index, article in enumerate(articles):
        sources = set(article.get("sources") or [])
        if effective_source(article):
            sources.add(effective_source(article))
        for other_index, other in enumerate(articles):
            if other_index == index:
                continue
            mine, theirs = token_sets[index], token_sets[other_index]
            if len(mine) < CORROBORATION_MIN_SHARED or len(theirs) < CORROBORATION_MIN_SHARED:
                continue
            shared = len(mine & theirs)
            if shared < CORROBORATION_MIN_SHARED:
                continue
            if shared / len(mine | theirs) < CORROBORATION_MIN_JACCARD:
                continue
            sources.update(other.get("sources") or [])
            if effective_source(other):
                sources.add(effective_source(other))
        distinct = len({s for s in sources if s})
        scores[id(article)] = min(1.0, max(0, distinct - 1) / 3.0)
    return scores


def rank_emerging(pool, topics, subtopics, preferences=(), role=None, today=None,
                 reading_profile=None, followed_sources=None, recent_sources=None,
                 negative_feedback=None):
    """Recent developments ranked by recency, corroboration and source quality.

    Distinct from My Fields: freshness dominates, items independently reported
    by several sources are placed ahead of single-source items, and results are
    labelled "recent developments" in the UI, not confirmed trends.
    """
    cfg = CONFIG["emerging"]
    today = today or datetime.now()
    if not isinstance(today, datetime):
        today = datetime(today.year, today.month, today.day)
    max_age = cfg["max_age_days"]

    def is_recent(article):
        published = parse_date(cq.publication_date_value(article))
        if published is None:
            return False
        age = (today - published).days
        return 0 <= age <= max_age

    articles = [a for a in _eligible(pool, cfg["min_relevance"]) if is_recent(a)]
    user_topics = set(topics or [])
    corroboration = corroboration_scores(articles)
    scored = []
    for article in articles:
        features = {
            "freshness": freshness(cq.publication_date_value(article), today),
            "corroboration": corroboration.get(id(article), 0.0),
            "quality": source_quality(article),
            "relevance": _relevance(article),
            "preference": preference_match(article, preferences, user_topics),
        }
        score = (_weighted(features, cfg)
                + _personalisation_boost(article, reading_profile, followed_sources, recent_sources,
                                      negative_feedback))
        if user_topics and (article.get("topic") or "") in user_topics:
            score += cfg["interest_bonus"]
        scored.append((score, article))
    # Tier 1: developments covered independently by more than one source.
    # Tier 2: everything else, by the usual recency/quality score.
    scored.sort(
        key=lambda pair: (corroboration.get(id(pair[1]), 0.0) > 0, pair[0]),
        reverse=True,
    )
    return apply_diversity(scored, cfg["max_per_source"], cfg["max_per_topic"], cfg["limit"])


# ─────────────────────────────────────────────────────────────────────────────
# Feed D — Broaden My Knowledge
# ─────────────────────────────────────────────────────────────────────────────
def rank_broaden(pool, topics, subtopics, preferences=(), role=None,
                 outside_topics=(), today=None, reading_profile=None,
                 followed_sources=None, recent_sources=None,
                 negative_feedback=None):
    """High-quality material from outside the user's primary interests.

    ``outside_topics`` lets the caller name topics retrieved purely for
    discovery. If too few outside items exist, a small number of accessible
    in-interest explainers are appended so the feed is not empty — the reality
    of the candidate pool is not hidden from the caller.
    """
    cfg = CONFIG["broaden"]
    user_topics = set(topics or [])
    outside = set(outside_topics or []) - user_topics

    def is_outside(article):
        topic = article.get("topic") or ""
        if not user_topics:
            return True
        if outside:
            return topic in outside
        return topic not in user_topics

    def score(article):
        features = {
            "freshness": freshness(cq.publication_date_value(article), today),
            "quality": source_quality(article),
            "preference": preference_match(article, preferences, user_topics),
            "relevance": _relevance(article),
        }
        value = (_weighted(features, cfg)
                + _personalisation_boost(article, reading_profile, followed_sources, recent_sources,
                                      negative_feedback))
        # Accessible formats are preferable when broadening.
        if infer_content_type(article) in ("explainer", "research"):
            value += 0.05
        return value

    eligible = _eligible(pool, cfg["min_relevance"])
    outside_items = sorted(((score(a), a) for a in eligible if is_outside(a)),
                           key=lambda pair: pair[0], reverse=True)
    chosen = apply_diversity(outside_items, cfg["max_per_source"],
                             cfg["max_per_topic"], cfg["limit"])
    # Only top up from the user's own fields when there were genuinely too few
    # outside candidates to work with (not merely because of diversity caps).
    if len(outside_items) < cfg["min_outside_before_fallback"]:
        chosen_ids = {id(a) for a in chosen}
        fallback = sorted(
            ((score(a), a) for a in eligible
             if id(a) not in chosen_ids
             and (a.get("topic") or "") in user_topics
             and infer_content_type(a) in ("explainer", "research")),
            key=lambda pair: pair[0], reverse=True)
        chosen.extend(a for _, a in fallback[:cfg["fallback_limit"]])
    return chosen


# ─────────────────────────────────────────────────────────────────────────────
# Pool construction (bounded, failure-tolerant)
# ─────────────────────────────────────────────────────────────────────────────
MAX_TOPICS_PER_REFRESH = 6
MAX_DISCOVERY_TOPICS = 2


def stable_seed(*parts):
    digest = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def choose_discovery_topics(catalogue, user_topics, limit=MAX_DISCOVERY_TOPICS, seed=0):
    """Deterministically rotate through catalogue topics the user hasn't chosen."""
    blocked = set(user_topics or []) | {"Local News & Community"}
    candidates = sorted(t for t in (catalogue or []) if t not in blocked)
    if not candidates:
        return []
    start = seed % len(candidates)
    rotated = candidates[start:] + candidates[:start]
    return rotated[:max(0, limit)]


def build_pool(loader, topics, subtopics_by_topic=None, discovery_topics=(),
               max_topics=MAX_TOPICS_PER_REFRESH):
    """Retrieve candidates per topic, tolerating individual source failures.

    ``loader(topic, subtopics)`` is any callable returning a list of article
    dicts (in the app this is ``load_topic_articles``). Failures are captured
    per topic so valid results from other topics are preserved.

    Returns ``(pool, errors)`` where errors is a list of ``{"topic", "error"}``.
    """
    selected = [t for t in (topics or []) if t != "Local News & Community"][:max_topics]
    per_topic = dict(subtopics_by_topic or {})
    pool, errors = [], []
    seen_topics = set()

    safe_discovery = [t for t in (discovery_topics or [])
                      if t not in selected and t != "Local News & Community"]
    for topic in list(selected) + safe_discovery:
        if topic in seen_topics:
            continue
        seen_topics.add(topic)
        try:
            articles = loader(topic, per_topic.get(topic) or None) or []
        except Exception as exc:  # a single adapter must not kill the feed
            errors.append({"topic": topic, "error": str(exc) or exc.__class__.__name__})
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            article = normalize_article(article)
            article.setdefault("topic", topic)
            article.setdefault("retrieval_topic", topic)
            # Re-validate: a loader may add records that bypassed the adapter
            # gate (e.g. a followed source), and generic pages must never reach
            # ranking or briefing counts.
            ok, _reason = cq.validate(article, article.get("topic") or topic)
            if not ok:
                continue
            try:
                relevance = float(article.get("relevance") or 0.0)
            except (TypeError, ValueError):
                relevance = 0.0
            # Below the lowest feed floor, a record is ineligible for every
            # strategy, so it is not allowed to consume pool or briefing budget.
            if relevance < cq.RELEVANCE["min_broaden"]:
                continue
            retrieval_topic = article.get("topic") or topic
            article.setdefault("retrieval_topic", retrieval_topic)
            # Map category-expanded queries (for example "Health & Medicine
            # fellowship") back to the selected parent interest without
            # claiming a match for unrelated outside-discovery candidates.
            matched_interest = next((selected_topic for selected_topic in selected
                                     if retrieval_topic.lower() == selected_topic.lower()
                                     or retrieval_topic.lower().startswith(selected_topic.lower() + " ")),
                                    None)
            if matched_interest:
                matches = list(article.get("matched_interests") or [])
                if matched_interest not in matches:
                    matches.append(matched_interest)
                article["matched_interests"] = matches
                matched_subtopics = list(article.get("matched_subtopics") or [])
                for subtopic in per_topic.get(matched_interest) or []:
                    if subtopic_match(article, [subtopic]) > 0 and subtopic not in matched_subtopics:
                        matched_subtopics.append(subtopic)
                article["matched_subtopics"] = matched_subtopics
            article = normalize_article(article)
            pool.append(article)

    return dedupe_articles(pool), errors


def search_articles(articles, query):
    """Case-insensitive title/summary search that preserves feed ordering."""
    needle = (query or "").strip().lower()
    if not needle:
        return list(articles or [])
    return [a for a in (articles or [])
            if needle in (a.get("title") or "").lower()
            or needle in (a.get("summary") or "").lower()]


# ─────────────────────────────────────────────────────────────────────────────
# Source recommendations — score candidate sources for a user.
# ─────────────────────────────────────────────────────────────────────────────
# Source type -> content types it typically carries.
SOURCE_TYPE_CONTENT = {
    "journal": {"research"}, "repository": {"research"},
    "institution": {"policy", "organisation"},
    "government": {"policy", "news"}, "research": {"research"},
    "news": {"news", "industry"}, "publication": {"research", "news"},
    "organisation": {"policy", "industry", "organisation"},
}

# Preference -> content types (reused from PREFERENCE_TYPES).
def _pref_content_types(preferences):
    cts = set()
    for p in (preferences or []):
        cts |= PREFERENCE_TYPES.get(p, set())
    return cts

def score_source(source, user_topics, user_preferences=(), followed_sources=()):
    """Score a discovered source (0..1) for a given user.

    Considers three signals:
      1. User interests/subtopics (topic overlap).
      2. Selected discovery preferences (content-type alignment).
      3. Source credibility (type bonus + live feed) and followed penalty.
    """
    name = (source.get("name") or "").strip()
    topics = set(source.get("topics") or [])
    user_topics = set(user_topics or [])
    overlap = topics & user_topics
    overlap_ratio = len(overlap) / max(1, len(user_topics)) if user_topics else 0.0

    source_type = (source.get("source_type") or "").lower()
    type_bonus = {
        "journal": 0.15, "publication": 0.12, "institution": 0.10,
        "government": 0.12, "research": 0.12, "news": 0.05,
    }.get(source_type, 0.03)

    # Preference alignment: does this source's typical content match the
    # user's discovery preferences?
    pref_cts = _pref_content_types(user_preferences)
    src_cts = SOURCE_TYPE_CONTENT.get(source_type, set())
    # Also infer from topics matching preference keywords.
    pref_overlap = pref_cts & src_cts
    pref_bonus = 0.25 * (len(pref_overlap) / max(1, len(pref_cts))) if pref_cts else 0.0

    feed_bonus = 0.10 if source.get("feed_status") == "active" else 0.0
    followed_penalty = 0.30 if (name in (followed_sources or set())
                                or source.get("feed_url") in (followed_sources or set())) else 0.0

    score = min(1.0, 0.30 * overlap_ratio + type_bonus + feed_bonus
                + pref_bonus - followed_penalty)

    # Reason combines topic overlap + preference alignment.
    if overlap and pref_overlap:
        reason = ("Covers " + ", ".join(sorted(overlap)[:2]) +
                  " · matches " + ", ".join(sorted(pref_overlap)[:2]))
    elif overlap:
        reason = "Covers " + ", ".join(sorted(overlap)[:2])
    elif pref_overlap:
        reason = "Matches " + ", ".join(sorted(pref_overlap)[:2])
    elif topics:
        reason = "Related to " + ", ".join(sorted(topics)[:2])
    else:
        reason = "Potentially useful source"
    if source.get("feed_status") == "active":
        reason += " · live feed"
    return {"score": round(score, 3), "reason": reason}


def recommend_sources(sources, user_topics, user_preferences=(), followed_sources=(),
                      limit=12):
    """Rank a list of discovered sources for a user, excluding already-followed."""
    scored = []
    for s in (sources or []):
        key = s.get("feed_url") or s.get("homepage_url") or s.get("name")
        if key in (followed_sources or set()):
            continue
        res = score_source(s, user_topics, user_preferences, followed_sources)
        scored.append((res["score"], res["reason"], s))
    scored.sort(key=lambda t: t[0], reverse=True)
    out = []
    for score, reason, src in scored[:limit]:
        item = dict(src)
        item["_score"] = score
        item["_reason"] = reason
        out.append(item)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Similar sources — topic-co-occurrence based recommendations.
# ─────────────────────────────────────────────────────────────────────────────
def similar_sources(source, all_sources, limit=4):
    """Return sources that share topics with the given source.

    Approximates collaborative filtering using topic overlap since we do not
    yet have cross-user follow data. Returns a list of source dicts.
    """
    src_topics = set(source.get("topics") or [])
    if not src_topics:
        return []
    scored = []
    for other in (all_sources or []):
        if other is source:
            continue
        other_key = other.get("feed_url") or other.get("homepage_url") or other.get("name")
        src_key = source.get("feed_url") or source.get("homepage_url") or source.get("name")
        if other_key == src_key:
            continue
        other_topics = set(other.get("topics") or [])
        overlap = src_topics & other_topics
        if not overlap:
            continue
        jaccard = len(overlap) / max(1, len(src_topics | other_topics))
        scored.append((jaccard, other))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [s for _, s in scored[:limit]]
