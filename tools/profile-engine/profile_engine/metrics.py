"""Derived analytics: everything the README shows is computed here, not fetched.

Pure functions over :mod:`profile_engine.models` — no I/O, fully unit testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from .models import ContributionDay, Language, Profile, Repository


@dataclass(frozen=True, slots=True)
class LanguageShare:
    name: str
    color: str
    bytes_: int
    percent: float


@dataclass(frozen=True, slots=True)
class Streak:
    current: int
    longest: int
    total: int
    best_day: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The complete set of numbers rendered into the README."""

    login: str
    public_repos: int
    active_repos: int
    total_stars: int
    total_forks: int
    total_commits: int
    total_kb: int
    followers: int
    languages: tuple[LanguageShare, ...]
    streak: Streak
    top_repositories: tuple[Repository, ...]
    impact_score: int


def language_shares(repositories: Iterable[Repository], *, limit: int = 8) -> tuple[LanguageShare, ...]:
    """Aggregate byte counts per language and normalise to percentages."""
    totals: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in repositories:
        if repo.is_fork:
            continue
        for language in repo.languages:
            totals[language.name] = totals.get(language.name, 0) + max(language.size, 0)
            colors.setdefault(language.name, Language(language.name, language.color, 0).safe_color)

    grand_total = sum(totals.values())
    if grand_total <= 0:
        return ()

    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    return tuple(
        LanguageShare(
            name=name,
            color=colors.get(name, "#8b949e"),
            bytes_=size,
            percent=round(size * 100 / grand_total, 2),
        )
        for name, size in ordered
    )


def contribution_streak(days: Sequence[ContributionDay], *, today: date | None = None) -> Streak:
    """Current streak tolerates "today has no commit yet"; longest never does."""
    if not days:
        return Streak(current=0, longest=0, total=0, best_day=0)

    ordered = sorted(days, key=lambda entry: entry.day)
    by_day = {entry.day: entry.count for entry in ordered}
    total = sum(by_day.values())
    best_day = max(by_day.values())

    longest = 0
    running = 0
    previous: date | None = None
    for entry in ordered:
        if entry.count > 0 and previous is not None and entry.day - previous == timedelta(days=1):
            running += 1
        elif entry.count > 0:
            running = 1
        else:
            running = 0
        previous = entry.day if entry.count > 0 else None
        longest = max(longest, running)

    reference = today or ordered[-1].day
    cursor = reference
    if by_day.get(cursor, 0) == 0:
        cursor -= timedelta(days=1)
    current = 0
    while by_day.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    return Streak(current=current, longest=longest, total=total, best_day=best_day)


def impact_score(profile: Profile) -> int:
    """A deliberately simple, explainable 0-100 engineering-footprint score.

    Weighted so that *sustained shipping* outranks vanity metrics: commits and
    recent activity dominate, stars contribute with diminishing returns.
    """
    owned = profile.owned
    if not owned:
        return 0

    commits = sum(repo.commits for repo in owned)
    stars = sum(repo.stars for repo in owned)
    active = sum(1 for repo in owned if repo.is_active)
    documented = sum(1 for repo in owned if (repo.description or "").strip())

    def saturate(value: float, ceiling: float) -> float:
        return min(value, ceiling) / ceiling

    score = (
        saturate(commits, 400) * 40
        + saturate(stars, 100) * 15
        + saturate(active, 6) * 20
        + saturate(documented / max(len(owned), 1) * 10, 10) * 15
        + saturate(len(owned), 15) * 10
    )
    return int(round(score))


def build_snapshot(profile: Profile, *, top: int = 6) -> Snapshot:
    owned = profile.owned
    ranked = sorted(
        owned,
        key=lambda repo: (repo.stars * 10 + repo.commits, -repo.days_since_push),
        reverse=True,
    )[:top]

    return Snapshot(
        login=profile.login,
        public_repos=len(owned),
        active_repos=sum(1 for repo in owned if repo.is_active),
        total_stars=sum(repo.stars for repo in owned),
        total_forks=sum(repo.forks for repo in owned),
        total_commits=sum(repo.commits for repo in owned),
        total_kb=sum(repo.disk_usage_kb for repo in owned),
        followers=profile.followers,
        languages=language_shares(owned),
        streak=contribution_streak(profile.contributions),
        top_repositories=tuple(ranked),
        impact_score=impact_score(profile),
    )
