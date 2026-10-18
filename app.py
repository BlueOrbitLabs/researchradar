"""
BodhStream — Your Personal Research Intelligence Stream
Type any topic → live articles + credible free sources + AI explanations + bookmarks + connect the dots
"""

import streamlit as st
import feedparser
import requests
import re
import json
import urllib.parse
from datetime import datetime

# ─────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="BodhStream",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
# CSS — mobile-first, responsive
# ─────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 3rem; padding-bottom: 2rem; max-width: 1200px; }

/* ── Brand colours ── */
:root {
    --indigo: #4f46e5;
    --teal:   #0d9488;
    --amber:  #d97706;
    --rose:   #e11d48;
    --slate:  #1e293b;
    --muted:  #64748b;
    --border: #e2e8f0;
    --bg:     #f8fafc;
    --card:   #ffffff;
}

/* ── Header ── */
.bs-header {
    display:flex; align-items:center; gap:12px;
    padding-bottom:14px; border-bottom:2px solid var(--border);
    margin-bottom:16px;
}
.bs-logo {
    width:40px; height:40px; border-radius:10px; flex-shrink:0;
    background:linear-gradient(135deg,var(--indigo),var(--teal));
    display:flex; align-items:center; justify-content:center; font-size:20px;
}
.bs-brand { font-size:1.2rem; font-weight:900; color:var(--slate); letter-spacing:-0.3px; }
.bs-tagline { font-size:0.72rem; color:var(--muted); }
.bs-badge {
    margin-left:auto; background:#ede9fe; color:var(--indigo);
    padding:3px 11px; border-radius:20px; font-size:0.7rem; font-weight:700;
    white-space:nowrap;
}

/* ── Onboarding ── */
.ob-hero { text-align:center; padding:40px 0 24px; }
.ob-hero h1 { font-size:2rem; font-weight:900; color:var(--slate); margin-bottom:8px; }
.ob-hero h1 span { color:var(--indigo); }
.ob-hero p { color:var(--muted); font-size:0.95rem; max-width:500px; margin:0 auto 28px; line-height:1.7; }
.area-card {
    border:2px solid var(--border); border-radius:12px;
    padding:14px 12px; text-align:center; cursor:pointer;
    transition:all 0.15s; background:var(--card);
}
.area-card:hover { border-color:var(--indigo); background:#ede9fe; }
.area-card.selected { border-color:var(--indigo); background:#ede9fe; }
.area-icon { font-size:1.8rem; margin-bottom:4px; }
.area-name { font-size:0.8rem; font-weight:700; color:var(--slate); }

/* ── Topic chips ── */
.topic-row { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:4px; }
.tc {
    display:inline-block; background:#ede9fe; color:var(--indigo);
    border:1.5px solid rgba(79,70,229,0.2); border-radius:20px;
    padding:4px 11px; font-size:0.74rem; font-weight:600;
}

/* ── Article card ── */
.art-card {
    background:var(--card); border:1.5px solid var(--border);
    border-radius:12px; padding:13px 15px; margin-bottom:10px;
}
.art-source { font-size:0.68rem; font-weight:700; color:var(--indigo); margin-bottom:2px; }
.art-title { font-size:0.92rem; font-weight:700; color:var(--slate); line-height:1.4; margin-bottom:4px; }
.art-title a { color:var(--slate); text-decoration:none; }
.art-title a:hover { color:var(--indigo); }
.art-meta { font-size:0.68rem; color:#94a3b8; margin-bottom:6px; }
.art-summary { font-size:0.81rem; color:#475569; line-height:1.55; }

/* ── Source card ── */
.src-card {
    background:var(--card); border:1.5px solid var(--border);
    border-radius:10px; padding:12px 13px; margin-bottom:8px;
    display:flex; gap:10px; align-items:flex-start;
}
.src-icon {
    width:32px; height:32px; border-radius:7px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center;
    font-size:15px; background:var(--bg);
}
.src-name a { font-size:0.87rem; font-weight:700; color:var(--slate); text-decoration:none; }
.src-name a:hover { color:var(--indigo); }
.src-type {
    font-size:0.62rem; font-weight:700; text-transform:uppercase;
    letter-spacing:0.07em; color:var(--teal); background:#ccfbf1;
    padding:2px 6px; border-radius:3px; margin-left:5px;
}
.src-free { font-size:0.62rem; font-weight:700; color:#059669; background:#d1fae5; padding:2px 6px; border-radius:3px; }
.src-desc { font-size:0.78rem; color:var(--muted); line-height:1.5; margin-top:3px; }

/* ── Bookmark card ── */
.bm-card {
    background:var(--card); border:1.5px solid var(--border);
    border-radius:10px; padding:12px 14px; margin-bottom:8px;
    border-left:4px solid var(--indigo);
}
.bm-cat {
    display:inline-block; font-size:0.63rem; font-weight:700;
    text-transform:uppercase; letter-spacing:0.06em;
    background:#fef3c7; color:var(--amber);
    padding:2px 7px; border-radius:3px; margin-bottom:4px;
}
.bm-title { font-size:0.9rem; font-weight:700; color:var(--slate); line-height:1.4; margin-bottom:3px; }
.bm-title a { color:var(--slate); text-decoration:none; }
.bm-title a:hover { color:var(--indigo); }
.bm-meta { font-size:0.67rem; color:#94a3b8; }

/* ── KA panel ── */
.ka-header {
    background:#ede9fe; border-radius:10px;
    padding:10px 13px; margin-bottom:12px;
}
.ka-label { font-size:0.65rem; font-weight:700; color:var(--indigo); text-transform:uppercase; letter-spacing:0.07em; }
.ka-title { font-size:0.88rem; font-weight:700; color:var(--slate); line-height:1.4; margin-top:2px; }
.section-label {
    display:inline-block; background:#ede9fe; color:var(--indigo);
    font-size:0.65rem; font-weight:800; text-transform:uppercase;
    letter-spacing:0.08em; padding:3px 8px; border-radius:4px;
    margin-bottom:5px; margin-top:8px;
}
.section-label:first-child { margin-top:0; }
.chat-user {
    background:var(--indigo); color:white;
    padding:8px 12px; border-radius:12px 12px 3px 12px;
    font-size:0.82rem; line-height:1.5; margin:5px 0; margin-left:12%;
}
.chat-ai {
    background:var(--card); color:var(--slate); border:1px solid var(--border);
    padding:8px 12px; border-radius:12px 12px 12px 3px;
    font-size:0.82rem; line-height:1.6; margin:5px 0; margin-right:4%;
}

/* ── Connect the Dots ── */
.ctd-card {
    background:linear-gradient(135deg,#ede9fe,#ccfbf1);
    border:1.5px solid rgba(79,70,229,0.2);
    border-radius:12px; padding:16px; margin-bottom:12px;
}
.ctd-section { font-size:0.78rem; color:var(--slate); line-height:1.6; }

/* ── Empty states ── */
.empty-state { text-align:center; padding:40px 16px; color:var(--muted); }
.empty-state .icon { font-size:2.5rem; margin-bottom:10px; }
.empty-state h3 { font-size:0.95rem; font-weight:600; color:#475569; margin-bottom:5px; }
.empty-state p { font-size:0.82rem; line-height:1.6; max-width:300px; margin:0 auto; }

/* ── Responsive ── */
@media (max-width: 768px) {
    .block-container { padding-left:0.8rem; padding-right:0.8rem; }
    .ob-hero h1 { font-size:1.5rem; }
    .bs-tagline { display:none; }
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
DEFAULTS = {
    "onboarded": False,
    "user_name": "",
    "selected_areas": [],
    "topics": [],
    "active_topic": None,
    "sources_cache": {},
    "followed_sources": [],       # list of source dicts user has followed
    "selected_article": None,
    "explanation": None,
    "chat_history": [],
    "bookmarks": [],              # list of {article, category, note, saved_at}
    "dots_analysis": None,
    "gemini_key": "",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.gemini_key:
    try:
        st.session_state.gemini_key = st.secrets.get("GEMINI_KEY", "")
    except Exception:
        pass

# ─────────────────────────────────────────────
# Area → seed topics map
# ─────────────────────────────────────────────
AREAS = {
    "🏥 Health & Medicine":       ["Public health", "Mental health", "Nutrition science", "Global health policy"],
    "🔬 Science & Research":      ["Climate science", "Biotechnology", "Neuroscience", "Quantum computing"],
    "💹 Economics & Finance":     ["Health economics", "Development economics", "Behavioural economics", "Monetary policy"],
    "💻 Technology & AI":         ["Artificial intelligence", "Machine learning", "Cybersecurity", "Data science"],
    "⚖️ Law & Policy":            ["Public policy", "Health law", "International law", "Human rights"],
    "📚 History & Culture":       ["Ancient history", "Cultural anthropology", "Philosophy", "Sociology"],
    "🌍 Climate & Environment":   ["Climate adaptation", "Biodiversity", "Sustainable development", "Environmental policy"],
    "🧠 Psychology & Behaviour":  ["Behavioural science", "Cognitive psychology", "Social psychology", "Positive psychology"],
    "📰 Current Affairs":         ["India news", "Global affairs", "Science news", "Technology news"],
    "🎓 Education & Academia":    ["Higher education", "Research methods", "Learning science", "Education policy"],
}

CATEGORY_COLORS = {
    "⭐ Important":    "#fef3c7",
    "📚 To Read":      "#dbeafe",
    "🔬 For Research": "#dcfce7",
    "🎓 For Teaching": "#ede9fe",
    "📌 Reference":    "#ffe4e6",
    "💡 Insight":      "#fef9c3",
}
CATEGORIES = list(CATEGORY_COLORS.keys())

# ─────────────────────────────────────────────
# Gemini
# ─────────────────────────────────────────────
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={}"

def _gemini_raw(prompt: str, history=None, system: str = "", max_tokens=1800) -> str:
    key = st.session_state.gemini_key
    if not key:
        return ""
    url = GEMINI_URL.format(key)
    contents = list(history or []) + [{"role": "user", "parts": [{"text": prompt}]}]
    body = {
        "contents": contents,
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    try:
        r = requests.post(url, json=body, timeout=35)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        try:
            return f"ERROR: {r.json().get('error', {}).get('message', str(e))}"
        except Exception:
            return f"ERROR: {e}"

# ─────────────────────────────────────────────
# Feed building
# ─────────────────────────────────────────────
HEALTH_KW  = {"health","medicine","medical","clinical","disease","drug","nutrition","epidemi",
               "public health","dentist","dental","oral","cancer","pharmacy","covid","mental",
               "nursing","patient","hospital","vaccine","global health","ncd","hta"}
SCIENCE_KW = {"physics","chemistry","biology","math","mathematics","astronomy","geology",
               "neuroscience","quantum","ecology","botany","zoology","genetics","climate",
               "material","nano","biotech","biochem"}
CS_KW      = {"computer","machine learning","artificial intelligence","deep learning","nlp",
               "algorithm","software","data science","robotics","cybersecurity","blockchain"}
ECON_KW    = {"economics","econom","finance","market","trade","fiscal","monetary","gdp",
               "inflation","poverty","development","inequality","behavioural economics"}

def topic_to_feeds(topic: str):
    q  = urllib.parse.quote_plus(topic)
    tl = topic.lower()
    feeds = [
        ("Google News",        f"https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"),
        ("Google News (India)", f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"),
    ]
    if any(kw in tl for kw in HEALTH_KW):
        feeds.append(("PubMed",
            f"https://pubmed.ncbi.nlm.nih.gov/rss/search/?term={q}&limit=15&api_key=e1818779c1e90fbafc339def7e176689c308"))
    if any(kw in tl for kw in SCIENCE_KW):
        if any(k in tl for k in ("physics","quantum","astro")):
            feeds.append(("ArXiv Physics", "https://arxiv.org/rss/physics"))
        if any(k in tl for k in ("chem","material")):
            feeds.append(("ArXiv Chem", "https://arxiv.org/rss/cond-mat"))
        if any(k in tl for k in ("bio","genetic","neuro")):
            feeds.append(("ArXiv Biology", "https://arxiv.org/rss/q-bio"))
        if any(k in tl for k in ("climate","ecolog","environ")):
            feeds.append(("Nature Climate", "https://www.nature.com/nclimate.rss"))
    if any(kw in tl for kw in CS_KW):
        feeds.append(("ArXiv CS/AI", "https://arxiv.org/rss/cs.AI"))
        feeds.append(("ArXiv ML",    "https://arxiv.org/rss/cs.LG"))
    if any(kw in tl for kw in ECON_KW):
        feeds.append(("NBER",      "https://feeds.feedburner.com/nber/new"))
        feeds.append(("ArXiv Econ","https://arxiv.org/rss/econ"))
    return feeds

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_feed(url: str, label: str, topic: str):
    try:
        r    = requests.get(url, headers={"User-Agent": "BodhStream/1.0"}, timeout=10)
        feed = feedparser.parse(r.content)
        arts = []
        for e in feed.entries[:8]:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            date_str = ""
            if pub:
                try: date_str = datetime(*pub[:6]).strftime("%d %b %Y")
                except: pass
            summary = re.sub(r"<[^>]+>", "", e.get("summary","")).strip()[:280]
            arts.append({
                "title":   e.get("title","Untitled").strip(),
                "url":     e.get("link",""),
                "summary": summary,
                "date":    date_str,
                "source":  label,
                "topic":   topic,
            })
        return arts
    except Exception:
        return []

def load_topic_articles(topic: str):
    feeds = topic_to_feeds(topic)
    all_arts, seen = [], set()
    for label, url in feeds:
        for art in fetch_feed(url, label, topic):
            key = art["title"][:55].lower()
            if key not in seen and art["title"] != "Untitled":
                seen.add(key); all_arts.append(art)
    return all_arts

# ─────────────────────────────────────────────
# Gemini: free sources
# ─────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def get_free_sources(topic: str, gemini_key: str) -> list:
    if not gemini_key: return []
    prompt = f"""List the top credible and FREELY accessible sources for research on: "{topic}"

STRICT RULE: Only sources that are 100% free to read — no paywalls, no subscriptions.
Include open-access journals, free databases, government sites, reputable free magazines, preprint servers.

Return raw JSON only (no markdown fences):
[
  {{
    "name": "Source Name",
    "url": "https://...",
    "type": "Journal|Magazine|Database|Website|Preprint Server|News",
    "icon": "single emoji",
    "description": "one sentence about what it covers and why useful",
    "access": "Open Access|Free to Read|Government|Preprint"
  }}
]
Return 8–12 sources. Only real working URLs. No duplicates."""
    body = {
        "contents": [{"role":"user","parts":[{"text":prompt}]}],
        "generationConfig": {"temperature":0.3,"maxOutputTokens":1200},
    }
    try:
        r   = requests.post(GEMINI_URL.format(gemini_key), json=body, timeout=25)
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        raw = re.sub(r"```json\s*","",raw); raw = re.sub(r"```\s*","",raw)
        src = json.loads(raw.strip())
        return src if isinstance(src, list) else []
    except Exception:
        return []

# ─────────────────────────────────────────────
# KA helpers
# ─────────────────────────────────────────────
def build_explain_prompt(title, url, summary):
    return f"""Explain this article deeply for a researcher or curious professional.

Title: "{title}"
{f"URL: {url}" if url else ""}
{f"Snippet: {summary[:500]}" if summary else ""}

Use this exact structure:

## 📌 What Is This?
[2–3 sentences — plain language, core topic and finding]

## 🕰️ Historical Background
[3–5 key milestones — origin, who pioneered it, how it evolved]

## 📊 Current Evidence & State
[Key findings, consensus, debates happening now]

## 🔮 What's Next
[Emerging trends, open questions, future directions]

## 💡 Why It Matters
[Practical significance — who should care and why — 2 sentences]

## 🔗 Key Terms
[5 bullet points — important terms/acronyms with one-line definitions]

End with exactly:
SUGGESTIONS: question1? | question2? | question3?"""

def parse_explanation(text):
    followups = []
    if "SUGGESTIONS:" in text:
        parts    = text.split("SUGGESTIONS:")
        text     = parts[0].strip()
        followups = [q.strip() for q in parts[1].split("|") if "?" in q][:3]
    sections, label, lines = [], None, []
    for line in text.split("\n"):
        if line.startswith("## "):
            if label: sections.append((label, "\n".join(lines).strip()))
            label, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if label: sections.append((label, "\n".join(lines).strip()))
    return sections, followups

def render_section_content(content):
    lines = content.split("\n")
    buf, in_list = [], False
    for line in lines:
        line = line.strip()
        is_b = re.match(r'^[\-\*•]\s+', line)
        is_n = re.match(r'^\d+\.\s+', line)
        clean = re.sub(r'^[\-\*•\d\.]\s+','',line)
        if is_b or is_n:
            if not in_list:
                if buf: st.markdown(" ".join(buf)); buf=[]
                in_list=True
            buf.append(f"- {clean}")
        else:
            if in_list:
                st.markdown("\n".join(buf)); buf=[]; in_list=False
            if clean: buf.append(clean)
    if buf:
        st.markdown("\n".join(buf) if in_list else " ".join(buf))

# ─────────────────────────────────────────────
# Connect the Dots
# ─────────────────────────────────────────────
def build_dots_prompt():
    bms = st.session_state.bookmarks
    lines = []
    for i, bm in enumerate(bms[:20]):
        art = bm["article"]
        lines.append(f"{i+1}. [{art['topic']}] {art['title']}")
        if art.get("summary"):
            lines.append(f"   → {art['summary'][:150]}")
    articles_text = "\n".join(lines)
    return f"""You are a research intelligence assistant. Analyse these bookmarked articles and synthesise the knowledge across them.

ARTICLES:
{articles_text}

Provide a deep synthesis using this structure:

## 🔴 Common Themes
[3–4 threads that run through multiple articles — what keeps coming up?]

## ⚡ Surprising Connections
[Non-obvious links between different topic areas — what would most readers miss?]

## 🕳️ Knowledge Gaps
[What important questions do these articles raise but leave unanswered?]

## 🔮 Where This Is Heading
[Based on what you're reading, what directions are emerging in this field/these fields?]

## 📚 What to Read Next
[5 specific books, papers, or sources that would deepen understanding — free/open access preferred]

Be specific, not generic. Reference the actual articles where possible."""

# ─────────────────────────────────────────────
# Bookmark helpers
# ─────────────────────────────────────────────
def is_bookmarked(art):
    return any(bm["article"]["url"] == art["url"] for bm in st.session_state.bookmarks)

def add_bookmark(art, category):
    if not is_bookmarked(art):
        st.session_state.bookmarks.append({
            "article":  art,
            "category": category,
            "saved_at": datetime.now().strftime("%d %b %Y"),
        })

def remove_bookmark(url):
    st.session_state.bookmarks = [b for b in st.session_state.bookmarks if b["article"]["url"] != url]

def export_bookmarks():
    return json.dumps([
        {"title": b["article"]["title"], "url": b["article"]["url"],
         "source": b["article"]["source"], "topic": b["article"]["topic"],
         "category": b["category"], "saved_at": b["saved_at"]}
        for b in st.session_state.bookmarks
    ], indent=2)

# ─────────────────────────────────────────────
# ══════════════ ONBOARDING ══════════════
# ─────────────────────────────────────────────
if not st.session_state.onboarded:
    st.markdown("""
    <div class="ob-hero">
        <div style="font-size:3rem;margin-bottom:10px;">🔮</div>
        <h1>Welcome to <span>BodhStream</span></h1>
        <p>Your personal research intelligence stream.<br>
        Live articles · credible free sources · AI explanations · bookmark & connect ideas.</p>
    </div>
    """, unsafe_allow_html=True)

    name = st.text_input("What's your name?", placeholder="e.g. Dr. Priya, Arjun, Sana…",
                         label_visibility="visible")

    st.markdown("**Pick your areas of interest** — we'll suggest starter topics:")
    area_keys = list(AREAS.keys())
    # 5-column grid
    rows = [area_keys[i:i+5] for i in range(0, len(area_keys), 5)]
    for row in rows:
        cols = st.columns(len(row))
        for col, area in zip(cols, row):
            with col:
                selected = area in st.session_state.selected_areas
                if st.button(area, key=f"area_{area}", use_container_width=True,
                             type="primary" if selected else "secondary"):
                    if selected:
                        st.session_state.selected_areas.remove(area)
                    else:
                        st.session_state.selected_areas.append(area)
                    st.rerun()

    if st.session_state.selected_areas:
        st.markdown("**Suggested starter topics from your areas:**")
        suggested = []
        for area in st.session_state.selected_areas:
            suggested.extend(AREAS[area])
        suggested = list(dict.fromkeys(suggested))  # dedupe

        sel_cols = st.columns(min(len(suggested), 4))
        for i, topic in enumerate(suggested[:8]):
            with sel_cols[i % 4]:
                checked = topic in st.session_state.topics
                if st.checkbox(topic, value=checked, key=f"sug_{topic}"):
                    if topic not in st.session_state.topics:
                        st.session_state.topics.append(topic)
                else:
                    if topic in st.session_state.topics:
                        st.session_state.topics.remove(topic)

    st.markdown("---")
    start_disabled = not (name.strip() and st.session_state.topics)
    if st.button("🚀 Start Exploring →", type="primary", use_container_width=True,
                 disabled=start_disabled):
        st.session_state.user_name   = name.strip()
        st.session_state.onboarded   = True
        st.session_state.active_topic = st.session_state.topics[0]
        st.rerun()

    if not name.strip():
        st.caption("Enter your name and select at least one topic to continue.")
    elif not st.session_state.topics:
        st.caption("Select at least one topic to continue.")
    st.stop()

# ─────────────────────────────────────────────
# ══════════════ MAIN APP ══════════════
# ─────────────────────────────────────────────

# ── Header ──
st.markdown(f"""
<div class="bs-header">
    <div class="bs-logo">🔮</div>
    <div>
        <div class="bs-brand">BodhStream</div>
        <div class="bs-tagline">Welcome back, {st.session_state.user_name} · your research stream</div>
    </div>
    <div class="bs-badge">✦ Gemini AI</div>
</div>
""", unsafe_allow_html=True)

# ── Topic input bar ──
ti_col, btn_col = st.columns([5, 1])
with ti_col:
    new_topic = st.text_input("Add topic", placeholder="Type any topic — 'CRISPR', 'health economics India', 'Byzantine history'…",
                              label_visibility="collapsed", key="topic_input")
with btn_col:
    add_pressed = st.button("+ Add", use_container_width=True, type="primary")

if add_pressed and new_topic.strip():
    t = new_topic.strip()
    if t not in st.session_state.topics:
        st.session_state.topics.append(t)
    st.session_state.active_topic     = t
    st.session_state.selected_article = None
    st.session_state.explanation      = None
    st.session_state.chat_history     = []
    st.rerun()

# ── My Topics bar ──
if st.session_state.topics:
    st.markdown("**My Topics:**")
    n = len(st.session_state.topics)
    chip_cols = st.columns(min(n, 6))
    for i, topic in enumerate(st.session_state.topics):
        with chip_cols[i % 6]:
            is_active = topic == st.session_state.active_topic
            lbl = f"✓ {topic}" if is_active else topic
            if st.button(lbl, key=f"tp_{i}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state.active_topic     = topic
                st.session_state.selected_article = None
                st.session_state.explanation      = None
                st.session_state.chat_history     = []
                st.rerun()

    with st.expander("⚙ Manage topics · settings"):
        rm = st.selectbox("Remove a topic", ["— select —"] + st.session_state.topics, key="rm_topic")
        if st.button("Remove topic") and rm != "— select —":
            st.session_state.topics.remove(rm)
            if st.session_state.active_topic == rm:
                st.session_state.active_topic = st.session_state.topics[0] if st.session_state.topics else None
            st.rerun()

        key_val = st.text_input("Gemini API Key", value=st.session_state.gemini_key,
                                type="password", label_visibility="visible")
        if key_val != st.session_state.gemini_key:
            st.session_state.gemini_key = key_val
            st.success("Key saved!")

    st.markdown("---")

# ── No topic guard ──
if not st.session_state.active_topic:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">🔮</div>
        <h3>What do you want to explore?</h3>
        <p>Type any topic above to start your stream.</p>
    </div>""", unsafe_allow_html=True)
    st.stop()

active = st.session_state.active_topic
st.markdown(f"### 📍 {active}")

# ─────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────
bm_count  = len(st.session_state.bookmarks)
bm_label  = f"🔖 Saved ({bm_count})" if bm_count else "🔖 Saved"
tab_feed, tab_sources, tab_saved, tab_ka = st.tabs(
    ["📰 Feed", "🔗 Sources", bm_label, "📡 Knowledge AI"]
)

# ════════════════════════════
# TAB 1 — FEED
# ════════════════════════════
with tab_feed:
    ref_col, _ = st.columns([1, 4])
    with ref_col:
        if st.button("🔄 Refresh", key="ref_feed"):
            fetch_feed.clear(); st.rerun()

    with st.spinner("Fetching articles…"):
        articles = load_topic_articles(active)

    if not articles:
        st.warning("No articles right now. Try refreshing.")
    else:
        st.caption(f"{len(articles)} articles · refreshes every 30 min")
        for i, art in enumerate(articles[:30]):
            summary_html = (f'<div class="art-summary">{art["summary"][:200]}{"…" if len(art["summary"])>200 else ""}</div>'
                            if art["summary"] else "")
            st.markdown(f"""
            <div class="art-card">
                <div class="art-source">{art['source']}</div>
                <div class="art-title"><a href="{art['url']}" target="_blank">{art['title']}</a></div>
                <div class="art-meta">📅 {art['date'] or 'Recent'}</div>
                {summary_html}
            </div>""", unsafe_allow_html=True)

            a_col, b_col = st.columns([2, 1])
            with a_col:
                if st.button("📡 Explain with AI", key=f"exp_{active[:6]}_{i}"):
                    st.session_state.selected_article = art
                    st.session_state.explanation      = None
                    st.session_state.chat_history     = []
                    with st.spinner("Generating explanation…"):
                        prompt = build_explain_prompt(art["title"], art["url"], art["summary"])
                        result = _gemini_raw(prompt, system=(
                            "You are a research knowledge assistant. Explain topics deeply "
                            "and clearly for academics, researchers, and curious professionals."
                        ))
                        st.session_state.explanation = result
                        st.session_state.chat_history = [
                            {"role":"user","parts":[{"text":prompt}]},
                            {"role":"model","parts":[{"text":result}]},
                        ]
                    st.rerun()

            with b_col:
                if is_bookmarked(art):
                    if st.button("✓ Saved", key=f"bm_{i}", use_container_width=True):
                        remove_bookmark(art["url"]); st.rerun()
                else:
                    with st.popover("🔖 Save", use_container_width=True):
                        st.markdown("**Save to:**")
                        for cat in CATEGORIES:
                            if st.button(cat, key=f"cat_{i}_{cat}", use_container_width=True):
                                add_bookmark(art, cat); st.rerun()

# ════════════════════════════
# TAB 2 — SOURCES
# ════════════════════════════
with tab_sources:
    st.markdown("**Free credible sources to follow** — journals, databases, magazines · all open access")

    if active not in st.session_state.sources_cache:
        with st.spinner("Finding best free sources with AI…"):
            sources = get_free_sources(active, st.session_state.gemini_key)
            st.session_state.sources_cache[active] = sources

    sources = st.session_state.sources_cache.get(active, [])

    if not sources:
        st.info("Add your Gemini API key in Settings to see AI-curated sources.")
    else:
        for src in sources:
            name   = src.get("name","")
            url    = src.get("url","#")
            stype  = src.get("type","")
            icon   = src.get("icon","📄")
            desc   = src.get("description","")
            access = src.get("access","Free")

            already_followed = any(s.get("url") == url for s in st.session_state.followed_sources)

            st.markdown(f"""
            <div class="src-card">
                <div class="src-icon">{icon}</div>
                <div style="flex:1;min-width:0;">
                    <div class="src-name">
                        <a href="{url}" target="_blank">{name}</a>
                        <span class="src-type">{stype}</span>
                    </div>
                    <div style="margin-top:3px;">
                        <span class="src-free">✓ {access}</span>
                    </div>
                    <div class="src-desc">{desc}</div>
                </div>
            </div>""", unsafe_allow_html=True)

            if already_followed:
                if st.button(f"✓ Following", key=f"flw_{url[:20]}", use_container_width=False):
                    st.session_state.followed_sources = [
                        s for s in st.session_state.followed_sources if s.get("url") != url
                    ]
                    st.rerun()
            else:
                if st.button(f"+ Follow {name}", key=f"flw_{url[:20]}", use_container_width=False):
                    st.session_state.followed_sources.append(src); st.rerun()

    rs_col, _ = st.columns([1, 3])
    with rs_col:
        if st.button("🔄 Refresh Sources"):
            if active in st.session_state.sources_cache:
                del st.session_state.sources_cache[active]
            get_free_sources.clear(); st.rerun()

    # Followed sources library
    if st.session_state.followed_sources:
        st.markdown("---")
        st.markdown(f"**📚 My Source Library** — {len(st.session_state.followed_sources)} sources saved")
        for src in st.session_state.followed_sources:
            st.markdown(f"""
            <div class="src-card">
                <div class="src-icon">{src.get('icon','📄')}</div>
                <div>
                    <div class="src-name"><a href="{src.get('url','#')}" target="_blank">{src.get('name','')}</a>
                    <span class="src-type">{src.get('type','')}</span></div>
                    <div class="src-desc">{src.get('description','')}</div>
                </div>
            </div>""", unsafe_allow_html=True)

# ════════════════════════════
# TAB 3 — SAVED / BOOKMARKS
# ════════════════════════════
with tab_saved:
    if not st.session_state.bookmarks:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">🔖</div>
            <h3>Nothing saved yet</h3>
            <p>Click "🔖 Save" on any article in the Feed tab to bookmark it here.</p>
        </div>""", unsafe_allow_html=True)
    else:
        # Filter by category
        all_cats = list(dict.fromkeys(b["category"] for b in st.session_state.bookmarks))
        filter_cat = st.selectbox("Filter by category", ["All"] + all_cats, key="bm_filter")

        bms = st.session_state.bookmarks
        if filter_cat != "All":
            bms = [b for b in bms if b["category"] == filter_cat]

        st.caption(f"{len(bms)} bookmarks")

        for bm in bms:
            art = bm["article"]
            bg  = CATEGORY_COLORS.get(bm["category"], "#f0f4f8")
            st.markdown(f"""
            <div class="bm-card" style="border-left-color:{bg};">
                <span class="bm-cat">{bm['category']}</span>
                <div class="bm-title"><a href="{art['url']}" target="_blank">{art['title']}</a></div>
                <div class="bm-meta">{art['source']} · {art['topic']} · saved {bm['saved_at']}</div>
            </div>""", unsafe_allow_html=True)

            rc_col, e_col, del_col = st.columns([2, 2, 1])
            with rc_col:
                new_cat = st.selectbox("Recategorise", CATEGORIES,
                                       index=CATEGORIES.index(bm["category"]) if bm["category"] in CATEGORIES else 0,
                                       key=f"rc_{art['url'][:20]}", label_visibility="collapsed")
                if new_cat != bm["category"]:
                    bm["category"] = new_cat; st.rerun()
            with e_col:
                if st.button("📡 Explain", key=f"bm_exp_{art['url'][:20]}", use_container_width=True):
                    st.session_state.selected_article = art
                    st.session_state.explanation      = None
                    st.session_state.chat_history     = []
                    with st.spinner("Generating explanation…"):
                        prompt = build_explain_prompt(art["title"], art["url"], art["summary"])
                        result = _gemini_raw(prompt, system=(
                            "You are a research knowledge assistant. Explain topics deeply "
                            "and clearly for academics, researchers, and curious professionals."
                        ))
                        st.session_state.explanation = result
                        st.session_state.chat_history = [
                            {"role":"user","parts":[{"text":prompt}]},
                            {"role":"model","parts":[{"text":result}]},
                        ]
                    st.rerun()
            with del_col:
                if st.button("🗑", key=f"del_{art['url'][:20]}", use_container_width=True):
                    remove_bookmark(art["url"]); st.rerun()

        st.markdown("---")
        # Export
        if st.download_button("⬇ Export bookmarks (JSON)",
                               data=export_bookmarks(),
                               file_name="bodhstream_bookmarks.json",
                               mime="application/json"):
            pass

        # ── Connect the Dots ──
        st.markdown("---")
        st.markdown("### 🔗 Connect the Dots")
        st.caption("Let AI find patterns, connections and gaps across all your saved articles.")
        if len(st.session_state.bookmarks) < 3:
            st.info("Save at least 3 articles to use Connect the Dots.")
        else:
            if st.button("✨ Connect the Dots", type="primary", use_container_width=True):
                with st.spinner("Analysing your reading across topics…"):
                    prompt = build_dots_prompt()
                    result = _gemini_raw(prompt, system=(
                        "You are a senior research intelligence analyst. Find non-obvious connections "
                        "and synthesise knowledge across interdisciplinary reading."
                    ), max_tokens=2000)
                    st.session_state.dots_analysis = result

            if st.session_state.dots_analysis:
                sections = []
                label_d, lines_d = None, []
                for line in st.session_state.dots_analysis.split("\n"):
                    if line.startswith("## "):
                        if label_d: sections.append((label_d, "\n".join(lines_d).strip()))
                        label_d, lines_d = line[3:].strip(), []
                    else:
                        lines_d.append(line)
                if label_d: sections.append((label_d, "\n".join(lines_d).strip()))

                for lbl, content in sections:
                    st.markdown(f'<div class="section-label">{lbl}</div>', unsafe_allow_html=True)
                    render_section_content(content)
                    st.markdown("---")

# ════════════════════════════
# TAB 4 — KNOWLEDGE AI
# ════════════════════════════
with tab_ka:
    if not st.session_state.selected_article:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">📡</div>
            <h3>Click "Explain with AI" on any article</h3>
            <p>Get a deep breakdown — what it is, historical background, current evidence, what's next.<br><br>
            Then ask anything in a live chat.</p>
        </div>""", unsafe_allow_html=True)
    else:
        art = st.session_state.selected_article
        st.markdown(f"""
        <div class="ka-header">
            <div class="ka-label">Now Explaining</div>
            <div class="ka-title">{art['title']}</div>
            <div style="font-size:0.68rem;color:#64748b;margin-top:3px;">{art['source']} · {art['topic']}</div>
        </div>""", unsafe_allow_html=True)

        if st.session_state.explanation:
            sections, followups = parse_explanation(st.session_state.explanation)
            for lbl, content in sections:
                st.markdown(f'<div class="section-label">{lbl}</div>', unsafe_allow_html=True)
                render_section_content(content)
                st.markdown("---")

            if followups:
                st.markdown("**💬 Suggested follow-ups:**")
                for j, q in enumerate(followups):
                    if st.button(q, key=f"chip_{j}_{art['title'][:8]}", use_container_width=True):
                        st.session_state.chat_history.append({"role":"user","parts":[{"text":q}]})
                        with st.spinner("Thinking…"):
                            resp = _gemini_raw(q, history=st.session_state.chat_history[:-1])
                        st.session_state.chat_history.append({"role":"model","parts":[{"text":resp}]})
                        st.rerun()

        # Chat history (skip first 2 — prompt/response pair)
        for msg in st.session_state.chat_history[2:]:
            role = msg["role"]
            text = msg["parts"][0]["text"]
            txt_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text).replace("\n","<br>")
            css = "chat-user" if role == "user" else "chat-ai"
            st.markdown(f'<div class="{css}">{txt_html}</div>', unsafe_allow_html=True)

        st.markdown("---")
        fu_input = st.text_input("Ask anything about this topic",
                                  placeholder="e.g. How does this apply in low-income countries?",
                                  label_visibility="collapsed",
                                  key=f"fu_{art['title'][:12]}")
        ask_c, clr_c = st.columns([3, 1])
        with ask_c:
            if st.button("Ask →", use_container_width=True, key="ask_btn"):
                q = fu_input.strip()
                if q:
                    st.session_state.chat_history.append({"role":"user","parts":[{"text":q}]})
                    with st.spinner("Thinking…"):
                        resp = _gemini_raw(q, history=st.session_state.chat_history[:-1])
                    st.session_state.chat_history.append({"role":"model","parts":[{"text":resp}]})
                    st.rerun()
        with clr_c:
            if st.button("🗑 Clear", key="clr_chat", use_container_width=True):
                st.session_state.chat_history = st.session_state.chat_history[:2]
                st.rerun()
