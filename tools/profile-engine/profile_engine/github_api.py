"""A dependency-free GitHub GraphQL client.

Uses only the standard library so the workflow needs no `pip install` step and
cannot break because of a transitive dependency. Handles rate limiting,
secondary-rate-limit backoff, cursor pagination, partial GraphQL errors and a
TTL response cache that keeps repeat runs off the rate limiter entirely.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol

from .cache import NullCache, cache_key
from .models import ContributionDay, Profile, Repository, parse_iso8601, repository_from_graphql

LOGGER = logging.getLogger("profile_engine.github")

ENDPOINT = "https://api.github.com/graphql"
MAX_ATTEMPTS = 5
PAGE_SIZE = 50


class SupportsCache(Protocol):
    """Structural type shared by ResponseCache and NullCache."""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def stale(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, data: Mapping[str, Any]) -> None: ...


PROFILE_QUERY = """
query($login: String!, $cursor: String) {
  rateLimit { limit cost remaining resetAt }
  user(login: $login) {

    login
    name
    bio
    createdAt
    followers { totalCount }
    following { totalCount }
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(
      first: 50
      after: $cursor
      ownerAffiliations: OWNER
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name description url diskUsage forkCount isFork isArchived
        createdAt pushedAt updatedAt
        stargazers { totalCount }
        watchers { totalCount }
        issues(states: OPEN) { totalCount }
        repositoryTopics(first: 20) { nodes { topic { name } } }
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name color } }
        }
        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
      }
    }
  }
}
"""


class GitHubError(RuntimeError):
    """Raised when the API cannot be reached or returns fatal errors."""


class GitHubClient:
    """Minimal, resilient GraphQL client with a TTL response cache."""

    def __init__(
        self,
        token: str,
        *,
        endpoint: str = ENDPOINT,
        sleep=time.sleep,
        cache: SupportsCache | None = None,
    ) -> None:
        if not token:
            raise GitHubError("A GitHub token is required (set GITHUB_TOKEN).")
        self._token = token
        self._endpoint = endpoint
        self._sleep = sleep
        self._cache: SupportsCache = cache if cache is not None else NullCache()
        self.rate_limit: dict[str, Any] = {}

    @property
    def cache(self) -> SupportsCache:
        return self._cache

    # -- transport ---------------------------------------------------------
    def _post(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "profile-engine/1.0 (+https://github.com/majid-alsakani)",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def execute(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Run one query: cache first, then network with backoff, then stale cache."""
        key = cache_key(query, variables)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                document = self._post({"query": query, "variables": dict(variables)})
            except urllib.error.HTTPError as exc:  # pragma: no cover - network path
                last_error = exc
                if exc.code in (403, 429, 500, 502, 503):
                    self._backoff(attempt)
                    continue
                raise GitHubError(f"GitHub returned HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:  # pragma: no cover - network path
                last_error = exc
                self._backoff(attempt)
                continue

            errors = document.get("errors") or []
            fatal = [error for error in errors if error.get("type") != "RATE_LIMITED"]
            if fatal:
                raise GitHubError("; ".join(str(error.get("message")) for error in fatal))
            if errors:
                self._backoff(attempt)
                continue

            data = document.get("data") or {}
            self._record_rate_limit(data)
            self._cache.set(key, data)
            return data

        # Every attempt failed. An expired entry beats a broken README.
        salvaged = self._cache.stale(key)
        if salvaged is not None:
            return salvaged
        raise GitHubError(f"GitHub unreachable after {MAX_ATTEMPTS} attempts: {last_error}")

    def _record_rate_limit(self, data: Mapping[str, Any]) -> None:
        info = data.get("rateLimit")
        if isinstance(info, dict) and info:
            self.rate_limit = dict(info)
            LOGGER.debug(
                "Rate limit: %s/%s remaining (cost %s, resets %s)",
                info.get("remaining"),
                info.get("limit"),
                info.get("cost"),
                info.get("resetAt"),
            )

    def _backoff(self, attempt: int) -> None:
        delay = min(2**attempt, 32) + random.random()
        LOGGER.warning("Backing off %.1fs (attempt %d/%d)", delay, attempt, MAX_ATTEMPTS)
        self._sleep(delay)


    # -- domain ------------------------------------------------------------
    def fetch_profile(self, login: str) -> Profile:
        """Fetch the full profile, following every repository page."""
        cursor: str | None = None
        repositories: list[Repository] = []
        header: dict[str, Any] = {}
        contributions: list[ContributionDay] = []

        while True:
            data = self.execute(PROFILE_QUERY, {"login": login, "cursor": cursor})
            user = data.get("user")
            if not user:
                raise GitHubError(f"No such user: {login}")
            if not header:
                header = user
                calendar = (
                    ((user.get("contributionsCollection") or {}).get("contributionCalendar") or {})
                    .get("weeks")
                    or []
                )
                for week in calendar:
                    for day in week.get("contributionDays") or []:
                        contributions.append(
                            ContributionDay(
                                day=parse_iso8601(f"{day['date']}T00:00:00Z").date(),
                                count=int(day.get("contributionCount") or 0),
                            )
                        )

            block = user.get("repositories") or {}
            repositories.extend(
                repository_from_graphql(node) for node in (block.get("nodes") or []) if node
            )
            page = block.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")

        return Profile(
            login=str(header.get("login") or login),
            name=str(header.get("name") or login),
            bio=str(header.get("bio") or ""),
            followers=int((header.get("followers") or {}).get("totalCount") or 0),
            following=int((header.get("following") or {}).get("totalCount") or 0),
            created_at=parse_iso8601(str(header.get("createdAt") or "1970-01-01T00:00:00Z")),
            repositories=tuple(repositories),
            contributions=tuple(sorted(contributions, key=lambda entry: entry.day)),
        )
