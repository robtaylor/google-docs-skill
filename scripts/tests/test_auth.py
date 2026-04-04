"""Tests for auth module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from google_docs.auth import _load_ruby_token, _save_credentials, SCOPES


class TestLoadRubyToken:
    def test_missing_file_returns_none(self):
        with patch("google_docs.auth.TOKEN_PATH", Path("/nonexistent/token.json")):
            assert _load_ruby_token() is None

    def test_ruby_format_parsed(self, tmp_path):
        token_data = {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "refresh_token": "test_refresh",
            "access_token": "test_access",
        }
        store = {"default": json.dumps(token_data)}
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps(store))

        with patch("google_docs.auth.TOKEN_PATH", token_file):
            result = _load_ruby_token()

        assert result is not None
        assert result["client_id"] == "test_id"
        assert result["refresh_token"] == "test_refresh"

    def test_malformed_json_returns_none(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("not json")

        with patch("google_docs.auth.TOKEN_PATH", token_file):
            assert _load_ruby_token() is None


class TestSaveCredentials:
    def test_saves_in_ruby_format(self, tmp_path):
        from unittest.mock import MagicMock

        creds = MagicMock()
        creds.client_id = "cid"
        creds.client_secret = "csec"
        creds.token = "tok"
        creds.refresh_token = "rtok"
        creds.token_uri = "https://oauth2.googleapis.com/token"
        creds.expiry = None

        token_file = tmp_path / "token.json"
        with patch("google_docs.auth.TOKEN_PATH", token_file):
            _save_credentials(creds)

        data = json.loads(token_file.read_text())
        assert "default" in data
        inner = json.loads(data["default"])
        assert inner["client_id"] == "cid"
        assert inner["access_token"] == "tok"

    def test_file_permissions_600(self, tmp_path):
        from unittest.mock import MagicMock
        import stat

        creds = MagicMock()
        creds.client_id = "cid"
        creds.client_secret = "csec"
        creds.token = "tok"
        creds.refresh_token = "rtok"
        creds.token_uri = "https://oauth2.googleapis.com/token"
        creds.expiry = None

        token_file = tmp_path / "token.json"
        with patch("google_docs.auth.TOKEN_PATH", token_file):
            _save_credentials(creds)

        mode = token_file.stat().st_mode & 0o777
        assert mode == 0o600


class TestScopes:
    def test_has_required_scopes(self):
        assert len(SCOPES) == 6
        assert "https://www.googleapis.com/auth/documents" in SCOPES
        assert "https://www.googleapis.com/auth/drive" in SCOPES
