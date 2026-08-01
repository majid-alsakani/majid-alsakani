"""A tiny content-addressed response cache for GraphQL queries.

The scheduled workflow runs four times a day and re-reads the same repository
pages every run. Each page costs GraphQL rate-limit points, and a secondary
rate limit mid-run leaves the README half-updated. This layer removes that
pressure:

* **Fresh hit** — a stored entry younger than the TTL is returned without any
  network call at all.
* **Stale fallback** — when the API is unreachable or rate-limited, an expired
  entry is still better than a failed run, so `stale()` hands it back.
* **Atomic writes** — entries are written to a temp file and `os.replace`d, so a
  cancelled workflow can never leave a half-written JSON blob behind.

Standard library only, no daemon, no server: the cache is a directory of JSON
files that GitHub Actions restores between runs with `actions/cache`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger("profile_engine.cache")

DEFAULT_TTL_SECONDS = 60 * 60 * 3  # three hours — shorter than the 6h schedule
CACHE_VERSION = 1
"""Bumping this invalidates every entry without deleting the directory."""


def cache_key(query: str, variables: Mapping[str, Any]) -> str:
    """Stable key for a query + variables pair.

    `sort_keys` makes the digest independent of dict ordering, so the same
    logical request always maps to the same file.
    """
    payload = json.dumps(
        {"v": CACHE_VERSION, "q": " ".join(query.split()), "vars": variables},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CacheStats:
    """Counters surfaced in the run log so cache value is measurable."""

    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    writes: int = 0

    @property
    def requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return (self.hits / self.requests * 100.0) if self.requests else 0.0

    def describe(self) -> str:
        return (
            f"{self.hits} hit(s), {self.misses} miss(es), {self.stale_hits} stale fallback(s), "
            f"{self.writes} write(s) — {self.hit_rate:.0f}% hit rate"
        )

    def as_dict(self) -> dict[str, float | int]:
        """Machine-readable counters for the JSON report and README block."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "writes": self.writes,
            "requests": self.requests,
            "hit_rate_percent": round(self.hit_rate, 1),
        }



class ResponseCache:
    """Filesystem-backed TTL cache. Every failure mode degrades to a miss."""

    def __init__(
        self,
        directory: Path | str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock=time.time,
    ) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._clock = clock
        self.stats = CacheStats()

    # -- paths -------------------------------------------------------------
    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def _read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # A corrupt entry must never take the run down.
            LOGGER.warning("Discarding unreadable cache entry %s", path.name)
            self.discard(key)
            return None
        if not isinstance(entry, dict) or "data" not in entry:
            return None
        return entry

    # -- api ---------------------------------------------------------------
    def get(self, key: str) -> dict[str, Any] | None:
        """Return the payload when a non-expired entry exists."""
        entry = self._read(key)
        if entry is None:
            self.stats.misses += 1
            return None
        age = self._clock() - float(entry.get("stored_at") or 0)
        if age > self.ttl_seconds:
            LOGGER.debug("Cache entry %s expired (%.0fs old)", key[:8], age)
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        LOGGER.debug("Cache hit %s (%.0fs old)", key[:8], age)
        return entry["data"]

    def stale(self, key: str) -> dict[str, Any] | None:
        """Return an expired payload — last resort when the API fails."""
        entry = self._read(key)
        if entry is None:
            return None
        self.stats.stale_hits += 1
        LOGGER.warning("Serving STALE cache entry %s — GitHub was unavailable.", key[:8])
        return entry["data"]

    def set(self, key: str, data: Mapping[str, Any]) -> None:
        """Persist a payload atomically; storage problems are non-fatal."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"stored_at": self._clock(), "data": data}, stream)
            os.replace(temp_name, self._path(key))
            self.stats.writes += 1
        except OSError as exc:  # pragma: no cover - filesystem edge case
            LOGGER.warning("Could not write cache entry %s: %s", key[:8], exc)

    def discard(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def purge(self, *, max_age_seconds: int | None = None) -> int:
        """Delete expired entries. Returns how many files were removed."""
        limit = self.ttl_seconds if max_age_seconds is None else max_age_seconds
        removed = 0
        if not self.directory.is_dir():
            return 0
        now = self._clock()
        for path in self.directory.glob("*.json"):
            try:
                stored = float(json.loads(path.read_text(encoding="utf-8")).get("stored_at") or 0)
            except (OSError, ValueError):
                stored = 0.0
            if now - stored > limit:
                path.unlink(missing_ok=True)
                removed += 1
        if removed:
            LOGGER.info("Purged %d expired cache entr%s.", removed, "y" if removed == 1 else "ies")
        return removed


@dataclass(slots=True)
class NullCache:
    """Drop-in no-op used by `--no-cache`; keeps the client branch-free."""

    stats: CacheStats = field(default_factory=CacheStats)

    def get(self, key: str) -> dict[str, Any] | None:
        self.stats.misses += 1
        return None

    def stale(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, data: Mapping[str, Any]) -> None:
        return None

    def discard(self, key: str) -> None:
        return None

    def purge(self, *, max_age_seconds: int | None = None) -> int:
        return 0
