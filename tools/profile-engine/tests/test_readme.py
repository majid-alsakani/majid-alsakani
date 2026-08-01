from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from profile_engine.metrics import LanguageShare, Snapshot, Streak
from profile_engine.models import Language, Repository
from profile_engine.readme import END, START, MarkerError, inject, render_section
from profile_engine.svg import language_card, stats_card

UTC = timezone.utc


def make_snapshot() -> Snapshot:
    repo = Repository(
        name="omni-agent-ai",
        description="agent",
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


def test_injection_is_idempotent():
    readme = f"# Title\n\nhand written\n\n{START}\nold\n{END}\n\nfooter\n"
    section = render_section(make_snapshot(), generated_at=datetime(2026, 8, 1, tzinfo=UTC))
    once = inject(readme, section)
    twice = inject(once, section)
    assert once == twice


def test_injection_preserves_surrounding_content():
    readme = f"# Title\n\nkeep me\n\n{START}\nold\n{END}\n\nkeep me too\n"
    result = inject(readme, render_section(make_snapshot()))
    assert "keep me" in result and "keep me too" in result and "# Title" in result
    assert "old" not in result


def test_injection_appends_when_markers_absent():
    result = inject("# Title\n", render_section(make_snapshot()))
    assert result.startswith("# Title\n")
    assert START in result and END in result


def test_unbalanced_markers_raise():
    with pytest.raises(MarkerError):
        inject(f"# Title\n{START}\nno end\n", render_section(make_snapshot()))


def test_section_contains_live_numbers():
    section = render_section(make_snapshot())
    assert "**170**" in section
    assert "omni-agent-ai" in section
    assert "57/100" in section


def test_svg_cards_are_wellformed_xml():
    from xml.etree import ElementTree

    snapshot = make_snapshot()
    for markup in (stats_card(snapshot), language_card(snapshot.languages)):
        root = ElementTree.fromstring(markup)
        assert root.tag.endswith("svg")


def test_svg_escapes_hostile_language_names():
    hostile = (LanguageShare('<script>"x"', "#3572A5", 1, 100.0),)
    markup = language_card(hostile)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_language_card_handles_empty_input():
    from xml.etree import ElementTree

    ElementTree.fromstring(language_card(()))
