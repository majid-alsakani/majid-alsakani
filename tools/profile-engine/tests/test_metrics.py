from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from profile_engine.metrics import (
    build_snapshot,
    contribution_streak,
    impact_score,
    language_shares,
)
from profile_engine.models import ContributionDay, Language, Profile, Repository

UTC = timezone.utc


def make_repo(name: str, **overrides) -> Repository:
    base = dict(
        name=name,
        description="a repo",
        stars=3,
        forks=1,
        watchers=1,
        issues=0,
        commits=10,
        disk_usage_kb=100,
        topics=("python",),
        pushed_at=datetime.now(tz=UTC) - timedelta(days=2),
        created_at=datetime.now(tz=UTC) - timedelta(days=400),
        is_fork=False,
        is_archived=False,
        languages=(Language("Python", "#3572A5", 1000),),
        url=f"https://github.com/x/{name}",
    )
    base.update(overrides)
    return Repository(**base)


def test_language_shares_sum_to_100():
    repos = [
        make_repo("a", languages=(Language("Python", "#3572A5", 750),)),
        make_repo("b", languages=(Language("TypeScript", "#3178c6", 250),)),
    ]
    shares = language_shares(repos)
    assert [s.name for s in shares] == ["Python", "TypeScript"]
    assert abs(sum(s.percent for s in shares) - 100.0) < 0.01


def test_language_shares_ignores_forks():
    repos = [make_repo("fork", is_fork=True)]
    assert language_shares(repos) == ()


def test_unsafe_language_color_is_replaced():
    assert Language("X", "javascript:alert(1)", 1).safe_color == "#8b949e"
    assert Language("X", "#3572A5", 1).safe_color == "#3572A5"


def test_streak_counts_consecutive_days():
    today = date(2026, 8, 1)
    days = [ContributionDay(today - timedelta(days=i), 1 if i < 5 else 0) for i in range(10)]
    streak = contribution_streak(days, today=today)
    assert streak.current == 5
    assert streak.longest == 5
    assert streak.total == 5


def test_streak_tolerates_empty_today():
    today = date(2026, 8, 1)
    days = [ContributionDay(today, 0)] + [
        ContributionDay(today - timedelta(days=i), 2) for i in range(1, 4)
    ]
    assert contribution_streak(days, today=today).current == 3


def test_streak_on_empty_input():
    assert contribution_streak([]).current == 0


def test_impact_score_is_bounded():
    profile = Profile(
        login="u",
        name="U",
        bio="",
        followers=10,
        following=1,
        created_at=datetime.now(tz=UTC),
        repositories=tuple(make_repo(f"r{i}", commits=500, stars=500) for i in range(30)),
    )
    assert 0 <= impact_score(profile) <= 100


def test_impact_score_empty_profile_is_zero():
    profile = Profile("u", "U", "", 0, 0, datetime.now(tz=UTC))
    assert impact_score(profile) == 0


def test_snapshot_ranks_top_repositories():
    profile = Profile(
        login="u",
        name="U",
        bio="",
        followers=5,
        following=0,
        created_at=datetime.now(tz=UTC),
        repositories=(
            make_repo("small", stars=0, commits=1),
            make_repo("big", stars=50, commits=90),
        ),
    )
    snapshot = build_snapshot(profile)
    assert snapshot.top_repositories[0].name == "big"
    assert snapshot.total_stars == 50
    assert snapshot.active_repos == 2
