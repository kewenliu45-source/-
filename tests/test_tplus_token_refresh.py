import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient


class TPlusSelfBuiltTokenRefreshTests(unittest.TestCase):
    """Tests for self_built mode token refresh fallback strategy."""

    def _make_client(self, token_cache_file: str) -> TPlusOpenAPIClient:
        with patch("app.data_sources.tplus_openapi_source.TPLUS_API_BASE_URL", "https://api.example.com"):
            with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_KEY", "test_key"):
                with patch("app.data_sources.tplus_openapi_source.APP_SECRET", "test_secret"):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_SECRET", "test_secret"):
                        client = TPlusOpenAPIClient()
        # Override cache file path for test isolation
        with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_cache_file):
            pass
        return client

    def _write_token_cache(self, path: str, expires_in: float, refresh_expires_in: float = 86400) -> None:
        now = time.time()
        payload = {
            "access_token": "cached_access_token",
            "refresh_token": "cached_refresh_token",
            "access_token_expires_at": now + expires_in,
            "refresh_token_expires_at": now + refresh_expires_in,
            "updated_at": now,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def _write_app_ticket_cache(self, path: str, age_seconds: float = 100) -> None:
        payload = {
            "app_ticket": "test_app_ticket",
            "received_at": time.time() - age_seconds,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_cached_token_not_expired_fallback_when_refresh_fails(self):
        """accessToken 未过期但 appTicket 缺失时，仍返回缓存 token."""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = os.path.join(tmpdir, "token_cache.json")
            ticket_file = os.path.join(tmpdir, "ticket_cache.json")

            # Token expires in 200s — within skew(600) but not truly expired
            self._write_token_cache(token_file, expires_in=200)
            # No app_ticket file -> _read_latest_app_ticket returns None

            client = self._make_client(token_file)

            with patch("app.data_sources.tplus_openapi_source.TPLUS_AUTH_MODE", "self_built"):
                with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_file):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET_CACHE_FILE", ticket_file):
                        with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET", ""):
                            with patch("app.data_sources.tplus_openapi_source.TPLUS_CERTIFICATE", "some_cert"):
                                token = client.get_access_token()

            self.assertEqual(token, "cached_access_token")

    def test_expired_token_no_app_ticket_raises_clear_error(self):
        """accessToken 已过期且 appTicket 缺失时，抛出清晰错误。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = os.path.join(tmpdir, "token_cache.json")
            ticket_file = os.path.join(tmpdir, "ticket_cache.json")

            # Token already expired
            self._write_token_cache(token_file, expires_in=-100)

            client = self._make_client(token_file)

            with patch("app.data_sources.tplus_openapi_source.TPLUS_AUTH_MODE", "self_built"):
                with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_file):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET_CACHE_FILE", ticket_file):
                        with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET", ""):
                            with patch("app.data_sources.tplus_openapi_source.TPLUS_CERTIFICATE", "some_cert"):
                                with self.assertRaises(RuntimeError) as ctx:
                                    client.get_access_token()

            self.assertIn("已过期", str(ctx.exception))
            self.assertIn("appTicket", str(ctx.exception))

    def test_force_refresh_no_app_ticket_raises_error(self):
        """force_refresh=True 且 appTicket 缺失时，抛出错误。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = os.path.join(tmpdir, "token_cache.json")
            ticket_file = os.path.join(tmpdir, "ticket_cache.json")

            # Token still valid (not expired)
            self._write_token_cache(token_file, expires_in=3600)

            client = self._make_client(token_file)

            with patch("app.data_sources.tplus_openapi_source.TPLUS_AUTH_MODE", "self_built"):
                with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_file):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET_CACHE_FILE", ticket_file):
                        with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET", ""):
                            with patch("app.data_sources.tplus_openapi_source.TPLUS_CERTIFICATE", "some_cert"):
                                with self.assertRaises(RuntimeError) as ctx:
                                    client.get_access_token(force_refresh=True)

            self.assertIn("已过期", str(ctx.exception))
            self.assertIn("appTicket", str(ctx.exception))

    def test_normal_with_app_ticket_calls_generate(self):
        """正常有 appTicket 时仍能走 generate_self_built_token。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = os.path.join(tmpdir, "token_cache.json")
            ticket_file = os.path.join(tmpdir, "ticket_cache.json")

            # Token already expired so it must refresh
            self._write_token_cache(token_file, expires_in=-100)
            self._write_app_ticket_cache(ticket_file)

            client = self._make_client(token_file)

            mock_payload = {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 7200,
                "refresh_expires_in": 86400,
            }
            mock_response = {"result": mock_payload}

            with patch("app.data_sources.tplus_openapi_source.TPLUS_AUTH_MODE", "self_built"):
                with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_file):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET_CACHE_FILE", ticket_file):
                        with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET", ""):
                            with patch("app.data_sources.tplus_openapi_source.TPLUS_CERTIFICATE", "test_cert"):
                                with patch.object(client, "_request_auth_token", return_value=mock_response) as mock_req:
                                    token = client.get_access_token()

            self.assertEqual(token, "new_token")
            mock_req.assert_called_once()

    def test_no_cached_token_no_app_ticket_raises_error(self):
        """没有任何缓存 token，也没有 appTicket 时，抛出清晰错误。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = os.path.join(tmpdir, "token_cache.json")
            ticket_file = os.path.join(tmpdir, "ticket_cache.json")
            # No token cache file, no ticket cache file

            client = self._make_client(token_file)

            with patch("app.data_sources.tplus_openapi_source.TPLUS_AUTH_MODE", "self_built"):
                with patch("app.data_sources.tplus_openapi_source.TPLUS_TOKEN_CACHE_FILE", token_file):
                    with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET_CACHE_FILE", ticket_file):
                        with patch("app.data_sources.tplus_openapi_source.TPLUS_APP_TICKET", ""):
                            with patch("app.data_sources.tplus_openapi_source.TPLUS_CERTIFICATE", "some_cert"):
                                with self.assertRaises(RuntimeError) as ctx:
                                    client.get_access_token()

            self.assertIn("appTicket", str(ctx.exception))


class TPlusCachedAccessTokenNotExpiredTests(unittest.TestCase):
    """Unit tests for _cached_access_token_not_expired static method."""

    def test_valid_token_returns_true(self):
        payload = {
            "access_token": "token123",
            "access_token_expires_at": time.time() + 3600,
        }
        self.assertTrue(TPlusOpenAPIClient._cached_access_token_not_expired(payload))

    def test_expired_token_returns_false(self):
        payload = {
            "access_token": "token123",
            "access_token_expires_at": time.time() - 100,
        }
        self.assertFalse(TPlusOpenAPIClient._cached_access_token_not_expired(payload))

    def test_none_payload_returns_false(self):
        self.assertFalse(TPlusOpenAPIClient._cached_access_token_not_expired(None))

    def test_no_token_returns_false(self):
        payload = {"access_token_expires_at": time.time() + 3600}
        self.assertFalse(TPlusOpenAPIClient._cached_access_token_not_expired(payload))

    def test_token_in_skew_window_but_not_expired_returns_true(self):
        """Token within refresh skew but not truly expired -> returns True."""
        payload = {
            "access_token": "token123",
            "access_token_expires_at": time.time() + 200,  # within 600s skew
        }
        self.assertTrue(TPlusOpenAPIClient._cached_access_token_not_expired(payload))

    def test_uses_expires_at_fallback_key(self):
        payload = {
            "access_token": "token123",
            "expires_at": time.time() + 3600,
        }
        self.assertTrue(TPlusOpenAPIClient._cached_access_token_not_expired(payload))


if __name__ == "__main__":
    unittest.main()
