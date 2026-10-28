"""Optional full-text extraction using Trafilatura.

This module is intentionally small and dependency-light. Trafilatura is an
optional dependency: if it is unavailable, every function degrades gracefully
and returns an explicit ``unavailable`` status. No network access is required
to import this module or to run its unit tests.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional

# Lazy import so the rest of the app boots when Trafilatura is absent.
try:
    import trafilatura as _trafilatura
    _TRAFILATURA_AVAILABLE = True
except Exception:  # pragma: no cover - exercised by tests via monkeypatch
    _trafilatura = None
    _TRAFILATURA_AVAILABLE = False


# Statuses returned by `extract_article`. These are the only values callers
# should rely on; new statuses require updating the documented contract.
STATUS_SUCCESS = "success"
STATUS_UNAVAILABLE = "unavailable"          # Trafilatura not installed
STATUS_INVALID_URL = "invalid_url"          # scheme/host/size/timeout problems
STATUS_BLOCKED = "blocked"                  # download failed or was disallowed
STATUS_INSUFFICIENT = "insufficient"        # extracted text too short
STATUS_ERROR = "error"                      # unexpected extraction failure
STATUS_SKIPPED = "skipped"                  # caller decided not to attempt

# Google News wrapper hostnames. These are redirect pages, not articles.
_GOOGLE_NEWS_HOSTS = {"news.google.com", "news.google.co.uk", "news.google.com.au"}

# Minimum number of characters for extracted text to be considered usable.
MIN_EXTRACTED_CHARS = 200

# Maximum response body size we are willing to download (bytes).
MAX_RESPONSE_BYTES = 2_000_000

# Default HTTP timeout in seconds.
DEFAULT_TIMEOUT = 12

# Maximum number of redirects to follow before rejecting the chain.
MAX_REDIRECTS = 3

# Prohibited URL schemes (case-insensitive).
_PROHIBITED_SCHEMES = frozenset({"javascript", "data", "file", "ftp", "vbscript",
                                 "blob", "about", "chrome", "chrome-extension"})

# User-Agent sent to publishers.
_USER_AGENT = "Owlume/1.0 (+https://owlume.example; research feed)"


def is_trafilatura_available() -> bool:
    """Return True when Trafilatura can be imported."""
    return _TRAFILATURA_AVAILABLE


def _is_safe_url(url: str) -> bool:
    """Validate scheme, credentials and destination; reject unsafe hosts.

    Rejects:
    - Non-http(s) schemes and prohibited schemes.
    - URLs with embedded credentials (user:pass@host).
    - Google News wrapper URLs.
    - Private, loopback, link-local, multicast, reserved and unspecified IPs.
    - IPv4-mapped IPv6 addresses that resolve to private/loopback ranges.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    # Reject prohibited schemes (defence in depth).
    if parsed.scheme.lower() in _PROHIBITED_SCHEMES:
        return False
    # Reject embedded credentials.
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    # Reject Google News wrapper URLs.
    if host in _GOOGLE_NEWS_HOSTS:
        return False
    # Reject malformed/ambiguous hosts.
    if "@" in host or ":" in host.split("]")[0] if "[" in host else ":" in host:
        # Allow IPv6 bracket notation but reject port-in-host ambiguity
        if not (host.startswith("[") and host.endswith("]")):
            return False
    # Resolve and validate all IPs.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        # Unwrap IPv4-mapped IPv6.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


def _resolve_and_validate_host(host: str) -> tuple:
    """Resolve hostname and validate all resulting IPs.

    Returns (ip_list, error_string). If error_string is non-empty, the host
    is unsafe or unresolvable.

    DNS rebinding mitigation: we resolve once and return the validated IPs.
    The caller must connect to one of these IPs. However, since requests
    uses the hostname for SNI/TLS, we cannot fully pin the connection in
    all cases. This is a documented limitation.
    """
    if not host:
        return [], "empty host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return [], "DNS resolution failed"
    if not infos:
        return [], "no DNS results"

    validated_ips = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return [], f"invalid IP address: {addr}"
        # Unwrap IPv4-mapped IPv6.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return [], f"unsafe IP address: {ip}"
        validated_ips.append(str(ip))

    if not validated_ips:
        return [], "no safe IP addresses"
    return validated_ips, ""


def _validate_url_full(url: str) -> tuple:
    """Full URL validation including DNS resolution.

    Returns (parsed_url, error_string). If error_string is non-empty, URL is unsafe.
    """
    if not url or not isinstance(url, str):
        return None, "empty or non-string URL"
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return None, "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return None, "unsupported scheme"
    if parsed.scheme.lower() in _PROHIBITED_SCHEMES:
        return None, "prohibited scheme"
    if parsed.username or parsed.password:
        return None, "credentials in URL"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None, "empty host"
    if host in _GOOGLE_NEWS_HOSTS:
        return None, "google news wrapper URL"
    # Reject malformed/ambiguous hosts.
    if "@" in host:
        return None, "ambiguous host"
    # IPv6 bracket validation
    if ":" in host and not host.startswith("["):
        # Could be host:port without brackets — reject if not valid IPv4
        parts = host.rsplit(":", 1)
        if len(parts) == 2:
            try:
                ipaddress.ip_address(parts[0])
            except ValueError:
                return None, "malformed host"
    # DNS resolution and IP validation
    _, err = _resolve_and_validate_host(host)
    if err:
        return None, err
    return parsed, ""


def _validate_redirect_chain(start_url: str, timeout: int = DEFAULT_TIMEOUT,
                            max_redirects: int = MAX_REDIRECTS) -> tuple:
    """Follow redirects manually, validating each destination before requesting.

    Returns (body_or_None, final_url, error_string).
    Uses requests with allow_redirects=False. Each redirect destination is
    validated (scheme, host, DNS, IP safety) before the next request.

    Security notes:
    - DNS is re-resolved and re-validated on each redirect step.
    - Redirect loops are detected by tracking seen URLs.
    - Maximum redirect count is enforced.
    - Response body is read with a size limit.
    - All responses are closed on success and failure paths.
    - Fail-closed: any validation failure returns an error.

    Limitation: DNS rebinding (TOCTOU) is mitigated by re-resolving on each
    step, but the HTTP client (requests) resolves DNS independently when
    connecting. We cannot fully guarantee that the IP validated is the IP
    contacted. For stronger guarantees, use a custom transport adapter that
    pins the connection to the validated IP.
    """
    import requests as _requests

    current_url = start_url.strip()
    seen_urls = {current_url}
    redirect_count = 0
    final_url = current_url

    while True:
        # Validate current URL before any request.
        parsed, err = _validate_url_full(current_url)
        if err:
            return None, current_url, f"invalid URL: {err}"

        # Issue request with redirects disabled.
        resp = None
        try:
            resp = _requests.get(
                current_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except Exception as exc:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            return None, current_url, f"request error: {exc}"

        # Read body with size limit.
        body_chunks = []
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    resp.close()
                    return None, current_url, "response too large"
                body_chunks.append(chunk)
        except Exception as exc:
            resp.close()
            return None, current_url, f"read error: {exc}"

        body = b"".join(body_chunks).decode("utf-8", errors="replace")
        status_code = resp.status_code
        headers = dict(resp.headers)
        resp.close()

        final_url = current_url

        # Check for redirect.
        if status_code in (301, 302, 303, 307, 308):
            location = headers.get("Location", "")
            if not location:
                return body, current_url, ""
            # Resolve relative URLs against current URL.
            next_url = urllib.parse.urljoin(current_url, location)
            # Validate redirect destination before following.
            _, err = _validate_url_full(next_url)
            if err:
                return None, next_url, f"unsafe redirect destination: {err}"
            if next_url in seen_urls:
                return None, next_url, "redirect loop detected"
            if redirect_count >= max_redirects:
                return None, next_url, f"too many redirects (max {max_redirects})"
            seen_urls.add(next_url)
            redirect_count += 1
            current_url = next_url
            continue

        # Non-redirect response.
        if status_code >= 400:
            return None, current_url, f"HTTP {status_code}"
        return body, current_url, ""


def safe_download(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """Production downloader that validates redirects and enforces limits.

    Returns the response body as a string, or None on any failure.
    All redirects are validated before following. Automatic redirect
    following is disabled.
    """
    body, final_url, error = _validate_redirect_chain(url, timeout=timeout)
    if error:
        return None
    return body


def extract_article(url: str, *,
                    downloader: Optional[Callable[[str], Optional[str]]] = None,
                    timeout: int = DEFAULT_TIMEOUT,
                    min_chars: int = MIN_EXTRACTED_CHARS) -> Dict[str, Any]:
    """Extract main text and metadata from a direct article URL.

    Returns a dict with keys:
      - ``status``: one of the STATUS_* constants
      - ``text``: extracted main text (empty on failure)
      - ``title``: extracted title (may be empty)
      - ``author``: extracted author(s) (may be empty)
      - ``date``: extracted publication date string (may be empty)
      - ``image``: extracted top image URL (may be empty)
      - ``error``: human-readable error (empty on success)

    ``downloader`` is an injectable callable returning raw HTML (or None).
    When None, Trafilatura's own fetcher is used. Tests should inject a
    downloader to avoid live network access.
    """
    result = {
        "status": STATUS_ERROR,
        "text": "",
        "title": "",
        "author": "",
        "date": "",
        "image": "",
        "error": "",
    }

    if not _TRAFILATURA_AVAILABLE:
        result["status"] = STATUS_UNAVAILABLE
        result["error"] = "trafilatura not installed"
        return result

    if not url or not isinstance(url, str):
        result["status"] = STATUS_INVALID_URL
        result["error"] = "empty or non-string URL"
        return result

    url = url.strip()
    if not _is_safe_url(url):
        result["status"] = STATUS_INVALID_URL
        result["error"] = "unsafe or unsupported URL"
        return result

    # Download with redirect safety.
    html = None
    final_url = url
    download_error = ""
    if downloader is not None:
        # Injected downloader: validate initial URL first, then call.
        # Note: we cannot control redirect behavior of injected downloaders.
        # Production code should use the default path (downloader=None) which
        # uses _validate_redirect_chain with allow_redirects=False.
        parsed, err = _validate_url_full(url)
        if err:
            result["status"] = STATUS_INVALID_URL
            result["error"] = err
            return result
        try:
            html = downloader(url)
        except Exception as exc:
            result["status"] = STATUS_BLOCKED
            result["error"] = f"downloader error: {exc}"
            return result
    else:
        # Production path: safe redirect-following with per-step validation.
        html, final_url, download_error = _validate_redirect_chain(
            url, timeout=timeout)
        if download_error and not html:
            result["status"] = STATUS_BLOCKED
            result["error"] = download_error
            return result

    if not html:
        result["status"] = STATUS_BLOCKED
        result["error"] = "download returned empty response"
        return result

    if len(html) > MAX_RESPONSE_BYTES:
        result["status"] = STATUS_BLOCKED
        result["error"] = "response too large"
        return result

    # Extract
    try:
        text = _trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            output_format="txt",
        )
        meta_json = _trafilatura.extract(
            html,
            output_format="json",
            with_metadata=True,
        )
    except Exception as exc:
        result["status"] = STATUS_ERROR
        result["error"] = f"extraction error: {exc}"
        return result

    if not text or len(text.strip()) < min_chars:
        result["status"] = STATUS_INSUFFICIENT
        result["error"] = f"extracted text too short ({len(text or '')} chars)"
        return result

    result["text"] = text.strip()
    result["status"] = STATUS_SUCCESS

    if meta_json:
        try:
            meta = __import__("json").loads(meta_json)
            result["title"] = (meta.get("title") or "").strip()
            result["author"] = (meta.get("author") or "").strip()
            result["date"] = (meta.get("date") or "").strip()
            result["image"] = (meta.get("image") or "").strip()
        except Exception:
            pass

    return result


def is_google_news_url(url: str) -> bool:
    """Return True if the URL is a Google News wrapper/redirect."""
    if not url or not isinstance(url, str):
        return False
    try:
        host = urllib.parse.urlparse(url.strip()).hostname or ""
    except Exception:
        return False
    return host.lower() in _GOOGLE_NEWS_HOSTS


def extract_if_eligible(article: dict, *,
                        downloader: Optional[Callable[[str], Optional[str]]] = None,
                        timeout: int = DEFAULT_TIMEOUT,
                        min_chars: int = MIN_EXTRACTED_CHARS) -> Dict[str, Any]:
    """Extract full text for an article if it has a direct, safe URL.

    Returns a dict with ``status`` and extracted fields. If the article has
    no URL, has a Google News wrapper URL, or is already extracted, returns
    ``STATUS_SKIPPED`` with empty text.
    """
    if not isinstance(article, dict):
        return {"status": STATUS_SKIPPED, "text": "", "title": "", "author": "",
                "date": "", "image": "", "error": "not a dict"}

    url = (article.get("url") or "").strip()
    if not url:
        return {"status": STATUS_SKIPPED, "text": "", "title": "", "author": "",
                "date": "", "image": "", "error": "no URL"}

    if is_google_news_url(url):
        return {"status": STATUS_SKIPPED, "text": "", "title": "", "author": "",
                "date": "", "image": "", "error": "google news wrapper URL"}

    # Skip if already extracted.
    if (article.get("extraction_status") == "full_text"
            and (article.get("extracted_text") or "").strip()):
        return {"status": STATUS_SKIPPED, "text": "", "title": "", "author": "",
                "date": "", "image": "", "error": "already extracted"}

    return extract_article(url, downloader=downloader, timeout=timeout,
                          min_chars=min_chars)


def apply_extraction(article: dict, extraction: Dict[str, Any],
                     *, extracted_at: Optional[str] = None) -> dict:
    """Apply an extraction result to an article copy.

    Preserves the original snippet/abstract. Never overwrites publication
    date with extractor-generated date unless provenance is validated.
    Returns a new dict; does not mutate the input.
    """
    if not isinstance(article, dict):
        return {}
    result = dict(article)
    status = extraction.get("status", STATUS_ERROR)

    if status == STATUS_SUCCESS:
        text = (extraction.get("text") or "").strip()
        if text:
            result["extracted_text"] = text
            # Ensure publication_date exists (from date or extractor).
            if not result.get("publication_date"):
                result["publication_date"] = result.get("date", "")
            result["extraction_status"] = "full_text"
            result["extraction_method"] = "trafilatura"
            result["extraction_timestamp"] = extracted_at or time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Preserve snippet — never overwrite.
            result.setdefault("snippet", result.get("summary", ""))
            # Only use extractor date if the article has no publication date.
            # The legacy ``date`` field is treated as a publication date unless
            # the adapter explicitly marked it as an RSS update timestamp.
            has_pub_date = (result.get("publication_date")
                            or (result.get("date")
                                and result.get("date_source", "published") != "updated"))
            if not has_pub_date and extraction.get("date"):
                result["publication_date"] = extraction["date"]
                result["date"] = extraction["date"]
                result["date_source"] = "extractor"
            if extraction.get("image") and not result.get("image"):
                result["image"] = extraction["image"]
            if extraction.get("title") and not result.get("title"):
                result["title"] = extraction["title"]
    else:
        # On failure/skip, record status but don't fabricate text.
        if status in (STATUS_BLOCKED, STATUS_INSUFFICIENT, STATUS_ERROR):
            result["extraction_status"] = status
            result["extraction_error"] = extraction.get("error", "")
        # Preserve snippet.
        result.setdefault("snippet", result.get("summary", ""))

    result.setdefault("snippet", result.get("summary", ""))
    return result


def select_extraction_candidates(articles, *, limit: int = 5,
                                min_relevance: float = 0.3) -> list:
    """Select high-relevance candidates for extraction.

    Prefers direct (non-Google-News) URLs, skips already-extracted articles,
    and limits to ``limit`` items. Returns a list of article dicts.
    """
    if not articles:
        return []
    candidates = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        url = (art.get("url") or "").strip()
        if not url:
            continue
        if is_google_news_url(url):
            continue
        if art.get("extraction_status") == "full_text":
            continue
        rel = art.get("relevance", 0)
        try:
            rel = float(rel)
        except (TypeError, ValueError):
            rel = 0.0
        if rel < min_relevance:
            continue
        candidates.append((rel, art))
    candidates.sort(key=lambda t: t[0], reverse=True)
    return [art for _, art in candidates[:limit]]


# In-memory cache: canonical URL -> extraction result.
_cache: Dict[str, Dict[str, Any]] = {}


def cached_extract(url: str, *,
                   downloader: Optional[Callable[[str], Optional[str]]] = None,
                   timeout: int = DEFAULT_TIMEOUT,
                   min_chars: int = MIN_EXTRACTED_CHARS) -> Dict[str, Any]:
    """Extract with in-memory caching by canonical URL.

    Cache does not survive process restarts. The cache key is the canonical
    URL (scheme/host/path without tracking params). Duplicate requests for the
    same canonical URL return the cached result without re-fetching.
    """
    if not url or not isinstance(url, str):
        return extract_article(url, downloader=downloader, timeout=timeout,
                              min_chars=min_chars)
    try:
        import feed_strategy as _fs
        key = _fs.canonical_url(url)
    except Exception:
        key = url.strip()
    if not key:
        key = url.strip()

    if key in _cache:
        return _cache[key]

    result = extract_article(url, downloader=downloader, timeout=timeout,
                            min_chars=min_chars)
    _cache[key] = result
    return result


def clear_cache() -> None:
    """Clear the in-memory extraction cache."""
    _cache.clear()


def get_cache_size() -> int:
    """Return the number of cached extraction results."""
    return len(_cache)
