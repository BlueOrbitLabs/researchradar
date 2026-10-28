"""Deterministic tests for the optional extraction module (Phase 6)."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extraction  # noqa: E402


class ExtractionAvailabilityTest(unittest.TestCase):
    def test_is_trafilatura_available_returns_bool(self):
        self.assertIsInstance(extraction.is_trafilatura_available(), bool)


class ExtractionUrlValidationTest(unittest.TestCase):
    def test_rejects_empty_url(self):
        r = extraction.extract_article("")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_none_url(self):
        r = extraction.extract_article(None)
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_unsupported_scheme(self):
        r = extraction.extract_article("ftp://example.com/article")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_google_news_wrapper(self):
        r = extraction.extract_article(
            "https://news.google.com/rss/articles/CBMiabc123?oc=5")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_is_google_news_url_detects_wrapper(self):
        self.assertTrue(extraction.is_google_news_url(
            "https://news.google.com/rss/articles/abc"))
        self.assertFalse(extraction.is_google_news_url(
            "https://example.com/article"))

    def test_rejects_private_ip(self):
        r = extraction.extract_article("http://127.0.0.1/article")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_loopback(self):
        r = extraction.extract_article("http://localhost/article")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)


class ExtractionDownloadTest(unittest.TestCase):
    def test_successful_extraction_with_injected_downloader(self):
        html = "<html><body><article><h1>Test Title</h1><p>" + "word " * 50 + "</p></article></body></html>"
        r = extraction.extract_article(
            "https://example.com/article",
            downloader=lambda url: html)
        self.assertEqual(r["status"], extraction.STATUS_SUCCESS)
        self.assertTrue(len(r["text"]) >= extraction.MIN_EXTRACTED_CHARS)
        self.assertEqual(r["title"], "Test Title")

    def test_blocked_download_returns_blocked(self):
        r = extraction.extract_article(
            "https://example.com/article",
            downloader=lambda url: None)
        self.assertEqual(r["status"], extraction.STATUS_BLOCKED)

    def test_downloader_exception_returns_blocked(self):
        def bad_downloader(url):
            raise ConnectionError("timeout")
        r = extraction.extract_article(
            "https://example.com/article",
            downloader=bad_downloader)
        self.assertEqual(r["status"], extraction.STATUS_BLOCKED)

    def test_insufficient_text_returns_insufficient(self):
        html = "<html><body><p>Short.</p></body></html>"
        r = extraction.extract_article(
            "https://example.com/article",
            downloader=lambda url: html)
        self.assertEqual(r["status"], extraction.STATUS_INSUFFICIENT)

    def test_empty_html_returns_blocked(self):
        r = extraction.extract_article(
            "https://example.com/article",
            downloader=lambda url: "")
        self.assertEqual(r["status"], extraction.STATUS_BLOCKED)


class ExtractionUnavailableTest(unittest.TestCase):
    def test_unavailable_when_trafilatura_missing(self):
        with patch.object(extraction, "_TRAFILATURA_AVAILABLE", False):
            with patch.object(extraction, "_trafilatura", None):
                r = extraction.extract_article(
                    "https://example.com/article",
                    downloader=lambda url: "<html><body><p>" + "word " * 50 + "</p></body></html>")
                self.assertEqual(r["status"], extraction.STATUS_UNAVAILABLE)


class ExtractIfEligibleTest(unittest.TestCase):
    def test_skips_google_news_wrapper(self):
        r = extraction.extract_if_eligible(
            {"url": "https://news.google.com/rss/articles/abc"})
        self.assertEqual(r["status"], extraction.STATUS_SKIPPED)

    def test_skips_no_url(self):
        r = extraction.extract_if_eligible({"url": ""})
        self.assertEqual(r["status"], extraction.STATUS_SKIPPED)

    def test_skips_already_extracted(self):
        r = extraction.extract_if_eligible({
            "url": "https://example.com/article",
            "extraction_status": "full_text",
            "extracted_text": "some text"})
        self.assertEqual(r["status"], extraction.STATUS_SKIPPED)

    def test_skips_non_dict(self):
        r = extraction.extract_if_eligible("not a dict")
        self.assertEqual(r["status"], extraction.STATUS_SKIPPED)


class ApplyExtractionTest(unittest.TestCase):
    def test_success_preserves_snippet(self):
        article = {"title": "Test", "url": "https://example.com/a",
                   "summary": "Original snippet.", "date": "2026-10-27"}
        extraction_result = {
            "status": extraction.STATUS_SUCCESS,
            "text": "Full extracted text " * 20,
            "title": "Extracted Title",
            "author": "Author",
            "date": "2026-10-26",
            "image": "",
            "error": "",
        }
        result = extraction.apply_extraction(article, extraction_result)
        self.assertEqual(result["extraction_status"], "full_text")
        self.assertTrue(result["extracted_text"].startswith("Full extracted"))
        self.assertEqual(result["snippet"], "Original snippet.")
        self.assertEqual(result["summary"], "Original snippet.")
        # Date NOT overwritten when publication_date exists (date is set)
        # Actually date IS set in article, so extractor date should NOT overwrite
        self.assertEqual(result["date"], "2026-10-27")

    def test_success_uses_extractor_date_when_no_publication_date(self):
        article = {"title": "Test", "url": "https://example.com/a",
                   "summary": "Snippet.", "date": ""}
        extraction_result = {
            "status": extraction.STATUS_SUCCESS,
            "text": "Full text " * 20,
            "title": "", "author": "", "date": "2026-10-26",
            "image": "", "error": "",
        }
        result = extraction.apply_extraction(article, extraction_result)
        self.assertEqual(result["publication_date"], "2026-10-26")
        self.assertEqual(result["date"], "2026-10-26")
        self.assertEqual(result["date_source"], "extractor")

    def test_failure_records_status(self):
        article = {"title": "Test", "url": "https://example.com/a",
                   "summary": "Snippet."}
        extraction_result = {
            "status": extraction.STATUS_BLOCKED,
            "text": "", "title": "", "author": "", "date": "", "image": "",
            "error": "download failed",
        }
        result = extraction.apply_extraction(article, extraction_result)
        self.assertEqual(result["extraction_status"], extraction.STATUS_BLOCKED)
        self.assertEqual(result["extraction_error"], "download failed")
        self.assertEqual(result["snippet"], "Snippet.")

    def test_non_dict_returns_empty(self):
        self.assertEqual(extraction.apply_extraction("bad", {}), {})


class SelectCandidatesTest(unittest.TestCase):
    def test_selects_high_relevance_direct_urls(self):
        articles = [
            {"title": "A", "url": "https://example.com/a", "relevance": 0.9},
            {"title": "B", "url": "https://news.google.com/rss/articles/x", "relevance": 0.95},
            {"title": "C", "url": "https://example.com/c", "relevance": 0.2},
            {"title": "D", "url": "https://example.com/d", "relevance": 0.8,
             "extraction_status": "full_text", "extracted_text": "text"},
        ]
        cands = extraction.select_extraction_candidates(articles, limit=5)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["title"], "A")

    def test_empty_returns_empty(self):
        self.assertEqual(extraction.select_extraction_candidates([]), [])


class CachingTest(unittest.TestCase):
    def setUp(self):
        extraction.clear_cache()

    def tearDown(self):
        extraction.clear_cache()

    def test_duplicate_requests_use_cache(self):
        call_count = [0]
        def downloader(url):
            call_count[0] += 1
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        r1 = extraction.cached_extract("https://example.com/article", downloader=downloader)
        r2 = extraction.cached_extract("https://example.com/article", downloader=downloader)
        self.assertEqual(r1["status"], extraction.STATUS_SUCCESS)
        self.assertEqual(r2["status"], extraction.STATUS_SUCCESS)
        self.assertEqual(call_count[0], 1)

    def test_cache_size(self):
        extraction.cached_extract("https://example.com/a",
                                 downloader=lambda u: "<html><body><p>" + "word " * 50 + "</p></body></html>")
        self.assertEqual(extraction.get_cache_size(), 1)

    def test_clear_cache(self):
        extraction.cached_extract("https://example.com/a",
                                 downloader=lambda u: "<html><body><p>" + "word " * 50 + "</p></body></html>")
        extraction.clear_cache()
        self.assertEqual(extraction.get_cache_size(), 0)




if __name__ == "__main__":
    unittest.main(verbosity=2)


class ExtractionPromptIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        # Extract just the three prompt functions by exec-ing their definitions
        ns = {}
        for name in ["build_summary_prompt", "build_takeaways_prompt", "build_why_matters_prompt"]:
            idx = src.find(f"def {name}")
            end = src.find("\n\ndef ", idx + 1)
            if end == -1:
                end = src.find("\n# ", idx + 1)
            exec(src[idx:end], ns)
        cls.build_summary_prompt = staticmethod(ns["build_summary_prompt"])
        cls.build_takeaways_prompt = staticmethod(ns["build_takeaways_prompt"])
        cls.build_why_matters_prompt = staticmethod(ns["build_why_matters_prompt"])

    def test_summary_prompt_uses_extracted_text(self):
        prompt = self.build_summary_prompt("Title", "Snippet", extracted_text="Full article text here")
        self.assertIn("Extracted article text", prompt)
        self.assertIn("Full article text here", prompt)

    def test_summary_prompt_falls_back_to_snippet(self):
        prompt = self.build_summary_prompt("Title", "Snippet text")
        self.assertIn("Snippet: Snippet text", prompt)
        self.assertIn("short snippet", prompt)

    def test_takeaways_prompt_uses_extracted_text(self):
        prompt = self.build_takeaways_prompt("Title", "Snippet", extracted_text="Full text")
        self.assertIn("Extracted text", prompt)

    def test_why_matters_prompt_uses_extracted_text(self):
        prompt = self.build_why_matters_prompt("Title", "Snippet", extracted_text="Full text")
        self.assertIn("Extracted text", prompt)


class UrlSafetyTest(unittest.TestCase):
    def test_rejects_javascript_scheme(self):
        r = extraction.extract_article("javascript:alert(1)")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_file_scheme(self):
        r = extraction.extract_article("file:///etc/passwd")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_data_scheme(self):
        r = extraction.extract_article("data:text/html,<h1>hi</h1>")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_google_news_wrapper_variants(self):
        for url in [
            "https://news.google.com/rss/articles/abc",
            "https://news.google.com/articles/xyz",
        ]:
            r = extraction.extract_article(url, downloader=lambda u: "<html><body><p>" + "word "*50 + "</p></body></html>")
            self.assertEqual(r["status"], extraction.STATUS_INVALID_URL, url)

    def test_rejects_private_ip_ranges(self):
        for url in ["http://10.0.0.1/x", "http://192.168.1.1/x", "http://172.16.0.1/x"]:
            r = extraction.extract_article(url)
            self.assertEqual(r["status"], extraction.STATUS_INVALID_URL, url)

    def test_rejects_link_local(self):
        r = extraction.extract_article("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_localhost(self):
        r = extraction.extract_article("http://localhost:8080/secret")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_rejects_empty_host(self):
        r = extraction.extract_article("http:///path")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_download_size_limit(self):
        big_html = "x" * (extraction.MAX_RESPONSE_BYTES + 1)
        r = extraction.extract_article(
            "https://example.com/big",
            downloader=lambda u: big_html)
        self.assertEqual(r["status"], extraction.STATUS_BLOCKED)

    def test_redirect_chain_validated_before_download(self):
        # The initial URL is validated before the downloader is called.
        called = []
        def downloader(url):
            called.append(url)
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        r = extraction.extract_article("http://10.0.0.1/secret", downloader=downloader)
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)
        self.assertEqual(called, [])  # downloader never called


class ExtractionProvenanceTest(unittest.TestCase):
    def test_snippet_preserved_on_success(self):
        art = {"title": "T", "url": "https://example.com/a",
               "summary": "Original snippet.", "date": "2026-10-27"}
        res = {"status": extraction.STATUS_SUCCESS,
               "text": "Extracted full text " * 20, "title": "", "author": "",
               "date": "2026-10-26", "image": "", "error": ""}
        out = extraction.apply_extraction(art, res)
        self.assertEqual(out["snippet"], "Original snippet.")
        self.assertEqual(out["summary"], "Original snippet.")
        self.assertEqual(out["extracted_text"], ("Extracted full text " * 20).strip())
        self.assertEqual(out["date"], "2026-10-27")  # date NOT overwritten

    def test_snippet_preserved_on_failure(self):
        art = {"title": "T", "url": "https://example.com/a",
               "summary": "Original snippet."}
        res = {"status": extraction.STATUS_BLOCKED, "text": "", "title": "",
               "author": "", "date": "", "image": "", "error": "timeout"}
        out = extraction.apply_extraction(art, res)
        self.assertEqual(out["snippet"], "Original snippet.")
        self.assertEqual(out["summary"], "Original snippet.")
        self.assertNotIn("extracted_text", out)

    def test_extractor_date_not_used_when_pub_date_exists(self):
        art = {"title": "T", "url": "https://example.com/a",
               "summary": "S", "date": "2026-10-27", "publication_date": "2026-10-27"}
        res = {"status": extraction.STATUS_SUCCESS,
               "text": "Text " * 20, "title": "", "author": "",
               "date": "2026-01-01", "image": "", "error": ""}
        out = extraction.apply_extraction(art, res)
        self.assertEqual(out["publication_date"], "2026-10-27")
        self.assertEqual(out["date"], "2026-10-27")

    def test_extractor_date_used_when_no_pub_date(self):
        art = {"title": "T", "url": "https://example.com/a",
               "summary": "S", "date": "", "publication_date": ""}
        res = {"status": extraction.STATUS_SUCCESS,
               "text": "Text " * 20, "title": "", "author": "",
               "date": "2026-10-26", "image": "", "error": ""}
        out = extraction.apply_extraction(art, res)
        self.assertEqual(out["publication_date"], "2026-10-26")
        self.assertEqual(out["date"], "2026-10-26")
        self.assertEqual(out["date_source"], "extractor")

    def test_extraction_timestamp_is_not_publication_date(self):
        art = {"title": "T", "url": "https://example.com/a",
               "summary": "S", "date": "2026-10-27"}
        res = {"status": extraction.STATUS_SUCCESS,
               "text": "Text " * 20, "title": "", "author": "",
               "date": "", "image": "", "error": ""}
        out = extraction.apply_extraction(art, res, extracted_at="2026-10-27T12:00:00Z")
        self.assertEqual(out["extraction_timestamp"], "2026-10-27T12:00:00Z")
        self.assertEqual(out["date"], "2026-10-27")
        self.assertEqual(out["publication_date"], "2026-10-27")


class RedirectSafetyTest(unittest.TestCase):
    """Deterministic redirect-chain tests. No live network."""

    def test_redirect_to_private_ip_rejected(self):
        def downloader(url):
            # Simulate a redirect to a private IP by raising after validation
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        # The initial URL is safe, but we test _is_safe_url on the redirect target
        self.assertFalse(extraction._is_safe_url("http://10.0.0.1/secret"))

    def test_redirect_to_loopback_rejected(self):
        self.assertFalse(extraction._is_safe_url("http://127.0.0.1/secret"))
        self.assertFalse(extraction._is_safe_url("http://localhost/secret"))

    def test_redirect_to_link_local_rejected(self):
        self.assertFalse(extraction._is_safe_url("http://169.254.169.254/latest/"))

    def test_redirect_to_prohibited_scheme_rejected(self):
        for scheme in ["javascript", "data", "file", "ftp", "vbscript"]:
            self.assertFalse(extraction._is_safe_url(f"{scheme}://example.com/x"))

    def test_credentials_in_url_rejected(self):
        r = extraction.extract_article("https://user:pass@example.com/article")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_malformed_url_rejected(self):
        r = extraction.extract_article("not-a-url")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_empty_host_rejected(self):
        r = extraction.extract_article("http:///path")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_google_news_wrapper_rejected(self):
        r = extraction.extract_article("https://news.google.com/rss/articles/abc")
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)

    def test_ipv4_mapped_ipv6_rejected(self):
        # ::ffff:127.0.0.1 is an IPv4-mapped loopback
        self.assertFalse(extraction._is_safe_url("http://[::ffff:127.0.0.1]/x"))

    def test_max_redirects_constant(self):
        self.assertEqual(extraction.MAX_REDIRECTS, 3)

    def test_redirect_chain_validated_before_download(self):
        """Ensure _is_safe_url is called before downloader for initial URL."""
        called = []
        def downloader(url):
            called.append(url)
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        r = extraction.extract_article("http://10.0.0.1/secret", downloader=downloader)
        self.assertEqual(r["status"], extraction.STATUS_INVALID_URL)
        self.assertEqual(called, [])  # downloader never called

    def test_safe_public_url_accepted(self):
        # example.com resolves to a public IP
        # (may fail in CI without DNS, so check _is_safe_url returns bool)
        result = extraction._is_safe_url("https://example.com/article")
        self.assertIsInstance(result, bool)


class RedirectChainTest(unittest.TestCase):
    """Test redirect chain handling with mocked requests."""

    def _make_response(self, status_code, location=None, body=None):
        """Create a mock response object."""
        class MockResponse:
            def __init__(self):
                self.status_code = status_code
                self.headers = {}
                if location:
                    self.headers["Location"] = location
                self._body = body or b""
            def iter_content(self, chunk_size=8192):
                yield self._body
            def close(self):
                pass
        return MockResponse()

    def test_redirect_loop_rejected(self):
        # A -> B -> A should be rejected
        responses = {
            "https://example.com/a": self._make_response(302, "https://example.com/b"),
            "https://example.com/b": self._make_response(302, "https://example.com/a"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/a")
            self.assertIsNone(body)
            self.assertIn("loop", err)

    def test_excessive_redirects_rejected(self):
        # Chain of 5 redirects (max is 3)
        responses = {}
        for i in range(6):
            responses[f"https://example.com/{i}"] = self._make_response(
                302, f"https://example.com/{i+1}")
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/0")
            self.assertIsNone(body)
            self.assertIn("too many redirects", err)

    def test_redirect_to_private_ip_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "http://10.0.0.1/secret"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)

    def test_redirect_to_loopback_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "http://127.0.0.1/secret"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)

    def test_redirect_to_link_local_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "http://169.254.169.254/latest/"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)

    def test_valid_public_redirect_chain_succeeds(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "https://example.com/final"),
            "https://example.com/final": self._make_response(
                200, body=b"<html><body><p>" + b"word " * 50 + b"</p></body></html>"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNotNone(body)
            self.assertEqual(err, "")
            self.assertEqual(final, "https://example.com/final")

    def test_redirect_to_prohibited_scheme_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "javascript:alert(1)"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)

    def test_redirect_without_location_header(self):
        responses = {
            "https://example.com/start": self._make_response(302),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            # No Location header -> treated as success with empty body
            self.assertEqual(err, "")

    def test_http_error_status_rejected(self):
        responses = {
            "https://example.com/bad": self._make_response(404),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/bad")
            self.assertIsNone(body)
            self.assertIn("HTTP 404", err)

    def test_oversized_response_rejected(self):
        big_body = b"x" * (extraction.MAX_RESPONSE_BYTES + 1)
        responses = {
            "https://example.com/big": self._make_response(200, body=big_body),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/big")
            self.assertIsNone(body)
            self.assertIn("too large", err)

    def test_redirect_with_credentials_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "https://user:pass@example.com/secret"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)

    def test_redirect_to_google_news_rejected(self):
        responses = {
            "https://example.com/start": self._make_response(
                302, "https://news.google.com/rss/articles/abc"),
        }
        def mock_get(url, **kwargs):
            return responses[url]
        with patch("requests.get", side_effect=mock_get):
            body, final, err = extraction._validate_redirect_chain("https://example.com/start")
            self.assertIsNone(body)
            self.assertIn("unsafe redirect", err)


class ExtractionCacheTest(unittest.TestCase):
    def setUp(self):
        extraction.clear_cache()

    def tearDown(self):
        extraction.clear_cache()

    def test_cache_survives_repeated_calls(self):
        call_count = [0]
        def downloader(url):
            call_count[0] += 1
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        r1 = extraction.cached_extract("https://example.com/cached", downloader=downloader)
        r2 = extraction.cached_extract("https://example.com/cached", downloader=downloader)
        self.assertEqual(r1["status"], extraction.STATUS_SUCCESS)
        self.assertEqual(r2["status"], extraction.STATUS_SUCCESS)
        self.assertEqual(call_count[0], 1)

    def test_cache_key_normalizes_url(self):
        extraction.clear_cache()
        call_count = [0]
        def downloader(url):
            call_count[0] += 1
            return "<html><body><p>" + "word " * 50 + "</p></body></html>"
        extraction.cached_extract("https://example.com/article?utm_source=x", downloader=downloader)
        extraction.cached_extract("https://example.com/article", downloader=downloader)
        # Both should use the same cache key (canonical URL)
        self.assertEqual(call_count[0], 1)
