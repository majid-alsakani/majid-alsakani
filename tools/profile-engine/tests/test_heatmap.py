"""Tests for the commit-distribution heatmap."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

from profile_engine.heatmap import PALETTE, build_heatmap, heatmap_svg, weekday_table
from profile_engine.models import ContributionDay


def calendar(counts: list[int], *, start: date = date(2026, 1, 5)) -> list[ContributionDay]:
    return [ContributionDay(day=start + timedelta(days=index), count=count) for index, count in enumerate(counts)]


def test_empty_calendar_is_safe() -> None:
    heat = build_heatmap([])
    assert heat.total == 0
    assert heat.weeks == 0
    assert heat.peak_weekday == "—"
    assert heat.level(5) == 0


def test_grid_placement_and_totals() -> None:
    heat = build_heatmap(calendar([1, 2, 3, 0, 0, 4, 5, 6]))
    assert heat.total == 21
    assert heat.max_cell == 6
    assert heat.weeks >= 2
    # 2026-01-05 is a Monday.
    assert heat.cells[0].weekday == 0
    assert heat.per_weekday[0] == 1 + 6  # both Mondays in the window
    assert heat.busiest_day == date(2026, 1, 12)
    assert heat.busiest_day_count == 6


def test_weekend_share_and_consistency() -> None:
    heat = build_heatmap(calendar([0, 0, 0, 0, 0, 10, 10]))
    assert heat.weekend_share == 100.0
    assert heat.active_days == 2
    assert heat.consistency == round(2 * 100 / 7, 1)


def test_levels_are_relative_to_the_maximum() -> None:
    heat = build_heatmap(calendar([1, 4, 8]))
    assert heat.level(0) == 0
    assert heat.level(8) == 4
    assert 1 <= heat.level(1) <= 2


def test_svg_is_valid_xml_and_escapes_values() -> None:
    heat = build_heatmap(calendar([1, 0, 3, 7]))
    markup = heatmap_svg(heat)
    root = ET.fromstring(markup)
    assert root.tag.endswith("svg")
    assert markup.count("<title>") == len(heat.cells)
    assert PALETTE[4] in markup


def test_weekday_table_rows_and_shares() -> None:
    heat = build_heatmap(calendar([1, 1, 1, 1, 1, 1, 1]))
    table = weekday_table(heat)
    assert len(table.splitlines()) == 7
    assert "14.3%" in table
