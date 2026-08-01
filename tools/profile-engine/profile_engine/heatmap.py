"""Commit distribution analytics: weekday x week heatmap.

The contribution calendar GitHub returns is a flat list of days. Everything a
human wants to *know* from it — which weekday you actually ship on, whether the
last month was a slump, how concentrated your work is — has to be derived.
This module does that derivation as pure functions, then renders the result
twice: once as an accessible SVG grid, once as a compact markdown table.

Standard library only, no I/O, fully unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from typing import Sequence

from .models import ContributionDay

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
"""Index 0..6 matches :meth:`datetime.date.weekday`."""

MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


@dataclass(frozen=True, slots=True)
class HeatmapCell:
    """One day of the grid, already placed on the (week, weekday) plane."""

    day: date
    count: int
    week_index: int
    weekday: int

    @property
    def is_weekend(self) -> bool:
        return self.weekday >= 5


@dataclass(frozen=True, slots=True)
class Heatmap:
    """A fully derived commit-distribution model.

    ``cells`` is sparse-safe: missing days simply do not appear, and every
    consumer reads the aggregates instead of re-scanning the raw calendar.
    """

    cells: tuple[HeatmapCell, ...]
    weeks: int
    start: date
    end: date
    per_weekday: tuple[int, ...]
    per_week: tuple[int, ...]
    total: int
    busiest_day: date | None
    busiest_day_count: int
    max_cell: int

    @property
    def peak_weekday(self) -> str:
        if not any(self.per_weekday):
            return "—"
        return WEEKDAY_NAMES[max(range(7), key=lambda i: self.per_weekday[i])]

    @property
    def quietest_weekday(self) -> str:
        if not any(self.per_weekday):
            return "—"
        return WEEKDAY_NAMES[min(range(7), key=lambda i: self.per_weekday[i])]

    @property
    def active_days(self) -> int:
        return sum(1 for cell in self.cells if cell.count > 0)

    @property
    def weekend_share(self) -> float:
        """Percent of contributions made on Sat/Sun — a real work-pattern signal."""
        if self.total <= 0:
            return 0.0
        weekend = self.per_weekday[5] + self.per_weekday[6]
        return round(weekend * 100 / self.total, 1)

    @property
    def daily_average(self) -> float:
        span = max((self.end - self.start).days + 1, 1)
        return round(self.total / span, 2)

    @property
    def consistency(self) -> float:
        """Share of days in the window with at least one contribution."""
        span = max((self.end - self.start).days + 1, 1)
        return round(self.active_days * 100 / span, 1)

    def level(self, count: int, *, buckets: int = 4) -> int:
        """Map a raw count onto 0..buckets using the observed maximum.

        Relative bucketing (not fixed thresholds) keeps the grid readable for
        both a 2-commit week and a 40-commit week.
        """
        if count <= 0 or self.max_cell <= 0:
            return 0
        ratio = count / self.max_cell
        for step in range(1, buckets + 1):
            if ratio <= step / buckets:
                return step
        return buckets


def build_heatmap(
    days: Sequence[ContributionDay],
    *,
    week_start: int = 6,
) -> Heatmap:
    """Project a contribution calendar onto a (week, weekday) grid.

    ``week_start`` uses :meth:`date.weekday` numbering; ``6`` means the grid
    columns break on Sunday, matching GitHub's own calendar.
    """
    if not days:
        today = date.today()
        return Heatmap(
            cells=(), weeks=0, start=today, end=today,
            per_weekday=(0,) * 7, per_week=(), total=0,
            busiest_day=None, busiest_day_count=0, max_cell=0,
        )

    ordered = sorted(days, key=lambda entry: entry.day)
    start, end = ordered[0].day, ordered[-1].day

    # Snap the first column back to the configured week boundary so column 0 is
    # a real week, not a ragged partial one.
    offset = (start.weekday() - week_start) % 7
    grid_origin = start - timedelta(days=offset)

    per_weekday = [0] * 7
    per_week_map: dict[int, int] = {}
    cells: list[HeatmapCell] = []
    busiest_day: date | None = None
    busiest_count = 0
    max_cell = 0
    total = 0

    for entry in ordered:
        count = max(int(entry.count), 0)
        week_index = (entry.day - grid_origin).days // 7
        weekday = entry.day.weekday()

        cells.append(HeatmapCell(day=entry.day, count=count, week_index=week_index, weekday=weekday))
        per_weekday[weekday] += count
        per_week_map[week_index] = per_week_map.get(week_index, 0) + count
        total += count
        if count > max_cell:
            max_cell = count
        if count > busiest_count:
            busiest_count, busiest_day = count, entry.day

    weeks = max(per_week_map) + 1 if per_week_map else 0
    per_week = tuple(per_week_map.get(index, 0) for index in range(weeks))

    return Heatmap(
        cells=tuple(cells),
        weeks=weeks,
        start=start,
        end=end,
        per_weekday=tuple(per_weekday),
        per_week=per_week,
        total=total,
        busiest_day=busiest_day,
        busiest_day_count=busiest_count,
        max_cell=max_cell,
    )


PALETTE = ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353")
"""Level 0..4. Same visual language as GitHub, so it reads instantly."""


def _t(value: object) -> str:
    return escape(str(value), quote=True)


def heatmap_svg(
    heatmap: Heatmap,
    *,
    cell: int = 11,
    gap: int = 3,
    palette: Sequence[str] = PALETTE,
    background: str = "#0d1117",
    border: str = "#30363d",
    muted: str = "#8b949e",
    accent: str = "#58a6ff",
) -> str:
    """Render the grid as a self-contained, accessible SVG.

    Every cell carries a ``<title>`` so hovering in a browser (and screen
    readers) reports the exact date and count.
    """
    step = cell + gap
    left = 40
    top = 58
    width = left + max(heatmap.weeks, 1) * step + 92
    height = top + 7 * step + 46

    rects: list[str] = []
    for entry in heatmap.cells:
        x = left + entry.week_index * step
        y = top + entry.weekday * step
        level = heatmap.level(entry.count, buckets=len(palette) - 1)
        color = palette[min(level, len(palette) - 1)]
        label = f"{entry.day.isoformat()} · {entry.count} contribution{'s' if entry.count != 1 else ''}"
        rects.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}" '
            f'class="cell l{level}"><title>{_t(label)}</title></rect>'
        )

    day_labels = "".join(
        f'<text x="{left - 8}" y="{top + index * step + cell - 1}" class="axis" text-anchor="end">'
        f"{WEEKDAY_NAMES[index]}</text>"
        for index in (0, 2, 4, 6)
    )

    month_labels: list[str] = []
    seen: set[tuple[int, int]] = set()
    for entry in heatmap.cells:
        key = (entry.day.year, entry.day.month)
        if key in seen or entry.day.day > 7:
            continue
        seen.add(key)
        month_labels.append(
            f'<text x="{left + entry.week_index * step}" y="{top - 8}" class="axis">'
            f"{MONTH_NAMES[entry.day.month - 1]}</text>"
        )

    legend_x = left + max(heatmap.weeks, 1) * step + 14
    legend = "".join(
        f'<rect x="{legend_x}" y="{top + index * (cell + 5)}" width="{cell}" height="{cell}" rx="2" '
        f'fill="{palette[index]}"/>'
        f'<text x="{legend_x + cell + 6}" y="{top + index * (cell + 5) + cell - 1}" class="axis">'
        f"{'none' if index == 0 else ('low' if index == 1 else ('max' if index == len(palette) - 1 else str(index)))}</text>"
        for index in range(len(palette))
    )

    footer = (
        f"{heatmap.total} contributions · peak {heatmap.peak_weekday} · "
        f"{heatmap.consistency}% of days active · {heatmap.weekend_share}% on weekends"
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Commit heatmap by weekday and week">
  <style>
    .title {{ font: 600 15px 'Segoe UI', Ubuntu, Sans-Serif; fill: {accent}; }}
    .axis  {{ font: 400 9px 'Segoe UI', Ubuntu, Sans-Serif; fill: {muted}; }}
    .foot  {{ font: 400 10px 'Segoe UI', Ubuntu, Sans-Serif; fill: {muted}; }}
    .cell  {{ shape-rendering: crispEdges; }}
    .cell:hover {{ stroke: {accent}; stroke-width: 1; }}
    @media (prefers-reduced-motion: no-preference) {{
      .cell {{ animation: fade .6s ease-out both; }}
      @keyframes fade {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}
    }}
  </style>
  <rect x="0.5" y="0.5" rx="10" width="{width - 1}" height="{height - 1}" fill="{background}" stroke="{border}"/>
  <text x="{left - 12}" y="32" class="title">Commit distribution · {_t(heatmap.start.isoformat())} → {_t(heatmap.end.isoformat())}</text>
  {''.join(month_labels)}
  {day_labels}
  {''.join(rects)}
  {legend}
  <text x="{left - 12}" y="{height - 16}" class="foot">{_t(footer)}</text>
</svg>
"""


def weekday_table(heatmap: Heatmap) -> str:
    """A markdown table with an inline sparkline bar per weekday."""
    peak = max(heatmap.per_weekday) if any(heatmap.per_weekday) else 0
    rows = []
    for index, name in enumerate(WEEKDAY_NAMES):
        count = heatmap.per_weekday[index]
        filled = 0 if peak <= 0 else round(count * 12 / peak)
        bar = "█" * filled + "░" * (12 - filled)
        share = 0.0 if heatmap.total <= 0 else round(count * 100 / heatmap.total, 1)
        rows.append(f"| {name} | `{bar}` | {count} | {share}% |")
    return "\n".join(rows)
