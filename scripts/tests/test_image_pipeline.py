"""Tests for image_pipeline module."""

import os
import pytest
from google_docs.image_pipeline import _resolve_file_path


class TestResolveFilePath:
    def test_absolute_path_returned_as_is(self):
        result = _resolve_file_path("/usr/local/img.png", "/tmp/docs")
        assert result == "/usr/local/img.png"

    def test_relative_path_resolved(self):
        result = _resolve_file_path("images/flow.png", "/tmp/docs")
        assert result.endswith("/tmp/docs/images/flow.png")

    def test_traversal_blocked(self):
        with pytest.raises(ValueError, match="escapes base directory"):
            _resolve_file_path("../../etc/passwd", "/tmp/docs")

    def test_double_traversal_blocked(self):
        with pytest.raises(ValueError, match="escapes base directory"):
            _resolve_file_path("../../../root/.ssh/id_rsa", "/tmp/docs/sub")

    def test_dot_path_stays_in_base(self):
        result = _resolve_file_path("./img.png", "/tmp/docs")
        assert result.endswith("/tmp/docs/img.png")

    def test_nested_relative_stays_in_base(self):
        result = _resolve_file_path("sub/dir/img.png", "/tmp/docs")
        assert result.endswith("/tmp/docs/sub/dir/img.png")
