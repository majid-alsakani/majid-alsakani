"""Report generation: one dataset, two publishable artefacts.

``build_payload`` is the single source of truth — a plain, JSON-serialisable
dict describing the whole snapshot. ``render_json`` writes it verbatim so other
tools can consume it, and ``render_html`` renders the *same* dict into a
self-contained, dependency-free dashboard page that GitHub Pages can serve
straight out of ``docs/``.

No template engine, no bundler, no CDN: the HTML embeds the JSON payload and a
few hundred bytes of vanilla JavaScript, so the page works offline, loads
instantly, and can never break because a third-party script went away.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from typing import Any, Mapping

from .config import EngineConfig
from .heatmap import WEEKDAY_NAMES, Heatmap
from .metrics import Snapshot

SCHEMA_VERSION = 2


def _t(value: object) -> str:
    return escape(str(value), quote=True)


def build_payload(
    snapshot: Snapshot,
    heatmap: Heatmap,
    *,
    config: EngineConfig | None = None,
    generated_at: datetime | None = None,
    cache_stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the canonical, machine-readable report."""
    stamp = (generated_at or datetime.now(tz=timezone.utc)).replace(microsecond=0)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": stamp.isoformat(),
        "login": snapshot.login,
        "config_source": config.source_path if config else None,
        "totals": {
            "public_repositories": snapshot.public_repos,
            "active_repositories": snapshot.active_repos,
            "commits": snapshot.total_commits,
            "stars": snapshot.total_stars,
            "forks": snapshot.total_forks,
            "followers": snapshot.followers,
            "disk_usage_kb": snapshot.total_kb,
            "impact_score": snapshot.impact_score,
        },
        "streak": {
            "current": snapshot.streak.current,
            "longest": snapshot.streak.longest,
            "total": snapshot.streak.total,
            "best_day": snapshot.streak.best_day,
        },
        "languages": [
            {
                "name": share.name,
                "color": share.color,
                "bytes": share.bytes_,
                "percent": share.percent,
            }
            for share in snapshot.languages
        ],
        "repositories": [
            {
                "name": repo.name,
                "url": repo.url,
                "description": repo.description or "",
                "language": repo.primary_language,
                "commits": repo.commits,
                "stars": repo.stars,
                "forks": repo.forks,
                "open_issues": repo.issues,
                "topics": list(repo.topics),
                "days_since_push": repo.days_since_push,
                "is_active": repo.is_active,
            }
            for repo in snapshot.top_repositories
        ],
        "heatmap": {
            "start": heatmap.start.isoformat(),
            "end": heatmap.end.isoformat(),
            "weeks": heatmap.weeks,
            "total": heatmap.total,
            "max_day": heatmap.max_cell,
            "active_days": heatmap.active_days,
            "consistency_percent": heatmap.consistency,
            "weekend_share_percent": heatmap.weekend_share,
            "daily_average": heatmap.daily_average,
            "peak_weekday": heatmap.peak_weekday,
            "quietest_weekday": heatmap.quietest_weekday,
            "busiest_day": heatmap.busiest_day.isoformat() if heatmap.busiest_day else None,
            "busiest_day_count": heatmap.busiest_day_count,
            "per_weekday": {
                name: heatmap.per_weekday[index] for index, name in enumerate(WEEKDAY_NAMES)
            },
            "per_week": list(heatmap.per_week),
            "days": [
                {"date": cell.day.isoformat(), "count": cell.count, "weekday": cell.weekday}
                for cell in heatmap.cells
            ],
        },
        "cache": dict(cache_stats or {}),
    }


def render_json(payload: Mapping[str, Any]) -> str:
    """Stable, diff-friendly JSON (sorted keys, trailing newline)."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


_CSS = """
:root{--bg:#0b0f14;--surface:#11161d;--surface-2:#161d26;--line:#232c38;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--good:#39d353;--warn:#f0883e}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 15% -10%,#132033 0,var(--bg) 60%);color:var(--text);font:16px/1.6 'Segoe UI',system-ui,-apple-system,Ubuntu,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:48px 20px 96px}
header h1{font-size:clamp(28px,4vw,44px);margin:0 0 8px;letter-spacing:-.02em}
header p{color:var(--muted);margin:0}
.badge{display:inline-block;padding:4px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px;color:var(--muted);margin-top:14px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:32px 0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px;transition:transform .18s ease,border-color .18s ease}
.card:hover{transform:translateY(-3px);border-color:var(--accent)}
.card .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.card .v{font-size:30px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
h2{margin:44px 0 14px;font-size:20px;display:flex;align-items:center;gap:10px}
h2::before{content:"";width:4px;height:20px;background:var(--accent);border-radius:2px}
section{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:22px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
tbody tr:hover{background:var(--surface-2)}
.bar{height:10px;border-radius:6px;background:var(--surface-2);overflow:hidden;display:flex}
.bar span{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:14px;font-size:13px;color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.hm{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,13px);gap:3px;min-width:max-content}
.hm i{width:13px;height:13px;border-radius:3px;background:#161b22;cursor:pointer;transition:transform .12s}
.hm i:hover{transform:scale(1.45);outline:1px solid var(--accent)}
.hm i.l1{background:#0e4429}.hm i.l2{background:#006d32}.hm i.l3{background:#26a641}.hm i.l4{background:#39d353}
.hmfoot{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:12px;margin-top:14px;gap:12px;flex-wrap:wrap}
.wk{display:flex;align-items:center;gap:10px;margin:8px 0;font-size:13px}
.wk b{width:42px;color:var(--muted);font-weight:600}
.wk .t{flex:1;height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden}
.wk .t i{display:block;height:100%;background:linear-gradient(90deg,#26a641,#39d353);border-radius:4px}
footer{color:var(--muted);font-size:13px;margin-top:44px;text-align:center}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

_JS = """
const D=window.__REPORT__;
const tip=(el,txt)=>el.setAttribute('title',txt);
const max=D.heatmap.max_day||1;
const lvl=c=>c<=0?0:Math.min(4,Math.ceil(c/max*4));
const grid=document.getElementById('hm');
if(grid){
  const first=new Date(D.heatmap.days[0]?.date||D.heatmap.start);
  const pad=(first.getDay()+6)%7;
  for(let i=0;i<pad;i++){const s=document.createElement('i');s.style.visibility='hidden';grid.appendChild(s);}
  for(const d of D.heatmap.days){
    const cell=document.createElement('i');
    const l=lvl(d.count); if(l) cell.className='l'+l;
    tip(cell,`${d.date} — ${d.count} contribution${d.count===1?'':'s'}`);
    cell.addEventListener('click',()=>{document.getElementById('hmsel').textContent=`${d.date}: ${d.count} contributions`;});
    grid.appendChild(cell);
  }
}
document.querySelectorAll('[data-count]').forEach(el=>{
  const end=+el.dataset.count; let t0=null;
  const run=ts=>{if(!t0)t0=ts;const p=Math.min((ts-t0)/900,1);
    el.textContent=Math.round(end*(1-Math.pow(1-p,3))).toLocaleString();
    if(p<1)requestAnimationFrame(run);};
  if(matchMedia('(prefers-reduced-motion:reduce)').matches){el.textContent=end.toLocaleString();}
  else requestAnimationFrame(run);
});
"""


def render_html(payload: Mapping[str, Any], *, config: EngineConfig | None = None) -> str:
    """Render the interactive dashboard page for GitHub Pages."""
    output = config.output if config else None
    title = (output.site_title if output else "Engineering Report")
    site_url = (output.site_url if output else "") or ""
    login = str(payload.get("login", ""))
    totals = payload.get("totals", {})
    streak = payload.get("streak", {})
    heat = payload.get("heatmap", {})
    languages = payload.get("languages", [])
    repositories = payload.get("repositories", [])
    generated = str(payload.get("generated_at", ""))

    page_title = f"{login} · {title}"
    description = (
        f"Live engineering report for {login}: {totals.get('commits', 0)} commits across "
        f"{totals.get('public_repositories', 0)} repositories, {totals.get('stars', 0)} stars, "
        f"commit heatmap and language distribution. Regenerated automatically."
    )

    cards = "".join(
        f'<div class="card"><div class="k">{_t(label)}</div>'
        f'<div class="v" data-count="{int(value)}">0</div></div>'
        for label, value in (
            ("Commits", totals.get("commits", 0)),
            ("Repositories", totals.get("public_repositories", 0)),
            ("Stars", totals.get("stars", 0)),
            ("Followers", totals.get("followers", 0)),
            ("Footprint score", totals.get("impact_score", 0)),
            ("Current streak", streak.get("current", 0)),
        )
    )

    lang_bar = "".join(
        f'<span style="width:{float(entry.get("percent", 0)):.2f}%;background:{_t(entry.get("color", "#8b949e"))}"></span>'
        for entry in languages
    ) or '<span style="width:100%;background:#30363d"></span>'

    lang_legend = "".join(
        f'<span><i class="dot" style="background:{_t(entry.get("color", "#8b949e"))}"></i>'
        f'{_t(entry.get("name", "?"))} {float(entry.get("percent", 0)):.1f}%</span>'
        for entry in languages
    ) or "<span>No language data</span>"

    per_weekday = heat.get("per_weekday", {})
    peak = max(per_weekday.values()) if per_weekday else 0
    weekday_rows = "".join(
        f'<div class="wk"><b>{_t(name)}</b><div class="t"><i style="width:'
        f'{(0 if peak <= 0 else count * 100 / peak):.1f}%"></i></div>'
        f'<span>{int(count)}</span></div>'
        for name, count in per_weekday.items()
    )

    repo_rows = "".join(
        "<tr>"
        f'<td><a href="{_t(repo.get("url", "#"))}" rel="noopener">{_t(repo.get("name", ""))}</a></td>'
        f'<td>{_t(repo.get("language", "—"))}</td>'
        f'<td>{int(repo.get("commits", 0))}</td>'
        f'<td>{int(repo.get("stars", 0))}</td>'
        f'<td>{int(repo.get("open_issues", 0))}</td>'
        f'<td>{int(repo.get("days_since_push", 0))}d</td>'
        "</tr>"
        for repo in repositories
    ) or '<tr><td colspan="6">No repositories matched the configured filters.</td></tr>'

    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": page_title,
            "description": description,
            "creator": {"@type": "Person", "name": login, "url": f"https://github.com/{login}"},
            "dateModified": generated,
            "license": "https://opensource.org/licenses/MIT",
            "keywords": [
                "GitHub analytics",
                "commit heatmap",
                "engineering metrics",
                login,
            ],
            **({"url": site_url} if site_url else {}),
        },
        ensure_ascii=False,
    )

    canonical = f'\n  <link rel="canonical" href="{_t(site_url)}" />' if site_url else ""
    og_url = f'\n  <meta property="og:url" content="{_t(site_url)}" />' if site_url else ""
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_t(page_title)}</title>
  <meta name="description" content="{_t(description)}" />
  <meta name="author" content="{_t(login)}" />
  <meta name="robots" content="index, follow, max-image-preview:large" />{canonical}
  <meta property="og:type" content="profile" />
  <meta property="og:title" content="{_t(page_title)}" />
  <meta property="og:description" content="{_t(description)}" />{og_url}
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{_t(page_title)}" />
  <meta name="twitter:description" content="{_t(description)}" />
  <meta name="theme-color" content="#0b0f14" />
  <link rel="alternate" type="application/json" href="./{_t(output.json_name if output else 'profile-report.json')}" title="Raw report data" />
  <script type="application/ld+json">{json_ld}</script>
  <style>{_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>{_t(login)} — {_t(title)}</h1>
      <p>{_t(description)}</p>
      <span class="badge">Generated {_t(generated)} · schema v{int(payload.get("schema_version", SCHEMA_VERSION))}</span>
    </header>

    <div class="grid">{cards}</div>

    <h2>Commit heatmap — weekday x week</h2>
    <section>
      <div class="hm" id="hm" role="img" aria-label="Contribution heatmap"></div>
      <div class="hmfoot">
        <span id="hmsel">Click any cell to inspect a day</span>
        <span>{_t(heat.get("start", ""))} → {_t(heat.get("end", ""))} ·
          peak <b>{_t(heat.get("peak_weekday", "—"))}</b> ·
          {_t(heat.get("consistency_percent", 0))}% of days active ·
          {_t(heat.get("weekend_share_percent", 0))}% on weekends ·
          avg {_t(heat.get("daily_average", 0))}/day</span>
      </div>
      <div style="margin-top:22px">{weekday_rows}</div>
    </section>

    <h2>Language distribution</h2>
    <section>
      <div class="bar">{lang_bar}</div>
      <div class="legend">{lang_legend}</div>
    </section>

    <h2>Most active repositories</h2>
    <section>
      <table>
        <thead><tr><th>Repository</th><th>Language</th><th>Commits</th><th>Stars</th><th>Open issues</th><th>Last push</th></tr></thead>
        <tbody>{repo_rows}</tbody>
      </table>
    </section>

    <footer>
      Built by <code>tools/profile-engine</code> — standard library only, no runtime dependencies.
      <br /><a href="./{_t(output.json_name if output else 'profile-report.json')}">Download the raw JSON</a> ·
      <a href="https://github.com/{_t(login)}/{_t(login)}" rel="noopener">Source</a>
    </footer>
  </div>
  <script>window.__REPORT__ = {embedded};</script>
  <script>{_JS}</script>
</body>
</html>
"""
