"""Persistence repository layer for Owlume.

This module provides a data-access abstraction over Supabase. When Supabase is
not configured (no credentials), all functions fall back to session_state or
return empty results. This ensures the app works in both local development and
production without crashing.

The repository pattern keeps SQL/Supabase calls out of the UI code. Each
function accepts a user_id and operates only on that user's data (enforced
by RLS when Supabase is used).

Authentication is required for persistent writes. Without a valid user_id,
functions operate on session_state only (ephemeral).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("owlume.persistence")

# ── Supabase client (lazy, optional) ──────────────────────────────────────────

_supabase_client = None


def _get_client():
    """Return the Supabase client if configured, else None."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "") if hasattr(st, "secrets") else ""
        key = st.secrets.get("SUPABASE_SERVICE_KEY", "") if hasattr(st, "secrets") else ""
        if url and key:
            from supabase import create_client
            _supabase_client = create_client(url, key)
    except Exception as exc:
        logger.debug("Supabase not available: %s", exc)
        _supabase_client = None
    return _supabase_client


def is_persistent() -> bool:
    """Return True if Supabase is configured and reachable."""
    return _get_client() is not None


# ── Authentication ───────────────────────────────────────────────────────────

def sign_up(email: str, password: str) -> dict:
    """Register a new user. Returns {success, user_id, error}."""
    client = _get_client()
    if not client:
        return {"success": False, "user_id": None, "error": "Supabase not configured"}
    try:
        resp = client.auth.sign_up({"email": email, "password": password})
        if resp.user:
            return {"success": True, "user_id": str(resp.user.id), "error": None}
        return {"success": False, "user_id": None, "error": "Registration failed"}
    except Exception as exc:
        logger.warning("Sign up failed: %s", exc)
        return {"success": False, "user_id": None, "error": str(exc)}


def sign_in(email: str, password: str) -> dict:
    """Sign in an existing user. Returns {success, user_id, error}."""
    client = _get_client()
    if not client:
        return {"success": False, "user_id": None, "error": "Supabase not configured"}
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
        if resp.user:
            return {"success": True, "user_id": str(resp.user.id), "error": None}
        return {"success": False, "user_id": None, "error": "Invalid credentials"}
    except Exception as exc:
        logger.warning("Sign in failed: %s", exc)
        return {"success": False, "user_id": None, "error": str(exc)}


def sign_out() -> bool:
    """Sign out the current user. Returns True on success."""
    client = _get_client()
    if not client:
        return False
    try:
        client.auth.sign_out()
        return True
    except Exception as exc:
        logger.warning("Sign out failed: %s", exc)
        return False


def get_current_user_id() -> Optional[str]:
    """Return the authenticated user's ID, or None."""
    client = _get_client()
    if not client:
        return None
    try:
        user = client.auth.get_user()
        if user and user.user:
            return str(user.user.id)
    except Exception:
        pass
    return None


def get_current_user_email() -> Optional[str]:
    """Return the authenticated user's email, or None."""
    client = _get_client()
    if not client:
        return None
    try:
        user = client.auth.get_user()
        if user and user.user:
            return user.user.email
    except Exception:
        pass
    return None


# ── Bookmarks ─────────────────────────────────────────────────────────────────

def load_bookmarks(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load bookmarks for a user. Returns [] if no client or user_id."""
    client = _get_client()
    if not client or not user_id:
        return []
    try:
        resp = client.table("bookmarks").select("*").eq("user_id", user_id).execute()
        return resp.data or []
    except Exception as exc:
        logger.warning("Failed to load bookmarks: %s", exc)
        return []


def save_bookmark(user_id: Optional[str], article: Dict[str, Any],
                  category: str = "Read later") -> bool:
    """Save a bookmark. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("bookmarks").upsert({
            "user_id": user_id,
            "article_url": article.get("url", ""),
            "article_title": article.get("title", ""),
            "article_source": article.get("source", ""),
            "article_topic": article.get("topic", ""),
            "article_summary": (article.get("summary") or "")[:200],
            "category": category,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save bookmark: %s", exc)
        return False


def remove_bookmark_persistent(user_id: Optional[str], url: str) -> bool:
    """Remove a bookmark. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("bookmarks").delete().eq("user_id", user_id).eq("article_url", url).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to remove bookmark: %s", exc)
        return False


# ── Followed sources ──────────────────────────────────────────────────────────

def load_followed_sources(user_id: Optional[str] = None) -> set:
    """Load followed sources for a user."""
    client = _get_client()
    if not client or not user_id:
        return set()
    try:
        resp = client.table("followed_sources").select("source_name").eq("user_id", user_id).execute()
        return {r["source_name"] for r in (resp.data or [])}
    except Exception as exc:
        logger.warning("Failed to load followed sources: %s", exc)
        return set()


def follow_source(user_id: Optional[str], source_name: str,
                  source_url: str = "") -> bool:
    """Follow a source. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("followed_sources").upsert({
            "user_id": user_id,
            "source_name": source_name,
            "source_url": source_url,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to follow source: %s", exc)
        return False


def unfollow_source(user_id: Optional[str], source_name: str) -> bool:
    """Unfollow a source. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("followed_sources").delete().eq("user_id", user_id).eq("source_name", source_name).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to unfollow source: %s", exc)
        return False


# ── Interests & preferences ───────────────────────────────────────────────────

def load_interests(user_id: Optional[str] = None) -> List[str]:
    """Load user interests."""
    client = _get_client()
    if not client or not user_id:
        return []
    try:
        resp = client.table("user_interests").select("topic").eq("user_id", user_id).execute()
        return [r["topic"] for r in (resp.data or [])]
    except Exception as exc:
        logger.warning("Failed to load interests: %s", exc)
        return []


def save_interests(user_id: Optional[str], topics: List[str]) -> bool:
    """Save user interests (replace all). Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        # Delete existing
        client.table("user_interests").delete().eq("user_id", user_id).execute()
        # Insert new
        if topics:
            client.table("user_interests").insert([
                {"user_id": user_id, "topic": t} for t in topics
            ]).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save interests: %s", exc)
        return False


def load_preferences(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Load discovery preferences."""
    client = _get_client()
    if not client or not user_id:
        return {"preferences": [], "disabled_subtypes": []}
    try:
        resp = client.table("user_preferences").select("*").eq("user_id", user_id).execute()
        if resp.data:
            r = resp.data[0]
            return {
                "preferences": r.get("preferences", []),
                "disabled_subtypes": r.get("disabled_subtypes", []),
            }
        return {"preferences": [], "disabled_subtypes": []}
    except Exception as exc:
        logger.warning("Failed to load preferences: %s", exc)
        return {"preferences": [], "disabled_subtypes": []}


def save_preferences(user_id: Optional[str], preferences: List[str],
                     disabled_subtypes: List[str] = None) -> bool:
    """Save discovery preferences. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("user_preferences").upsert({
            "user_id": user_id,
            "preferences": preferences,
            "disabled_subtypes": disabled_subtypes or [],
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save preferences: %s", exc)
        return False


# ── Negative feedback ─────────────────────────────────────────────────────────

def load_negative_feedback(user_id: Optional[str] = None) -> set:
    """Load negative feedback keys."""
    client = _get_client()
    if not client or not user_id:
        return set()
    try:
        resp = client.table("negative_feedback").select("feedback_key").eq("user_id", user_id).execute()
        return {r["feedback_key"] for r in (resp.data or [])}
    except Exception as exc:
        logger.warning("Failed to load negative feedback: %s", exc)
        return set()


def save_negative_feedback(user_id: Optional[str], key: str) -> bool:
    """Save a negative feedback key. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("negative_feedback").upsert({
            "user_id": user_id,
            "feedback_key": key,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save negative feedback: %s", exc)
        return False


# ── Read articles ─────────────────────────────────────────────────────────────

def load_read_articles(user_id: Optional[str] = None) -> set:
    """Load read article URLs."""
    client = _get_client()
    if not client or not user_id:
        return set()
    try:
        resp = client.table("read_articles").select("article_url").eq("user_id", user_id).execute()
        return {r["article_url"] for r in (resp.data or [])}
    except Exception as exc:
        logger.warning("Failed to load read articles: %s", exc)
        return set()


def save_read_article(user_id: Optional[str], url: str) -> bool:
    """Mark an article as read. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("read_articles").upsert({
            "user_id": user_id,
            "article_url": url,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save read article: %s", exc)
        return False


# ── Alerts ────────────────────────────────────────────────────────────────────

def load_alerts(user_id: Optional[str] = None) -> list:
    """Load alert keywords."""
    client = _get_client()
    if not client or not user_id:
        return []
    try:
        resp = client.table("alerts").select("keyword").eq("user_id", user_id).execute()
        return [r["keyword"] for r in (resp.data or [])]
    except Exception as exc:
        logger.warning("Failed to load alerts: %s", exc)
        return []


def save_alert(user_id: Optional[str], keyword: str) -> bool:
    """Save an alert keyword. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("alerts").upsert({
            "user_id": user_id,
            "keyword": keyword,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save alert: %s", exc)
        return False


def remove_alert(user_id: Optional[str], keyword: str) -> bool:
    """Remove an alert keyword. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("alerts").delete().eq("user_id", user_id).eq("keyword", keyword).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to remove alert: %s", exc)
        return False


# ── Local config ──────────────────────────────────────────────────────────────

def load_local_config(user_id: Optional[str] = None) -> dict:
    """Load local news configuration."""
    client = _get_client()
    if not client or not user_id:
        return {"city": "", "region": "", "interests": []}
    try:
        resp = client.table("local_config").select("*").eq("user_id", user_id).execute()
        if resp.data:
            r = resp.data[0]
            return {
                "city": r.get("city", ""),
                "region": r.get("region", ""),
                "interests": r.get("interests", []),
            }
        return {"city": "", "region": "", "interests": []}
    except Exception as exc:
        logger.warning("Failed to load local config: %s", exc)
        return {"city": "", "region": "", "interests": []}


def save_local_config(user_id: Optional[str], city: str, region: str,
                     interests: list = None) -> bool:
    """Save local news configuration. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("local_config").upsert({
            "user_id": user_id,
            "city": city,
            "region": region,
            "interests": interests or [],
        }).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save local config: %s", exc)
        return False


# ── Subtopics ─────────────────────────────────────────────────────────────────

def load_subtopics(user_id: Optional[str] = None) -> dict:
    """Load user subtopics."""
    client = _get_client()
    if not client or not user_id:
        return {}
    try:
        resp = client.table("user_subtopics").select("*").eq("user_id", user_id).execute()
        result = {}
        for r in (resp.data or []):
            topic = r.get("topic", "")
            subtopic = r.get("subtopic", "")
            if topic and subtopic:
                result.setdefault(topic, []).append(subtopic)
        return result
    except Exception as exc:
        logger.warning("Failed to load subtopics: %s", exc)
        return {}


def save_subtopics(user_id: Optional[str], subtopics: dict) -> bool:
    """Save user subtopics. Returns True on success."""
    client = _get_client()
    if not client or not user_id:
        return False
    try:
        client.table("user_subtopics").delete().eq("user_id", user_id).execute()
        rows = []
        for topic, subs in (subtopics or {}).items():
            for sub in (subs or []):
                rows.append({"user_id": user_id, "topic": topic, "subtopic": sub})
        if rows:
            client.table("user_subtopics").insert(rows).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save subtopics: %s", exc)
        return False
