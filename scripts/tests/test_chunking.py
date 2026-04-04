"""Tests for chunking and rate limiting in markdown_to_docs."""

import json
import time

import pytest
from google_docs.markdown_to_docs import RateLimiter, chunk_requests


class TestChunkRequests:
    def test_empty_requests(self):
        assert chunk_requests([]) == []

    def test_single_small_request(self):
        reqs = [{"insertText": {"text": "hello", "location": {"index": 1}}}]
        chunks = chunk_requests(reqs)
        assert len(chunks) == 1
        assert chunks[0] == reqs

    def test_splits_at_size_limit(self):
        # Create requests that are ~1KB each
        reqs = [
            {"insertText": {"text": "x" * 900, "location": {"index": i}}}
            for i in range(10)
        ]
        # With 4KB limit, should split into multiple chunks
        chunks = chunk_requests(reqs, max_bytes=4000)
        assert len(chunks) > 1
        # All requests accounted for
        total = sum(len(c) for c in chunks)
        assert total == 10

    def test_each_chunk_under_limit(self):
        reqs = [
            {"insertText": {"text": "x" * 500, "location": {"index": i}}}
            for i in range(20)
        ]
        max_bytes = 2000
        chunks = chunk_requests(reqs, max_bytes=max_bytes)
        for chunk in chunks:
            size = len(json.dumps(chunk).encode("utf-8"))
            # Each chunk should be under limit (with some tolerance for single large items)
            assert size <= max_bytes + 1000  # Allow one item overflow

    def test_single_oversized_request(self):
        # A single request larger than max_bytes should still be in its own chunk
        big_req = {"insertText": {"text": "x" * 10000, "location": {"index": 1}}}
        chunks = chunk_requests([big_req], max_bytes=1000)
        assert len(chunks) == 1
        assert chunks[0] == [big_req]

    def test_preserves_order(self):
        reqs = [{"id": i} for i in range(5)]
        chunks = chunk_requests(reqs, max_bytes=100)
        flat = [r for chunk in chunks for r in chunk]
        assert [r["id"] for r in flat] == [0, 1, 2, 3, 4]


class TestRateLimiter:
    def test_first_call_no_wait(self):
        limiter = RateLimiter(max_per_minute=55)
        start = time.time()
        limiter.wait_if_needed()
        elapsed = time.time() - start
        assert elapsed < 0.1

    def test_tracks_timestamps(self):
        limiter = RateLimiter(max_per_minute=55)
        limiter.wait_if_needed()
        assert len(limiter._timestamps) == 1

    def test_multiple_calls_under_limit(self):
        limiter = RateLimiter(max_per_minute=100)
        for _ in range(5):
            limiter.wait_if_needed()
        assert len(limiter._timestamps) == 5
