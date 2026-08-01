"""Tests for the JSON + HTML report generator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from profile_engine.config import EngineConfig, OutputConfig
from profile_engine.heatmap import build_heatmap
from profile_engine.metrics import LanguageShare, Snapshot, Streak
from profile_engine.models import ContributionDay, Language, Repository
from profile_engine.report import SCHEMA_VERSION, build_payload, render_html, render_json

UTC = timezone.utc


def text_between(haystack: str, start: str, end: str) -> str:
    return haystack.split(start, 1)[1].split(end, 1)[0]


def make_snapshot() -> Snapshot:
    repo = Repository(
        name="omni-agent-ai",
        description="agent runtime",
        stars=12,
        forks=2,
        watchers=2,
        issues=1,
        commits=94,
        disk_usage_kb=1600,
        topics=("ai",),
        pushed_at=datetime.now(tz=UTC) - timedelta(days=1),
        created_at=datetime.now(tz=UTC) - timedelta(days=200),
        is_fork=False,
        is_archived=False,
        languages=(Language("Python", "#3572A5", 900),),
        url="https://github.com/u/omni-agent-ai",
    )
    return Snapshot(
        login="majid-alsakani",
        public_repos=11,
        active_repos=4,
        total_stars=24,
        total_forks=3,
        total_commits=170,
        total_kb=34000,
        followers=9,
        languages=(LanguageShare("Python", "#3572A5", 900, 62.5),),
        streak=Streak(current=4, longest=12, total=310, best_day=19),
        top_repositories=(repo,),
        impact_score=57,
    )


def make_heatmap():
    from datetime import date

    days = [ContributionDay(day=date(2026, 1, 5) + timedelta(days=i), count=i % 5) for i in range(30)]
    return build_heatmap(days)


def test_payload_shape_is_stable() -> None:
    payload = build_payload(make_snapshot(), make_heatmap())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["totals"]["commits"] == 170
    assert payload["heatmap"]["weeks"] >= 4
    assert len(payload["heatmap"]["days"]) == 30
    assert set(payload["heatmap"]["per_weekday"]) == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_json_round_trips_and_is_sorted() -> None:
    payload = build_payload(make_snapshot(), make_heatmap())
    text = render_json(payload)
    assert text.endswith("\n")
    assert json.loads(text)["login"] == "majid-alsakani"


def test_html_is_self_contained_and_seo_ready() -> None:
    config = EngineConfig(output=OutputConfig(site_url="https://example.com/report/"))
    payload = build_payload(make_snapshot(), make_heatmap(), config=config)
    html = render_html(payload, config=config)

    assert html.startswith("<!doctype html>")
    assert "https://cdn" not in html and "<script src=" not in html
    assert 'rel="canonical"' in html
    assert 'application/ld+json' in html
    assert 'property="og:title"' in html
    assert "window.__REPORT__" in html
    assert json.loads(text_between(html, "window.__REPORT__ = ", ";</script>"))["login"]


def test_html_survives_hostile_values() -> None:
    snapshot = make_snapshot()
    hostile = snapshot.top_repositories[0].__class__(
        **{
            **{f.name: getattr(snapshot.top_repositories[0], f.name)
               for f in snapshot.top_repositories[0].__dataclass_fields__.values()},
            "name": '<img src=x onerror="alert(1)">',
        }
    )
    snapshot = Snapshot(
        **{**{f: getattr(snapshot, f) for f in snapshot.__dataclass_fields__},
           "top_repositories": (hostile,)}
    )
    html = render_html(build_payload(snapshot, make_heatmap()))
    markup = html.split("window.__REPORT__")[0]
    assert "<img src=x" not in markup
    assert "&lt;img src=x" in markup


def test_embedded_payload_cannot_break_out_of_the_script_tag() -> None:
    snapshot = make_snapshot()
    payload = build_payload(snapshot, make_heatmap())
    payload["login"] = "a</script><script>alert(1)</script>"
    html = render_html(payload)
    tail = html.split("window.__REPORT__")[1]
    assert "</script><script>alert(1)" not in tail
    assert "<\\/script>" in tail
