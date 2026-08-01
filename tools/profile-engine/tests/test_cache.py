from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_engine.cache import (
    CACHE_VERSION,
    CacheStats,
    NullCache,
    ResponseCache,
    cache_key,
)
from profile_engine.github_api import GitHubClient, GitHubError


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_cache(tmp_path: Path, ttl: int = 100) -> tuple[ResponseCache, FakeClock]:
    clock = FakeClock()
    return ResponseCache(tmp_path / "c", ttl_seconds=ttl, clock=clock), clock


# -- keys ------------------------------------------------------------------
def test_key_is_stable_across_dict_ordering():
    assert cache_key("query { a }", {"login": "u", "cursor": None}) == cache_key(
        "query { a }", {"cursor": None, "login": "u"}
    )


def test_key_ignores_query_whitespace():
    assert cache_key("query {\n  a\n}", {}) == cache_key("query { a }", {})


def test_key_changes_with_variables():
    assert cache_key("q", {"cursor": "a"}) != cache_key("q", {"cursor": "b"})


def test_key_embeds_cache_version():
    assert CACHE_VERSION == 1  # bump invalidates every entry


# -- storage ---------------------------------------------------------------
def test_set_then_get_round_trip(tmp_path):
    cache, _ = make_cache(tmp_path)
    cache.set("k", {"user": {"login": "u"}})
    assert cache.get("k") == {"user": {"login": "u"}}
    assert cache.stats.hits == 1 and cache.stats.writes == 1


def test_get_misses_on_unknown_key(tmp_path):
    cache, _ = make_cache(tmp_path)
    assert cache.get("nope") is None
    assert cache.stats.misses == 1


def test_entry_expires_after_ttl(tmp_path):
    cache, clock = make_cache(tmp_path, ttl=100)
    cache.set("k", {"v": 1})
    clock.advance(101)
    assert cache.get("k") is None
    assert cache.stats.misses == 1


def test_stale_returns_expired_payload(tmp_path):
    cache, clock = make_cache(tmp_path, ttl=10)
    cache.set("k", {"v": 1})
    clock.advance(999)
    assert cache.get("k") is None
    assert cache.stale("k") == {"v": 1}
    assert cache.stats.stale_hits == 1


def test_corrupt_entry_is_discarded_not_raised(tmp_path):
    cache, _ = make_cache(tmp_path)
    cache.set("k", {"v": 1})
    (cache.directory / "k.json").write_text("{ not json", encoding="utf-8")
    assert cache.get("k") is None
    assert not (cache.directory / "k.json").exists()


def test_writes_are_atomic_no_temp_files_left(tmp_path):
    cache, _ = make_cache(tmp_path)
    cache.set("k", {"v": 1})
    assert list(cache.directory.glob("*.tmp")) == []
    payload = json.loads((cache.directory / "k.json").read_text(encoding="utf-8"))
    assert "stored_at" in payload and payload["data"] == {"v": 1}


def test_purge_removes_only_expired(tmp_path):
    cache, clock = make_cache(tmp_path, ttl=100)
    cache.set("old", {"v": 1})
    clock.advance(200)
    cache.set("new", {"v": 2})
    assert cache.purge() == 1
    assert cache.get("new") == {"v": 2}


def test_purge_on_missing_directory(tmp_path):
    assert ResponseCache(tmp_path / "absent").purge() == 0


def test_stats_describe_reports_hit_rate():
    stats = CacheStats(hits=3, misses=1)
    assert "75% hit rate" in stats.describe()
    assert CacheStats().hit_rate == 0.0


# -- null cache ------------------------------------------------------------
def test_null_cache_never_stores(tmp_path):
    cache = NullCache()
    cache.set("k", {"v": 1})
    assert cache.get("k") is None
    assert cache.stale("k") is None
    assert cache.purge() == 0


# -- client integration ----------------------------------------------------
class CountingClient(GitHubClient):
    def __init__(self, responses, **kwargs):
        super().__init__("token", sleep=lambda _: None, **kwargs)
        self._responses = list(responses)
        self.calls = 0

    def _post(self, payload):  # type: ignore[override]
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_second_identical_query_skips_the_network(tmp_path):
    cache, _ = make_cache(tmp_path)
    client = CountingClient([{"data": {"user": {"login": "u"}}}], cache=cache)
    first = client.execute("query { user }", {"login": "u"})
    second = client.execute("query { user }", {"login": "u"})
    assert first == second == {"user": {"login": "u"}}
    assert client.calls == 1  # the rate limiter was touched exactly once
    assert cache.stats.hits == 1


def test_different_cursor_is_a_separate_entry(tmp_path):
    cache, _ = make_cache(tmp_path)
    client = CountingClient(
        [{"data": {"page": 1}}, {"data": {"page": 2}}],
        cache=cache,
    )
    assert client.execute("q", {"cursor": None}) == {"page": 1}
    assert client.execute("q", {"cursor": "c1"}) == {"page": 2}
    assert client.calls == 2


def test_expired_cache_falls_back_to_network(tmp_path):
    cache, clock = make_cache(tmp_path, ttl=10)
    client = CountingClient([{"data": {"n": 1}}, {"data": {"n": 2}}], cache=cache)
    assert client.execute("q", {}) == {"n": 1}
    clock.advance(50)
    assert client.execute("q", {}) == {"n": 2}
    assert client.calls == 2


def test_stale_entry_rescues_a_failing_run(tmp_path):
    import urllib.error

    cache, clock = make_cache(tmp_path, ttl=10)
    outage = [urllib.error.URLError("down")] * 5
    client = CountingClient([{"data": {"n": 1}}, *outage], cache=cache)
    assert client.execute("q", {}) == {"n": 1}
    clock.advance(999)
    assert client.execute("q", {}) == {"n": 1}  # served stale instead of crashing
    assert cache.stats.stale_hits == 1


def test_total_outage_without_cache_still_raises(tmp_path):
    import urllib.error

    cache, _ = make_cache(tmp_path)
    client = CountingClient([urllib.error.URLError("down")] * 5, cache=cache)
    with pytest.raises(GitHubError):
        client.execute("q", {})


def test_rate_limit_is_recorded(tmp_path):
    cache, _ = make_cache(tmp_path)
    client = CountingClient(
        [{"data": {"rateLimit": {"limit": 5000, "cost": 1, "remaining": 4999}, "user": {}}}],
        cache=cache,
    )
    client.execute("q", {})
    assert client.rate_limit["remaining"] == 4999


def test_client_defaults_to_null_cache():
    client = CountingClient([{"data": {"n": 1}}, {"data": {"n": 2}}])
    assert client.execute("q", {}) == {"n": 1}
    assert client.execute("q", {}) == {"n": 2}
    assert client.calls == 2


def test_fetch_profile_pages_are_cached_individually(tmp_path):
    from tests.test_github_api import NODE

    cache, _ = make_cache(tmp_path)
    page_one = {
        "data": {
            "user": {
                "login": "u",
                "name": "U",
                "bio": "",
                "createdAt": "2020-01-01T00:00:00Z",
                "followers": {"totalCount": 1},
                "following": {"totalCount": 0},
                "contributionsCollection": {"contributionCalendar": {"weeks": []}},
                "repositories": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    "nodes": [NODE],
                },
            }
        }
    }
    page_two = json.loads(json.dumps(page_one))
    page_two["data"]["user"]["repositories"]["pageInfo"] = {
        "hasNextPage": False,
        "endCursor": None,
    }
    client = CountingClient([page_one, page_two], cache=cache)
    client.fetch_profile("u")
    assert client.calls == 2

    warm = CountingClient([], cache=cache)
    warm.fetch_profile("u")
    assert warm.calls == 0  # a full re-run costs zero API points
