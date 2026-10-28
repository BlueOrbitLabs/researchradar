"""Content quality: structural gate, relevance scoring, eligibility and briefing.

Pure functions only — no Streamlit, no network. The module is applied twice:

1. At adapter output (``app.load_topic_articles``): reject generic pages before
   they can ever be ranked, labelled or counted in a briefing.
2. At display/eligibility time (feed strategies, briefing): apply the documented
   relevance thresholds.

Rejections are logged server-side (never rendered as raw text to users).
Thresholds live in ``RELEVANCE`` below; per-feed floors live in
``feed_strategy.CONFIG``. Set ``OWLUME_DIAGNOSTICS=1`` to emit rejection (INFO)
and down-rank (DEBUG) messages to the server log.

The module is calibrated against live adapters but tested with fixtures: live
APIs are non-deterministic, so ``tests/test_content_quality.py`` uses controlled
records and the real-source checks are run separately (see the Phase 1B report).
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date, datetime

logger = logging.getLogger("owlume.quality")

# Diagnostics are server-side only and opt-in: set OWLUME_DIAGNOSTICS=1 to see
# rejection (INFO) and down-rank (DEBUG) messages in the server log. Nothing
# here is ever rendered in the UI. A host that already configured logging keeps
# its own configuration (basicConfig is a no-op in that case).
if os.environ.get("OWLUME_DIAGNOSTICS"):
    logging.basicConfig(level=logging.DEBUG)


# ─────────────────────────────────────────────────────────────────────────────
# Structural gate
# ─────────────────────────────────────────────────────────────────────────────
# A record must describe one content item. These rules reject directory/category
# pages, library guides and index pages that are not themselves articles. They
# deliberately do NOT reject old records: historical research stays eligible.
GATE = {
    "min_title_chars": 12,
    "min_title_words": 3,
    # Record kinds that are navigation/metadata rather than content (OpenAlex).
    "blocked_kinds": {
        "libguides", "paratext", "peer-review", "erratum", "dataset",
        "standard", "supplementary-materials", "other",
    },
    # Anchored patterns: title starts with a navigation label.
    "generic_title_patterns": [
        r"^libguides\b",
        r"^subject guides?\b",
        r"^research guides?\b",
        r"^library guides?\b",
        r"^(category|tag|topic|topics|archive|archives|index|directory|catalogue|catalog|browse)\b",
        r"^(search results?|advanced search|all topics?|topics a-z)\b",
        r"^(sitemap|site map|page not found|404|sign in|log in|login|register|subscribe)\b",
    ],
    # Trailing navigation suffixes ("... - Home").
    "generic_title_suffixes": [r"[-|:]\s*home\s*$", r"\|\s*(library|libguides)\s*$"],
    # Corporate/promotional notices. These are individual items, but they are
    # announcements ("to present at", earnings calls, ticker listings) rather
    # than research or reporting about the field, so they are not feed content.
    "promotional_title_patterns": [
        r"\bto present (at|in)\b",
        r"\bto participate in\b.*\bconference\b",
        r"\binvestor (conference|presentation|webcast|call)\b",
        r"\bearnings (call|conference|webcast|release)\b",
        r"\bconference (call|webcast)\b",
        r"\bto (host|webcast) (a |its )?(conference|call)\b",
        r"\bannounces? (pricing|closing|pricing of|pricing of its)\b",
        r"\b(shares?|stock) (rise|fall|surge|plunge|jump|soar|drop|slide)\b",
        r"\b(NYSE|NASDAQ|LSE|TSX)\s*[:\-]",
        r"\bclass action (lawsuit|suit|filed)\b",
        r"\b(shareholders?|investors?) (of|alert|deadline)\b",
        r"\bquarter(ly)? (results|earnings|revenue)\b",
        r"\bto acquire\b.*\b(company|corporation|inc\.?)\b",
    ],
    # Book/reference works are catalogued records, not individual articles.
    "reference_title_patterns": [
        r"^(short\s+|a\s+|an\s+|the\s+|oxford\s+|cambridge\s+|routledge\s+)?"
        r"(textbook|handbook|encyclopedia|encyclopaedia|dictionary|companion)\b",
        r"\b(textbook|handbook|encyclopedia|encyclopaedia|dictionary)\s+of\b",
        r"^the\s+[a-z ]{3,40}\s+guide\s+to\b",
    ],
    # URL shapes that are indexes, not articles.
    "generic_url_markers": [
        "/libguides/", "/search?", "/search/", "/category/", "/tag/",
        "/topics/", "/browse", "/catalog", "/catalogue", "/directory",
        "/sitemap", "/login", "/signin", "/register", "/subject/", "?q=",
    ],
}

# Words that carry no topical evidence on their own. Used to decide whether a
# title says anything beyond repeating the category name.
GENERIC_TITLE_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "about", "after", "before", "their", "your", "its", "his", "her",
    "society", "studies", "study", "research", "review", "journal",
    "international", "public", "global", "new", "perspectives", "issues",
    "introduction", "handbook", "textbook", "essential", "short", "series",
    "volume", "edition", "history", "guide", "overview", "analysis", "report",
    "news", "update", "updates", "today", "weekly", "monthly",
}

_COMPILED_GENERIC = [re.compile(p, re.I) for p in GATE["generic_title_patterns"]]
_COMPILED_SUFFIXES = [re.compile(p, re.I) for p in GATE["generic_title_suffixes"]]
_COMPILED_PROMOTIONAL = [re.compile(p, re.I) for p in GATE["promotional_title_patterns"]]
_COMPILED_REFERENCE = [re.compile(p, re.I) for p in GATE["reference_title_patterns"]]


def normalise(text):
    """Lower-case, collapse punctuation/whitespace, map '&' to 'and'."""
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text):
    return [t for t in normalise(text).split() if t]


def _content_tokens(text):
    return [t for t in _tokens(text)
            if t not in GENERIC_TITLE_WORDS and (len(t) >= 3 or t == "ai")]


def _title_is_generic_shape(title, topic=None):
    """True when the title only echoes the category name / generic words."""
    title_tokens = set(_content_tokens(title))
    if not title_tokens:
        return True
    if topic:
        allowed = set(_content_tokens(topic)) | GENERIC_TITLE_WORDS
        if title_tokens <= allowed:
            return True
    return False


def _title_echoes_topic(title, topic):
    """True when a title adds at most two content words to the topic name.

    Such records ("Attitudes to business & industry", "The history of American
    business & industry") are too thin to support a *strong* match even when
    they contain the exact topic phrase.
    """
    title_tokens = list(set(_content_tokens(title)))
    topic_terms = _content_tokens(topic)
    if not title_tokens or not topic_terms:
        return False
    patterns = [p for p in (_term_pattern(t) for t in topic_terms) if p]
    if not patterns:
        return False
    matched, extra = 0, []
    for token in title_tokens:
        if any(p.search(token) for p in patterns):
            matched += 1
        else:
            extra.append(token)
    return matched > 0 and len(extra) <= 2


def validate(article, topic=None):
    """Return ``(is_content_item, reason)`` for a candidate record.

    ``reason`` is a short machine label used in logs and tests; it is never
    shown to end users.
    """
    if not isinstance(article, dict):
        return False, "not_a_record"
    title = (article.get("title") or "").strip()
    url = (article.get("url") or "").strip()
    source = (article.get("source") or "").strip()

    if not title:
        return False, "missing_title"
    if len(title) < GATE["min_title_chars"]:
        return False, "short_title"
    if len(title.split()) < GATE["min_title_words"]:
        return False, "too_few_words"
    if not re.search(r"[A-Za-z]{3}", title):
        return False, "no_text"
    if (article.get("kind") or "").lower() in GATE["blocked_kinds"]:
        return False, "blocked_kind"
    for pattern in _COMPILED_GENERIC:
        if pattern.search(title):
            return False, "generic_title"
    for pattern in _COMPILED_SUFFIXES:
        if pattern.search(title):
            return False, "generic_title"
    for pattern in _COMPILED_PROMOTIONAL:
        if pattern.search(title):
            return False, "promotional_listing"
    for pattern in _COMPILED_REFERENCE:
        if pattern.search(title):
            return False, "reference_work"
    if topic and normalise(title) == normalise(topic):
        return False, "topic_page"
    container = (article.get("container") or "").strip()
    if container and normalise(title) == normalise(container):
        return False, "journal_page"
    if _title_is_generic_shape(title, topic):
        return False, "generic_title"
    if not url:
        return False, "missing_url"
    if not re.match(r"^https?://", url, re.I):
        return False, "invalid_url"
    host = re.sub(r"^https?://", "", url, flags=re.I).split("/")[0]
    if not host or "." not in host:
        return False, "invalid_url"
    lowered = url.lower()
    if any(marker in lowered for marker in GATE["generic_url_markers"]):
        return False, "generic_url"
    if not source:
        return False, "missing_source"
    return True, "ok"


def filter_articles(articles, topic=None):
    """Return ``(kept, report)``; logs every rejection with its reason."""
    kept, report = [], Counter()
    for article in articles or []:
        ok, reason = validate(article, topic)
        if ok:
            kept.append(article)
        else:
            report[reason] += 1
            title = (article.get("title") or "")[:100] if isinstance(article, dict) else repr(article)[:100]
            logger.info("rejected (%s): %s", reason, title)
    return kept, report


# ─────────────────────────────────────────────────────────────────────────────
# Relevance
# ─────────────────────────────────────────────────────────────────────────────
# Thresholds are the contract for the UI labels:
#   high     — at least two independent kinds of evidence (or an exact topic
#              phrase) AND a score >= 0.60. A single shared keyword can never
#              earn this label (see the weak-evidence caps below).
#   relevant — partial, supported match (>= 0.30); shown as "Relevant".
#   below 0.30 — not eligible for a personalised feed or the briefing.
RELEVANCE = {
    "phrase_title": 0.35,
    "phrase_summary": 0.20,
    "coverage_title": 0.20,
    "coverage_summary": 0.08,
    "keyword_title_each": 0.05,
    "keyword_summary_each": 0.025,
    "keyword_cap": 0.20,
    "subtopic_title_each": 0.10,
    "subtopic_summary_each": 0.05,
    "subtopic_cap": 0.20,
    "core_title_each": 0.08,
    "core_summary_each": 0.04,
    "core_cap": 0.24,
    "term_title_each": 0.04,
    "term_summary_each": 0.02,
    "term_cap": 0.12,
    "weak_cap": 0.40,        # single-signal matches can be Relevant, never High
    "generic_title_cap": 0.45,
    # A short title that is essentially the category name plus one or two words
    # ("Attitudes to business & industry") is a thin record: capped below High.
    "topic_echo_cap": 0.55,
    # Discipline-scoped sources (PubMed, category-constrained arXiv) only return
    # records their index matched to the query, so the index scope is itself a
    # relevance signal. The floor is exactly the "Relevant" threshold: it can
    # promote a terse record to Relevant but can never claim a High match.
    "discipline_floor": 0.30,
    # Human-interest/career/consumer vocabulary is down-ranked for research
    # topics: a parenting or "healthy travel tips" piece should not outrank
    # subject-matter reporting on the same keyword.
    "lifestyle_penalty": 0.10,
    "high": 0.60,
    "relevant": 0.30,
    "min_feed": 0.30,
    "min_emerging": 0.25,
    "min_broaden": 0.20,
    "min_briefing": 0.30,
    "briefing_window_days": 7,
}

# Consumer/lifestyle/human-interest vocabulary used only for the penalty above.
LIFESTYLE_TERMS = {
    "parenting", "parent", "parents", "toddler", "baby", "babies", "kids",
    "children", "family", "families", "wedding", "relationship", "dating",
    "celebrities", "celebrity", "actor", "actress", "tv", "movie", "film",
    "music", "fashion", "beauty", "style", "recipe", "recipes", "cooking",
    "restaurant", "travel", "holiday", "vacation", "wellness", "self-care",
    "horoscope", "astrology", "sports", "football", "basketball", "olympics",
    "entertainment", "gossip", "royal", "influencer", "shopping", "deals",
    "discount", "gift", "gifts", "career", "job", "jobs", "promotion",
    "resume", "interview", "productivity", "habits", "tips", "hacks",
}

_COMPILED_LIFESTYLE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(t) for t in LIFESTYLE_TERMS),
                               key=len, reverse=True)) + r")\b", re.I)


def _phrase_pattern(phrase):
    tokens = _tokens(phrase)
    if not tokens:
        return None
    return re.compile(r"\b" + r"\W+".join(re.escape(t) for t in tokens) + r"\b", re.I)


def _term_pattern(term):
    """Word-ish pattern with light morphology (plurals, -ation, -ic, -al).

    This lets a catalogue term such as "Vaccines" match "vaccination" without
    matching unrelated words; it only ever extends the term's own stem.
    """
    term = normalise(term)
    if not term:
        return None
    if " " in term:
        return re.compile(r"\b" + re.escape(term) + r"\b", re.I)
    if len(term) <= 4:
        return re.compile(r"\b" + re.escape(term) + r"\b", re.I)
    stem = term
    if stem.endswith("s") and not stem.endswith("ss"):
        stem = stem[:-1]
    if stem.endswith("e"):
        stem = stem[:-1]
    if stem.endswith("y"):
        stem = stem[:-1]
        suffixes = r"(?:y|ies|ical|ically|ic)?"
    else:
        suffixes = r"(?:e|es|s|al|ic|ical|ically|ing|ed|ion|ions|ation|ations|ly)?"
    return re.compile(r"\b" + re.escape(stem) + suffixes + r"\b", re.I)


def _hits(terms, text):
    """Count distinct terms present in ``text`` (ignoring empty/duplicate terms)."""
    if not text:
        return 0
    seen, count = set(), 0
    for term in terms or []:
        key = normalise(term)
        if not key or key in seen:
            continue
        seen.add(key)
        pattern = _term_pattern(term)
        if pattern and pattern.search(text):
            count += 1
    return count


def topic_coverage(topic, text):
    """Fraction of distinct topic tokens present in ``text``."""
    tokens = [t for t in _tokens(topic) if t not in GENERIC_TITLE_WORDS]
    tokens = [t for t in tokens if len(t) >= 3 or t == "ai"]
    if not tokens or not text:
        return 0.0
    normalised = normalise(text)
    matched = 0
    for token in dict.fromkeys(tokens):
        pattern = _term_pattern(token)
        if pattern and pattern.search(normalised):
            matched += 1
    return matched / len(dict.fromkeys(tokens))


def explain_relevance(article, topic, subtopics=(), keywords=(),
                      core_terms=(), terms=(), discipline_scoped=False,
                      lifestyle_penalty=False):
    """Return the score plus the signals that produced it (for tests/logs).

    ``discipline_scoped`` is set by adapters whose source scope is restricted to
    the topic's field: PubMed (biomedical index), category-constrained arXiv and
    the NBER working-paper series. It raises the floor to
    ``RELEVANCE["discipline_floor"]`` but can never produce a High match.
    ``lifestyle_penalty`` subtracts a small amount for consumer/human-interest
    vocabulary so those pieces do not outrank subject-matter reporting.
    """
    title = normalise(article.get("title"))
    summary = normalise(article.get("summary"))
    subtopics = list(subtopics or [])
    keywords = list(keywords or [])

    phrase = _phrase_pattern(topic)
    phrase_title = bool(phrase and title and phrase.search(title))
    phrase_summary = bool(phrase and summary and phrase.search(summary))
    lifestyle_hit = bool(
        lifestyle_penalty
        and _COMPILED_LIFESTYLE.search((article.get("title") or "") + " "
                                       + (article.get("summary") or ""))
    )
    # Deterministic synonym/alias experiment: a multiword curated catalogue
    # keyword (e.g. "artificial intelligence") can stand for a short UI label
    # (e.g. "AI & Technology"). Reuse existing phrase weights; do not add a
    # new weight or call a model per article. Exact topic phrases take
    # precedence so an alias is not counted twice.
    phrase_aliases = [term for term in keywords
                      if len(_tokens(term)) > 1
                      and normalise(term) != normalise(topic)]
    alias_title = bool(not phrase_title and not lifestyle_hit and _hits(phrase_aliases, title))
    alias_summary = bool(not phrase_summary and not lifestyle_hit and _hits(phrase_aliases, summary))
    coverage_title = topic_coverage(topic, title)
    coverage_summary = topic_coverage(topic, summary)
    keyword_title = _hits(keywords, title)
    keyword_summary = _hits(keywords, summary)
    subtopic_title = _hits(subtopics, title)
    subtopic_summary = _hits(subtopics, summary)
    core_title = _hits(core_terms, title)
    core_summary = _hits(core_terms, summary)
    term_title = _hits(terms, title)
    term_summary = _hits(terms, summary)

    score = 0.0
    if phrase_title or alias_title:
        score += RELEVANCE["phrase_title"]
    elif phrase_summary or alias_summary:
        score += RELEVANCE["phrase_summary"]
    score += RELEVANCE["coverage_title"] * coverage_title
    score += RELEVANCE["coverage_summary"] * coverage_summary
    score += min(RELEVANCE["keyword_cap"],
                 RELEVANCE["keyword_title_each"] * keyword_title
                 + RELEVANCE["keyword_summary_each"] * keyword_summary)
    score += min(RELEVANCE["subtopic_cap"],
                 RELEVANCE["subtopic_title_each"] * subtopic_title
                 + RELEVANCE["subtopic_summary_each"] * subtopic_summary)
    score += min(RELEVANCE["core_cap"],
                 RELEVANCE["core_title_each"] * core_title
                 + RELEVANCE["core_summary_each"] * core_summary)
    score += min(RELEVANCE["term_cap"],
                 RELEVANCE["term_title_each"] * term_title
                 + RELEVANCE["term_summary_each"] * term_summary)

    # A single shared keyword is not enough for a *strong* claim.
    strong = (
        phrase_title
        or alias_title
        or coverage_title >= 0.999
        or subtopic_title > 0
        or core_title > 0
        or keyword_title >= 2
    )
    if score > 0 and not strong:
        score = min(score, RELEVANCE["weak_cap"])
    # A curated multi-word subject alias in the publisher's title/summary is
    # enough evidence for Relevant, but never High, when the UI category uses
    # a different short label. Keep the floor at the existing Relevant
    # threshold rather than adding another tuned weight.
    if alias_summary and not alias_title:
        score = max(score, RELEVANCE["relevant"])
    # Titles that only echo the category name are not strong matches either.
    generic_shape = _title_is_generic_shape(article.get("title"), topic)
    if generic_shape:
        score = min(score, RELEVANCE["generic_title_cap"])
    topic_echo = _title_echoes_topic(article.get("title"), topic)
    if topic_echo:
        score = min(score, RELEVANCE["topic_echo_cap"])
    # Human-interest/consumer framing is weaker evidence than subject reporting.
    if lifestyle_hit:
        score = max(0.0, score - RELEVANCE["lifestyle_penalty"])
    # Index scope is evidence of topical fit, but only enough for "Relevant"
    # (0.30 < high 0.60), never a High match.
    if discipline_scoped:
        score = max(score, RELEVANCE["discipline_floor"])

    if score > 0 and (not strong or generic_shape or topic_echo or lifestyle_hit):
        logger.debug(
            "down-ranked (weak=%s generic_title=%s topic_echo=%s lifestyle=%s): "
            "%.2f %s",
            not strong, generic_shape, topic_echo, lifestyle_hit,
            score, (article.get("title") or "")[:100],
        )

    return {
        "score": round(min(1.0, max(0.0, score)), 3),
        "signals": {
            "phrase_title": phrase_title,
            "phrase_summary": phrase_summary,
            "alias_title": alias_title,
            "alias_summary": alias_summary,
            "coverage_title": round(coverage_title, 3),
            "coverage_summary": round(coverage_summary, 3),
            "keyword_title": keyword_title,
            "keyword_summary": keyword_summary,
            "subtopic_title": subtopic_title,
            "subtopic_summary": subtopic_summary,
            "core_title": core_title,
            "core_summary": core_summary,
            "term_title": term_title,
            "term_summary": term_summary,
            "lifestyle_penalty": lifestyle_hit,
            "discipline_floor": bool(discipline_scoped),
            "weak": score > 0 and not strong,
        },
    }


def relevance_score(article, topic, subtopics=(), keywords=(),
                    core_terms=(), terms=(), discipline_scoped=False,
                    lifestyle_penalty=False):
    """Documented 0–1 relevance score (see ``RELEVANCE`` thresholds)."""
    return explain_relevance(article, topic, subtopics, keywords,
                             core_terms, terms, discipline_scoped,
                             lifestyle_penalty)["score"]


def relevance_label(score):
    """UI label for a score: ``high``, ``relevant`` or ``None``."""
    try:
        score = float(score or 0)
    except (TypeError, ValueError):
        return None
    if score >= RELEVANCE["high"]:
        return "high"
    if score >= RELEVANCE["relevant"]:
        return "relevant"
    return None


def local_relevance_score(article, city, region="", interests=()):
    """Score an article against the active app's location/interest signals.

    This extracts the existing local-news scoring rule into a pure function so
    fixture baselines can exercise the production behavior without network I/O.
    It deliberately preserves the current weights and national-story penalty.
    """
    text = " ".join((article.get("title", ""), article.get("summary", ""))).lower()
    city_lower = (city or "").lower()
    region_lower = (region or "").lower()
    score = 0.0
    if city_lower and city_lower in text:
        score += 0.5
    if region_lower and region_lower in text:
        score += 0.2
    for interest in interests or ():
        prefix = (interest or "").lower()[:6]
        if prefix and prefix in text:
            score += 0.1
    national_words = ["india", "government of india", "parliament",
                      "supreme court of india"]
    location_terms = [city_lower] + ([region_lower] if region_lower else [])
    if not any(term and term in text for term in location_terms):
        if any(word in text for word in national_words):
            score -= 0.1
    return round(min(1.0, max(0.0, score)), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Publisher identity
# ─────────────────────────────────────────────────────────────────────────────
AGGREGATOR_SOURCES = {"google news", "google news india"}


def publisher(article):
    """Publisher name; unwraps Google News' aggregator label using the title."""
    source = (article.get("source") or "").strip()
    if source.lower() in AGGREGATOR_SOURCES:
        title = (article.get("title") or "").strip()
        if " - " in title:
            tail = title.rsplit(" - ", 1)[1].strip()
            if 2 < len(tail) <= 80:
                return tail
    return source


# ─────────────────────────────────────────────────────────────────────────────
# Dates and briefing
# ─────────────────────────────────────────────────────────────────────────────
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                 "%B %d, %Y", "%Y/%m/%d", "%B %Y", "%b %Y", "%Y")


def publication_date_value(article):
    """Publication date only; never substitute RSS update/retrieval time.

    Legacy records without ``publication_date`` continue to use ``date`` unless
    the adapter explicitly marks that value as an RSS update timestamp.
    """
    if not isinstance(article, dict):
        return ""
    published = article.get("publication_date")
    if published:
        return published
    if (article.get("date_source") or "").strip().lower() == "updated":
        return ""
    return article.get("date") or ""


def parse_date(value):
    """Parse the date shapes produced by the adapters; ``None`` if unknown."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"(20\d{2})", text)
    if match:
        return date(int(match.group(1)), 1, 1)
    return None


def canonical_key(article):
    """Identity used to collapse duplicates: DOI, then canonical URL, then title.

    This mirrors ``feed_strategy.dedupe_articles`` closely enough that briefing
    counts cannot include the same record twice (the feed strategy owns the
    richer merge logic; this is a pure key for counting).
    """
    doi = (article.get("doi") or "").strip().lower()
    url = (article.get("url") or "").strip()
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", doi or url.lower())
    if match:
        return "doi:" + match.group(0).rstrip("/.")
    if url:
        url = re.sub(r"^https?://", "", url.lower())
        url = re.sub(r"^www\.", "", url)
        url = url.split("#")[0].split("?")[0].rstrip("/")
        if url:
            return "url:" + url
    return "title:" + normalise(article.get("title"))


def briefing_articles(pool, days=None, limit=3, today=None, preferences=None, role=None):
    """Eligible, deduplicated, recent articles for the daily briefing.

    Only records that pass the structural gate, carry a supported relevance
    score and a real publication date inside the window are counted. Returns
    counts derived from that same list — never an estimate.
    """
    days = RELEVANCE["briefing_window_days"] if days is None else days
    today = today or date.today()
    eligible, seen, rejected = [], set(), Counter()

    for article in pool or []:
        ok, reason = validate(article)
        if not ok:
            rejected[reason] += 1
            continue
        try:
            relevance = float(article.get("relevance") or 0)
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance < RELEVANCE["min_briefing"]:
            rejected["low_relevance"] += 1
            continue
        published = parse_date(publication_date_value(article))
        if not published:
            rejected["unknown_date"] += 1
            continue
        age = (today - published).days
        if age < 0 or age > days:
            rejected["outside_window"] += 1
            continue
        key = canonical_key(article)
        if key in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(key)
        eligible.append(article)

    # Group repetitive coverage: articles with substantially overlapping
    # distinctive title tokens are the same story.
    def _title_tokens(a):
        text = (a.get("title") or "").lower()
        words = set(re.findall(r"[a-z]{4,}", text))
        return words - {"this", "that", "with", "from", "about", "into",
                        "their", "have", "will", "more", "most", "study"}

    groups = []
    for a in eligible:
        toks = _title_tokens(a)
        matched = None
        for g in groups:
            inter = toks & g["tokens"]
            union = toks | g["tokens"]
            if len(inter) >= 3 and (len(inter) / max(1, len(union))) >= 0.35:
                matched = g
                break
        if matched:
            matched["items"].append(a)
            matched["tokens"] |= toks
        else:
            groups.append({"tokens": set(toks), "items": [a]})

    # Pick representative per group (highest relevance, then freshest).
    grouped_items = []
    for g in groups:
        reps = sorted(g["items"], key=lambda a: (float(a.get("relevance") or 0),
                                                 parse_date(a.get("date")) or date.min),
                      reverse=True)
        rep = dict(reps[0])
        rep["_group_sources"] = [x.get("source") for x in g["items"] if x.get("source")]
        rep["_group_count"] = len(g["items"])
        grouped_items.append(rep)

    # Preference/role-aware re-ranking on top of relevance+freshness.
    if preferences or role:
        def _brief_score(a):
            base = float(a.get("relevance") or 0)
            try:
                import feed_strategy as _fs
                pref = _fs.preference_match(a, preferences or [])
                prof = _fs.profile_affinity(a, role)
            except Exception:
                pref = 0.0; prof = 0.0
            return base + 0.15 * pref + 0.10 * prof
        grouped_items.sort(key=_brief_score, reverse=True)
    else:
        grouped_items.sort(
            key=lambda a: (float(a.get("relevance") or 0),
                           parse_date(a.get("date")) or date.min),
            reverse=True,
        )

    return {
        "items": grouped_items[:limit],
        "total": len(eligible),
        "publishers": len({publisher(a) for a in eligible if publisher(a)}),
        "window_days": days,
        "rejected": rejected,
        "groups": len(groups),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────────────────────────────────────
# Bounded, per-process record of the last gate run for each topic. Used only to
# surface aggregate counts in the retrieval-details panel; never business logic.
LAST_REPORTS: dict[str, Counter] = {}


def record_report(topic, report):
    """Remember the gate summary for ``topic`` (bounded to 32 topics)."""
    if not topic:
        return
    LAST_REPORTS[topic] = Counter(report or {})
    while len(LAST_REPORTS) > 32:
        LAST_REPORTS.pop(next(iter(LAST_REPORTS)))


def report_snapshot():
    """Aggregate rejection counts across the last gate run."""
    total = Counter()
    for report in LAST_REPORTS.values():
        total.update(report)
    return total
