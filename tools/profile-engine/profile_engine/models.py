"""Typed domain models for the profile engine.

Every value that crosses a module boundary is one of these frozen dataclasses,
so the renderer can never be handed a raw, unvalidated API payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class Language:
    """A single language slice of a repository."""

    name: str
    color: str
    size: int

    @property
    def safe_color(self) -> str:
        """Never let an upstream value leak raw into generated SVG."""
        if self.color.startswith("#") and len(self.color) in (4, 7):
            allowed = set("0123456789abcdefABCDEF")
            if all(c in allowed for c in self.color[1:]):
                return self.color
        return "#8b949e"


@dataclass(frozen=True, slots=True)
class Repository:
    """A repository reduced to the facts the engine actually reasons about."""

    name: str
    description: str | None
    stars: int
    forks: int
    watchers: int
    issues: int
    commits: int
    disk_usage_kb: int
    topics: tuple[str, ...]
    pushed_at: datetime
    created_at: datetime
    is_fork: bool
    is_archived: bool
    languages: tuple[Language, ...]
    url: str

    @property
    def primary_language(self) -> str:
        if not self.languages:
            return "Other"
        return max(self.languages, key=lambda language: language.size).name

    @property
    def age_days(self) -> int:
        return max((_utc_now() - self.created_at).days, 0)

    @property
    def days_since_push(self) -> int:
        return max((_utc_now() - self.pushed_at).days, 0)

    @property
    def is_active(self) -> bool:
        return self.days_since_push <= 30 and not self.is_archived

    @property
    def total_language_bytes(self) -> int:
        return sum(language.size for language in self.languages)


@dataclass(frozen=True, slots=True)
class ContributionDay:
    """One cell of the contribution calendar."""

    day: date
    count: int


@dataclass(frozen=True, slots=True)
class Profile:
    """The account-level snapshot."""

    login: str
    name: str
    bio: str
    followers: int
    following: int
    created_at: datetime
    repositories: tuple[Repository, ...] = field(default_factory=tuple)
    contributions: tuple[ContributionDay, ...] = field(default_factory=tuple)

    @property
    def owned(self) -> tuple[Repository, ...]:
        return tuple(repo for repo in self.repositories if not repo.is_fork)


def parse_iso8601(value: str) -> datetime:
    """Parse GitHub's `Z`-suffixed timestamps into aware datetimes."""
    normalised = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def repository_from_graphql(node: Mapping[str, Any]) -> Repository:
    """Map one GraphQL repository node onto :class:`Repository` defensively."""
    languages_edges: Iterable[Mapping[str, Any]] = (
        (node.get("languages") or {}).get("edges") or []
    )
    languages = tuple(
        Language(
            name=str((edge.get("node") or {}).get("name") or "Other"),
            color=str((edge.get("node") or {}).get("color") or "#8b949e"),
            size=_int(edge.get("size")),
        )
        for edge in languages_edges
    )

    history = ((node.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}
    topics = tuple(
        str(((entry or {}).get("topic") or {}).get("name") or "")
        for entry in ((node.get("repositoryTopics") or {}).get("nodes") or [])
    )

    return Repository(
        name=str(node.get("name") or "unknown"),
        description=node.get("description"),
        stars=_int((node.get("stargazers") or {}).get("totalCount")),
        forks=_int(node.get("forkCount")),
        watchers=_int((node.get("watchers") or {}).get("totalCount")),
        issues=_int((node.get("issues") or {}).get("totalCount")),
        commits=_int(history.get("totalCount")),
        disk_usage_kb=_int(node.get("diskUsage")),
        topics=tuple(topic for topic in topics if topic),
        pushed_at=parse_iso8601(str(node.get("pushedAt") or node.get("updatedAt") or "1970-01-01T00:00:00Z")),
        created_at=parse_iso8601(str(node.get("createdAt") or "1970-01-01T00:00:00Z")),
        is_fork=bool(node.get("isFork")),
        is_archived=bool(node.get("isArchived")),
        languages=languages,
        url=str(node.get("url") or ""),
    )
