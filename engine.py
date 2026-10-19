"""Owlume discovery engine — SQLite persistence, source adapters, adaptive ranking.

Public API consumed by app.py:
    init_db()                           — call once at startup
    record_feedback(url, ftype, topic, source, content_type, note)
    undo_feedback(url, ftype)
    get_user_prefs()  -> UserPrefs
    adaptive_rank(articles, prefs)  -> list
    get_disliked_urls()  -> set[str]
    load_feed(topic, strategy, subtopics, prefs, discover_prefs)  -> list[Article]
    load_emerging(all_topics, prefs)  -> list[Article]
    load_broaden(all_topics, prefs)  -> list[Article]
    persist_articles(articles)
    generate_queries(topic, subtopics, discover_prefs)  -> list[str]
    Article  (TypedDict)
    UserPrefs  (dataclass)
    FeedStrategy  (Enum)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import requests

# ── DB location ───────────────────────────────────────────────────────────────
DB_PATH = Path("owlume.db")

# ── Article schema ─────────────────────────────────────────────────────────────
def _art_id(url: str) -> str:
    """Stable article ID — SHA-256 of canonical URL (lowercased, stripped)."""
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:32]


def make_article(
    *,
    title: str,
    url: str,
    summary: str = "",
    date_str: str = "",
    source: str = "",
    topic: str = "",
    relevance: float = 0.5,
    content_type: str = "news",
    doi: str = "",
    adapter: str = "",
    open_access: bool = False,
    strategy: str = "my_fields",
    geo_relevance: float = 0.0,
) -> dict:
    """Normalised article record. Never invents missing values."""
    return {
        "id": _art_id(url) if url else "",
        "title": title.strip() if title else "",
        "url": url.strip() if url else "",
        "source": source or "",
        "topic": topic or "",
        "date": date_str or "",
        "summary": (summary or "")[:400],
        "relevance": round(float(relevance), 3),
        "content_type": content_type,
        "doi": doi or "",
        "adapter": adapter or "",
        "open_access": bool(open_access),
        "strategy": strategy,
        "geo_relevance": round(float(geo_relevance), 3),
        "retrieved_at": int(time.time()),
    }


# ── SQLite schema ──────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    source      TEXT,
    topic       TEXT,
    date_str    TEXT,
    summary     TEXT,
    relevance   REAL DEFAULT 0,
    content_type TEXT,
    doi         TEXT,
    adapter     TEXT,
    open_access INTEGER DEFAULT 0,
    strategy    TEXT,
    geo_relevance REAL DEFAULT 0,
    retrieved_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    art_id      TEXT,
    ftype       TEXT NOT NULL,
    topic       TEXT,
    source      TEXT,
    content_type TEXT,
    note        TEXT,
    ts          INTEGER DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS feedback_url ON feedback(url);
CREATE INDEX IF NOT EXISTS feedback_ftype ON feedback(ftype);

CREATE TABLE IF NOT EXISTS user_prefs (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


def init_db(path: Path = DB_PATH) -> sqlite3.Connection:
    """Create DB and tables if they don't exist. Returns connection."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _conn() -> sqlite3.Connection:
    return init_db(DB_PATH)


# ── Feedback ───────────────────────────────────────────────────────────────────
VALID_FTYPES = {
    "more_like", "less_like", "not_interested", "save",
    "irrelevant", "repetitive", "too_basic", "too_technical",
    "wrong_topic", "source_pref",
}


def record_feedback(
    url: str,
    ftype: str,
    topic: str = "",
    source: str = "",
    content_type: str = "",
    note: str = "",
) -> None:
    """Persist one feedback event; update learned prefs."""
    if ftype not in VALID_FTYPES:
        return
    art_id = _art_id(url)
    with _conn() as db:
        db.execute(
            "INSERT INTO feedback (url, art_id, ftype, topic, source, content_type, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url, art_id, ftype, topic, source, content_type, note),
        )
        db.commit()
    _update_prefs_from_feedback(ftype, topic, source, content_type)


def undo_feedback(url: str, ftype: str) -> None:
    """Remove the most recent feedback event of a given type for a URL."""
    with _conn() as db:
        db.execute(
            "DELETE FROM feedback WHERE id = ("
            "  SELECT id FROM feedback WHERE url=? AND ftype=? ORDER BY ts DESC LIMIT 1"
            ")",
            (url, ftype),
        )
        db.commit()
    # Rebuild prefs from scratch after undo
    _rebuild_prefs()


def get_disliked_urls() -> set:
    """Return URLs the user marked 'not_interested'."""
    with _conn() as db:
        rows = db.execute(
            "SELECT DISTINCT url FROM feedback WHERE ftype='not_interested'"
        ).fetchall()
    return {r[0] for r in rows}


# ── Preference model ───────────────────────────────────────────────────────────
@dataclass
class UserPrefs:
    topic_weights: dict = field(default_factory=dict)      # topic -> float delta
    source_weights: dict = field(default_factory=dict)     # source -> float delta
    depth: str = "any"                                     # 'basic' | 'technical' | 'any'
    not_interested_urls: set = field(default_factory=set)

    def topic_boost(self, topic: str) -> float:
        return self.topic_weights.get(topic, 0.0)

    def source_boost(self, source: str) -> float:
        return self.source_weights.get(source, 0.0)


def _pref_get(key: str, default: Any = None) -> Any:
    with _conn() as db:
        row = db.execute("SELECT value FROM user_prefs WHERE key=?", (key,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]
    return default


def _pref_set(key: str, value: Any) -> None:
    with _conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO user_prefs (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        db.commit()


def get_user_prefs() -> UserPrefs:
    tw = _pref_get("topic_weights", {})
    sw = _pref_get("source_weights", {})
    depth = _pref_get("depth", "any")
    not_int = set(_pref_get("not_interested_urls", []))
    return UserPrefs(topic_weights=tw, source_weights=sw, depth=depth, not_interested_urls=not_int)


def _update_prefs_from_feedback(ftype, topic, source, content_type):
    prefs = get_user_prefs()
    tw = prefs.topic_weights
    sw = prefs.source_weights

    if ftype == "more_like":
        if topic:
            tw[topic] = round(tw.get(topic, 0) + 0.12, 3)
        if source:
            sw[source] = round(sw.get(source, 0) + 0.08, 3)
    elif ftype == "less_like":
        if topic:
            tw[topic] = round(tw.get(topic, 0) - 0.06, 3)
        if source:
            sw[source] = round(sw.get(source, 0) - 0.04, 3)
    elif ftype == "not_interested":
        if topic:
            tw[topic] = round(tw.get(topic, 0) - 0.04, 3)
        urls = set(_pref_get("not_interested_urls", []))
        # (url not available here; caller should pass it separately)
        _pref_set("not_interested_urls", list(urls))
    elif ftype == "too_basic":
        _pref_set("depth", "technical")
        return
    elif ftype == "too_technical":
        _pref_set("depth", "basic")
        return
    elif ftype == "source_pref" and source:
        sw[source] = round(sw.get(source, 0) - 0.10, 3)

    _pref_set("topic_weights", tw)
    _pref_set("source_weights", sw)


def record_not_interested(url: str, topic: str = "", source: str = "") -> None:
    """Convenience: record + mark URL disliked."""
    record_feedback(url, "not_interested", topic=topic, source=source)
    urls = set(_pref_get("not_interested_urls", []))
    urls.add(url)
    _pref_set("not_interested_urls", list(urls))


def _rebuild_prefs() -> None:
    """Recompute preference weights from all feedback in DB."""
    tw: dict = {}
    sw: dict = {}
    depth = "any"
    not_int_urls: set = set()

    with _conn() as db:
        rows = db.execute(
            "SELECT ftype, topic, source, content_type, url FROM feedback ORDER BY ts"
        ).fetchall()

    for ftype, topic, source, content_type, url in rows:
        if ftype == "more_like":
            if topic:
                tw[topic] = round(tw.get(topic, 0) + 0.12, 3)
            if source:
                sw[source] = round(sw.get(source, 0) + 0.08, 3)
        elif ftype == "less_like":
            if topic:
                tw[topic] = round(tw.get(topic, 0) - 0.06, 3)
            if source:
                sw[source] = round(sw.get(source, 0) - 0.04, 3)
        elif ftype == "not_interested":
            if topic:
                tw[topic] = round(tw.get(topic, 0) - 0.04, 3)
            if url:
                not_int_urls.add(url)
        elif ftype == "too_basic":
            depth = "technical"
        elif ftype == "too_technical":
            depth = "basic"
        elif ftype == "source_pref" and source:
            sw[source] = round(sw.get(source, 0) - 0.10, 3)

    _pref_set("topic_weights", tw)
    _pref_set("source_weights", sw)
    _pref_set("depth", depth)
    _pref_set("not_interested_urls", list(not_int_urls))


# ── Adaptive ranking ───────────────────────────────────────────────────────────
def adaptive_rank(articles: list, prefs: UserPrefs) -> list:
    """Re-rank articles using learned preference weights. Non-destructive."""
    disliked = prefs.not_interested_urls

    def _score(art: dict) -> float:
        base = art.get("relevance", 0.0)
        boost = prefs.topic_boost(art.get("topic", ""))
        src_boost = prefs.source_boost(art.get("source", ""))
        # Freshness signal (articles within 30 days get small lift)
        freshness = 0.0
        date_str = art.get("date", "") or art.get("date_str", "")
        if date_str:
            try:
                import datetime
                for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%Y"):
                    try:
                        pub = datetime.datetime.strptime(date_str[:10], fmt[:len(date_str[:10])])
                        days_old = (datetime.datetime.utcnow() - pub).days
                        freshness = max(0, 0.05 * (1 - days_old / 90))
                        break
                    except Exception:
                        pass
            except Exception:
                pass
        return base + boost + src_boost + freshness

    filtered = [a for a in articles if a.get("url", "") not in disliked]
    return sorted(filtered, key=_score, reverse=True)


# ── Article persistence ────────────────────────────────────────────────────────
def persist_articles(articles: list) -> None:
    """Save articles to DB. Existing URLs are ignored (INSERT OR IGNORE)."""
    if not articles:
        return
    rows = [
        (
            a.get("id") or _art_id(a.get("url", "")),
            a.get("title", "")[:400],
            a.get("url", ""),
            a.get("source", ""),
            a.get("topic", ""),
            a.get("date") or a.get("date_str", ""),
            a.get("summary", "")[:800],
            a.get("relevance", 0.5),
            a.get("content_type", "news"),
            a.get("doi", ""),
            a.get("adapter", ""),
            1 if a.get("open_access") else 0,
            a.get("strategy", "my_fields"),
            a.get("geo_relevance", 0.0),
        )
        for a in articles
        if a.get("url")
    ]
    with _conn() as db:
        db.executemany(
            "INSERT OR IGNORE INTO articles "
            "(id,title,url,source,topic,date_str,summary,relevance,content_type,"
            " doi,adapter,open_access,strategy,geo_relevance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()


def cached_articles(topic: str, max_age_s: int = 1800) -> list:
    """Return recently cached articles for a topic, if fresh enough."""
    cutoff = int(time.time()) - max_age_s
    with _conn() as db:
        rows = db.execute(
            "SELECT title,url,source,topic,date_str,summary,relevance,"
            "content_type,doi,adapter,open_access,strategy,geo_relevance "
            "FROM articles WHERE topic=? AND retrieved_at>? ORDER BY relevance DESC",
            (topic, cutoff),
        ).fetchall()
    if not rows:
        return []
    keys = ["title", "url", "source", "topic", "date", "summary", "relevance",
            "content_type", "doi", "adapter", "open_access", "strategy", "geo_relevance"]
    return [dict(zip(keys, r)) for r in rows]


# ── Source adapters ────────────────────────────────────────────────────────────
_HEADERS = {"User-Agent": "Owlume/1.0 (research feed; contact owlumesupport@gmail.com)"}
_TIMEOUT = 12


def fetch_crossref(query: str, topic: str, max_items: int = 10) -> list:
    """Crossref REST API — publication metadata, DOIs."""
    try:
        q = urllib.parse.quote_plus(query)
        url = (
            f"https://api.crossref.org/works?query={q}"
            f"&rows={max_items}&sort=relevance&select=title,DOI,abstract,"
            f"container-title,published,URL,is-referenced-by-count"
        )
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
        arts = []
        for it in items:
            titles = it.get("title", [])
            title = titles[0] if titles else ""
            if not title:
                continue
            doi = it.get("DOI", "")
            link = f"https://doi.org/{doi}" if doi else it.get("URL", "")
            abstract = it.get("abstract", "")
            # Strip JATS XML tags if present
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
            # Date
            pub = it.get("published", {})
            dp = pub.get("date-parts", [[]])[0] if pub else []
            date_str = "-".join(str(p) for p in dp) if dp else ""
            containers = it.get("container-title", [])
            source = containers[0] if containers else "Crossref"
            arts.append(make_article(
                title=title, url=link, summary=abstract[:400],
                date_str=date_str, source=source, topic=topic,
                doi=doi, adapter="crossref", content_type="research",
                open_access=False,
            ))
        return arts
    except Exception:
        return []


def fetch_europepmc(query: str, topic: str, max_items: int = 10) -> list:
    """Europe PMC — biomedical and life-sciences literature."""
    try:
        q = urllib.parse.quote_plus(query)
        url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query={q}&format=json&pageSize={max_items}&sort=RELEVANCE"
            f"&resultType=core"
        )
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        results = r.json().get("resultList", {}).get("result", [])
        arts = []
        for it in results:
            title = it.get("title", "")
            if not title:
                continue
            pmid = it.get("pmid", "")
            doi = it.get("doi", "")
            link = (
                f"https://europepmc.org/article/MED/{pmid}" if pmid
                else (f"https://doi.org/{doi}" if doi else "")
            )
            abstract = it.get("abstractText", "")[:400]
            date_str = it.get("firstPublicationDate", "")
            source = it.get("journalTitle", "Europe PMC")
            is_oa = it.get("isOpenAccess", "N") == "Y"
            arts.append(make_article(
                title=title, url=link, summary=abstract,
                date_str=date_str, source=source, topic=topic,
                doi=doi, adapter="europepmc", content_type="research",
                open_access=is_oa,
            ))
        return arts
    except Exception:
        return []


def fetch_openalex(query: str, topic: str, max_items: int = 10,
                   sort: str = "relevance_score") -> list:
    """OpenAlex API — multidisciplinary scholarly research."""
    try:
        q = urllib.parse.quote_plus(query)
        url = (
            f"https://api.openalex.org/works?search={q}"
            f"&sort={sort}:desc&per-page={max_items}"
            f"&filter=is_paratext:false"
            f"&select=title,doi,abstract_inverted_index,publication_date,"
            f"primary_location,open_access"
        )
        r = requests.get(url, headers={**_HEADERS, "Accept": "application/json"}, timeout=_TIMEOUT)
        r.raise_for_status()
        items = r.json().get("results", [])
        arts = []
        for w in items:
            title = (w.get("title") or "").strip()
            if not title:
                continue
            doi = w.get("doi", "")
            link = (
                f"https://doi.org/{doi.replace('https://doi.org/', '')}" if doi else ""
            )
            if not link:
                loc = w.get("primary_location") or {}
                link = loc.get("landing_page_url") or loc.get("pdf_url") or ""
            # Reconstruct abstract
            inv = w.get("abstract_inverted_index") or {}
            abstract = ""
            if inv:
                pos_word = [(pos, word) for word, pos_list in inv.items() for pos in pos_list]
                pos_word.sort()
                abstract = " ".join(wd for _, wd in pos_word[:80])
            date_str = (w.get("publication_date") or "")[:10]
            oa = (w.get("open_access") or {}).get("is_oa", False)
            arts.append(make_article(
                title=title, url=link, summary=abstract[:400],
                date_str=date_str, source="OpenAlex", topic=topic,
                doi=doi, adapter="openalex", content_type="research",
                open_access=bool(oa),
            ))
        return arts
    except Exception:
        return []


def fetch_doaj(query: str, topic: str, max_items: int = 8) -> list:
    """DOAJ — open-access journals across all disciplines."""
    try:
        q = urllib.parse.quote_plus(query)
        url = f"https://doaj.org/api/search/articles/{q}?pageSize={max_items}&sort=relevance"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        results = r.json().get("results", [])
        arts = []
        for it in results:
            bib = it.get("bibjson", {})
            title = bib.get("title", "")
            if not title:
                continue
            links = bib.get("link", [])
            link = next((l.get("url", "") for l in links if l.get("type") == "fulltext"), "")
            abstract = bib.get("abstract", "")[:400]
            year = str(bib.get("year", ""))
            source = (bib.get("journal") or {}).get("title", "DOAJ")
            arts.append(make_article(
                title=title, url=link, summary=abstract,
                date_str=year, source=source, topic=topic,
                adapter="doaj", content_type="research", open_access=True,
            ))
        return arts
    except Exception:
        return []


def fetch_rss(url: str, label: str, topic: str, max_items: int = 10) -> list:
    """Generic RSS/Atom fetcher."""
    import feedparser
    from datetime import datetime as _dt
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        feed = feedparser.parse(r.content)
        arts = []
        for e in feed.entries[:max_items]:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            raw_sum = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()
            pub = e.get("published_parsed") or e.get("updated_parsed")
            date_str = ""
            if pub:
                try:
                    date_str = _dt(*pub[:6]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            arts.append(make_article(
                title=title, url=e.get("link", ""),
                summary=raw_sum[:400], date_str=date_str,
                source=label, topic=topic, adapter="rss", content_type="news",
            ))
        return arts
    except Exception:
        return []


# ── Query planner ──────────────────────────────────────────────────────────────
_PREF_QUERY_TAGS = {
    "Research publications":    ["research", "study", "findings", "journal"],
    "Emerging trends":          ["emerging", "latest", "new developments", "advances"],
    "Current affairs":          ["news", "policy", "current", "today"],
    "Grants & fellowships":     ["grant", "fellowship", "funding", "call for proposals"],
    "Industry updates":         ["industry", "market", "sector", "update"],
    "Clinical practice":        ["clinical", "practice", "guidelines", "treatment"],
    "Policy & regulation":      ["policy", "regulation", "legislation", "government"],
    "Career opportunities":     ["career", "job", "opportunity", "recruitment"],
}


def generate_queries(
    topic: str,
    subtopics: list | None = None,
    discover_prefs: list | None = None,
) -> list[str]:
    """Build a focused set of search queries from topic + optional context.

    Rules:
    - Always produce the bare topic query.
    - Add up to 2 subtopic queries (one per subtopic, max).
    - Add up to 2 preference-flavoured queries if discover_prefs given.
    - Total cap: 5 queries, to avoid combinatorial explosion.
    """
    queries: list[str] = []
    base = topic.strip()
    if not base:
        return queries

    # 1. Bare topic
    queries.append(base)

    # 2. Subtopic queries
    subs = list(subtopics or [])[:2]
    for sub in subs:
        q = f"{base} {sub}".strip()
        if q not in queries:
            queries.append(q)

    # 3. Preference-flavoured queries
    prefs = list(discover_prefs or [])
    pref_added = 0
    for pref in prefs:
        if pref_added >= 2:
            break
        tags = _PREF_QUERY_TAGS.get(pref, [])
        if tags:
            q = f"{base} {tags[0]}".strip()
            if q not in queries:
                queries.append(q)
                pref_added += 1

    return queries[:5]


# ── Adjacent topics for Broaden ────────────────────────────────────────────────
_ADJACENT: dict[str, list[str]] = {
    "Health & Medicine":      ["Epidemiology", "Global health", "Mental health", "Nutrition science"],
    "AI & Technology":        ["Robotics", "Quantum computing", "Cybersecurity", "Data science"],
    "Finance & Markets":      ["Behavioural economics", "Fintech", "Global trade", "Fiscal policy"],
    "Climate & Environment":  ["Renewable energy", "Biodiversity", "Urban planning", "Water resources"],
    "Science & Research":     ["Philosophy of science", "Science policy", "Open access publishing"],
    "Policy & Government":    ["International relations", "Governance", "Election studies", "Law"],
    "Business & Industry":    ["Supply chain", "Entrepreneurship", "Corporate governance"],
    "Education":              ["EdTech", "Pedagogy", "Higher education policy", "Learning science"],
    "Social Sciences":        ["Anthropology", "Gender studies", "Urban sociology", "Demography"],
    "Arts & Culture":         ["Heritage conservation", "Digital humanities", "Film studies"],
    "World Affairs":          ["Geopolitics", "Diplomacy", "Refugee studies", "Development studies"],
    "Careers":                ["Future of work", "Skills development", "Labour economics"],
}

_TREND_TOPICS = [
    "AI governance", "large language models", "GLP-1 obesity research",
    "antimicrobial resistance", "quantum computing breakthroughs",
    "climate tipping points", "CRISPR gene therapy", "digital public infrastructure",
    "battery technology", "space economy", "misinformation research",
    "longevity science", "sovereign AI", "central bank digital currency",
]


def _adjacent_topics(user_topics: list[str]) -> list[str]:
    seen: set[str] = set(user_topics)
    result: list[str] = []
    for t in user_topics:
        for adj in _ADJACENT.get(t, []):
            if adj not in seen:
                result.append(adj)
                seen.add(adj)
    return result[:6]


# ── Feed strategies ────────────────────────────────────────────────────────────
class FeedStrategy(str, Enum):
    MY_FIELDS    = "my_fields"
    EMERGING     = "emerging"
    BROADEN      = "broaden"


def load_feed(
    topic: str,
    strategy: FeedStrategy = FeedStrategy.MY_FIELDS,
    subtopics: list | None = None,
    prefs: UserPrefs | None = None,
    discover_prefs: list | None = None,
    force_refresh: bool = False,
) -> list:
    """Load articles for a single topic using the given strategy.

    Checks SQLite cache first (30-min TTL) unless force_refresh.
    Falls back gracefully if any provider fails.
    """
    if prefs is None:
        prefs = get_user_prefs()

    if not force_refresh:
        cached = cached_articles(topic, max_age_s=1800)
        if len(cached) >= 5:
            ranked = adaptive_rank(cached, prefs)
            return ranked

    queries = generate_queries(topic, subtopics, discover_prefs)
    raw: list = []

    for q in queries:
        # My Fields → all adapters, balance research + news
        if strategy == FeedStrategy.MY_FIELDS:
            raw += fetch_openalex(q, topic, max_items=8)
            raw += fetch_crossref(q, topic, max_items=5)
            raw += fetch_doaj(q, topic, max_items=5)

        # Emerging → recent OpenAlex sorted by publication date, + Crossref
        elif strategy == FeedStrategy.EMERGING:
            raw += fetch_openalex(q, topic, max_items=10, sort="publication_date")
            raw += fetch_crossref(q, topic, max_items=6)

        # Broaden → adjacent topics, lower relevance bar acceptable
        elif strategy == FeedStrategy.BROADEN:
            raw += fetch_openalex(q, topic, max_items=6)
            raw += fetch_europepmc(q, topic, max_items=5)

        # Europe PMC for any biomedical topic in any strategy
        bio_kw = {"health", "medicine", "medical", "clinical", "biology", "pharma",
                  "disease", "public health", "epidemiology", "cancer", "genomics"}
        if any(kw in topic.lower() or kw in q.lower() for kw in bio_kw):
            raw += fetch_europepmc(q, topic, max_items=6)

    # Score, deduplicate, rank
    arts = _deduplicate(raw)
    arts = _score_articles(arts, topic, strategy)
    arts = adaptive_rank(arts, prefs)

    persist_articles(arts)
    return arts


def load_emerging(all_topics: list[str], prefs: UserPrefs | None = None) -> list:
    """Emerging Trends feed — recent publications + trending adjacent topics."""
    if prefs is None:
        prefs = get_user_prefs()

    raw: list = []
    # User topics, recently published
    for topic in all_topics[:4]:
        raw += fetch_openalex(topic, topic, max_items=8, sort="publication_date")

    # Trending topics not in user's list
    for trend_topic in _TREND_TOPICS[:6]:
        if not any(trend_topic.lower() in t.lower() for t in all_topics):
            raw += fetch_openalex(trend_topic, trend_topic, max_items=4, sort="publication_date")

    arts = _deduplicate(raw)
    arts = _score_articles(arts, "emerging", FeedStrategy.EMERGING)
    # Extra freshness sort before personalisation
    arts.sort(key=lambda a: a.get("date", "") or "", reverse=True)
    arts = adaptive_rank(arts[:60], prefs)
    persist_articles(arts)
    return arts


def load_broaden(all_topics: list[str], prefs: UserPrefs | None = None) -> list:
    """Broaden My Knowledge — deliberately outside usual topics."""
    if prefs is None:
        prefs = get_user_prefs()

    adj = _adjacent_topics(all_topics)
    raw: list = []
    for adj_topic in adj:
        raw += fetch_openalex(adj_topic, adj_topic, max_items=6)
        raw += fetch_crossref(adj_topic, adj_topic, max_items=4)

    # Also pull from trending topics
    for trend in _TREND_TOPICS[:4]:
        if not any(trend.lower() in t.lower() for t in all_topics):
            raw += fetch_openalex(trend, trend, max_items=5)

    arts = _deduplicate(raw)
    # For Broaden, keep ALL articles even low-relevance — diversity is the point
    arts = [a for a in arts if a.get("title")]
    arts = adaptive_rank(arts, prefs)
    persist_articles(arts)
    return arts


# ── Relevance scoring ─────────────────────────────────────────────────────────
def _score_articles(articles: list, topic: str, strategy: FeedStrategy) -> list:
    """Assign/update relevance scores. Modifies articles in place."""
    topic_words = set(re.findall(r"\b\w{4,}\b", topic.lower()))
    for art in articles:
        text = f"{art.get('title','')} {art.get('summary','')}".lower()
        text_words = set(re.findall(r"\b\w{4,}\b", text))
        overlap = topic_words & text_words
        score = min(0.6, len(overlap) / max(len(topic_words), 1) * 0.6)

        # Broaden: artificially floor at 0.2 so articles aren't filtered out
        if strategy == FeedStrategy.BROADEN:
            score = max(0.2, score)

        art["relevance"] = round(score, 3)
        art["strategy"] = strategy.value

    return articles


# ── Deduplication ──────────────────────────────────────────────────────────────
def _deduplicate(articles: list) -> list:
    """Remove exact URL duplicates and near-duplicate titles."""
    seen_urls: set = set()
    seen_ids: set = set()
    out: list = []
    for art in articles:
        url = art.get("url", "")
        aid = art.get("id") or _art_id(url)
        if not url or url in seen_urls or aid in seen_ids:
            continue
        seen_urls.add(url)
        seen_ids.add(aid)
        out.append(art)
    return out


# ── Local news classification ──────────────────────────────────────────────────
_GEO_TERMS = {
    "local", "community", "city", "municipal", "district", "town", "village",
    "civic", "mayor", "council", "ward", "constituency", "neighbourhood",
}


def is_local_news(article: dict, city: str, region: str = "") -> bool:
    """Return True if article is genuinely geographically relevant local news."""
    if not city:
        return False
    text = f"{article.get('title','')} {article.get('summary','')}".lower()
    city_l = city.lower()
    region_l = region.lower()

    # Must mention city or region
    city_present = city_l in text or (region_l and region_l in text)
    if not city_present:
        return False

    # Must also contain geo/community signal words
    geo_signal = any(term in text for term in _GEO_TERMS)
    source = article.get("source", "").lower()
    local_source = any(kw in source for kw in [city_l, region_l, "local", "herald",
                                                "times", "post", "news", "journal"])
    return geo_signal or local_source
