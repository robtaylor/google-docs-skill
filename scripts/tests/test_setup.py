"""Tests for setup/environment detection module."""

import pytest
from google_docs.setup import check_environment


class TestCheckEnvironment:
    def test_returns_status_dict(self):
        result = check_environment()
        assert "status" in result
        assert "checks" in result
        assert result["status"] in ("ready", "setup_needed")

    def test_has_all_check_keys(self):
        result = check_environment()
        expected_keys = {"uv", "python", "venv", "dependencies", "google_credentials", "google_token", "mmdc"}
        assert set(result["checks"].keys()) == expected_keys

    def test_each_check_has_ok_field(self):
        result = check_environment()
        for name, check in result["checks"].items():
            assert "ok" in check, f"Check '{name}' missing 'ok' field"
            assert isinstance(check["ok"], bool)
