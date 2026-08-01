"""Hand-rolled SVG rendering — no matplotlib, no headless browser, no fonts.

Two cards are produced: a stats card and a language-distribution bar. Both are
theme-aware and every dynamic value is escaped before it reaches the markup.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Sequence

from .metrics import LanguageShare, Snapshot


@dataclass(frozen=True, slots=True)
class Theme:
    background: str
    surface: str
    text: str
    muted: str
    accent: str
    border: str


DARK = Theme(
    background="#0d1117",
    surface="#161b22",
    text="#e6edf3",
    muted="#8b949e",
    accent="#58a6ff",
    border="#30363d",
)


def _t(value: object) -> str:
    """Escape any interpolated value; SVG is XML, not a string template."""
    return escape(str(value), quote=True)


def _human(number: int) -> str:
    for unit, size in (("M", 1_000_000), ("K", 1_000)):
        if number >= size:
            trimmed = f"{number / size:.1f}".rstrip("0").rstrip(".")
            return f"{trimmed}{unit}"
    return str(number)


def stats_card(snapshot: Snapshot, *, theme: Theme = DARK, width: int = 470) -> str:
    """Render the headline metrics card."""
    rows = (
        ("Public repositories", snapshot.public_repos),
        ("Total commits", snapshot.total_commits),
        ("Stars earned", snapshot.total_stars),
        ("Forks", snapshot.total_forks),
        ("Active this month", snapshot.active_repos),
        ("Followers", snapshot.followers),
    )
    height = 90 + len(rows) * 30

    lines: list[str] = []
    for index, (label, value) in enumerate(rows):
        y = 96 + index * 30
        lines.append(
            f'<text x="28" y="{y}" class="label">{_t(label)}</text>'
            f'<text x="{width - 28}" y="{y}" class="value" text-anchor="end">{_t(_human(int(value)))}</text>'
        )

    ring = _score_ring(snapshot.impact_score, cx=width - 62, cy=46, theme=theme)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub statistics for {_t(snapshot.login)}">
  <style>
    .title {{ font: 600 17px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.accent}; }}
    .label {{ font: 400 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.muted}; }}
    .value {{ font: 600 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.text}; }}
    .score {{ font: 700 15px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.text}; }}
    .caption {{ font: 400 9px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.muted}; }}
  </style>
  <rect x="0.5" y="0.5" rx="10" width="{width - 1}" height="{height - 1}" fill="{theme.background}" stroke="{theme.border}"/>
  <text x="28" y="40" class="title">{_t(snapshot.login)} · engineering footprint</text>
  {ring}
  {''.join(lines)}
</svg>
"""


def _score_ring(score: int, *, cx: int, cy: int, theme: Theme, radius: int = 26) -> str:
    circumference = 2 * 3.14159265 * radius
    filled = circumference * max(0, min(score, 100)) / 100
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{theme.border}" stroke-width="5"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{theme.accent}" stroke-width="5" '
        f'stroke-linecap="round" stroke-dasharray="{filled:.2f} {circumference:.2f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + 5}" class="score" text-anchor="middle">{score}</text>'
    )


def language_card(
    languages: Sequence[LanguageShare], *, theme: Theme = DARK, width: int = 470
) -> str:
    """Render a stacked language bar plus a legend."""
    if not languages:
        languages = (LanguageShare("No data", theme.muted, 0, 100.0),)

    height = 92 + ((len(languages) + 1) // 2) * 24
    bar_width = width - 56
    segments: list[str] = []
    offset = 0.0
    for share in languages:
        span = max(bar_width * share.percent / 100, 2.0)
        segments.append(
            f'<rect x="{28 + offset:.2f}" y="56" width="{span:.2f}" height="10" fill="{share.color}"/>'
        )
        offset += span

    legend: list[str] = []
    for index, share in enumerate(languages):
        column = index % 2
        row = index // 2
        x = 28 + column * (bar_width / 2)
        y = 96 + row * 24
        legend.append(
            f'<circle cx="{x + 5:.1f}" cy="{y - 4}" r="5" fill="{share.color}"/>'
            f'<text x="{x + 18:.1f}" y="{y}" class="label">{_t(share.name)} '
            f'<tspan class="pct">{share.percent:.1f}%</tspan></text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Language distribution">
  <style>
    .title {{ font: 600 17px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.accent}; }}
    .label {{ font: 400 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {theme.text}; }}
    .pct {{ fill: {theme.muted}; }}
  </style>
  <rect x="0.5" y="0.5" rx="10" width="{width - 1}" height="{height - 1}" fill="{theme.background}" stroke="{theme.border}"/>
  <text x="28" y="36" class="title">Language distribution</text>
  <clipPath id="rounded"><rect x="28" y="56" width="{bar_width}" height="10" rx="5"/></clipPath>
  <g clip-path="url(#rounded)">{''.join(segments)}</g>
  {''.join(legend)}
</svg>
"""
