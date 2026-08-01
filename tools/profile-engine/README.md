# profile-engine

> A self-updating analytics pipeline that recomputes this profile's engineering
> metrics from the GitHub GraphQL API, derives a weekday x week commit heatmap,
> renders every chart as hand-built SVG, publishes an interactive HTML dashboard
> plus a machine-readable JSON report to GitHub Pages, and rewrites a single
> marked block of `README.md` — four times a day, with zero runtime dependencies.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3572A5)](https://www.python.org)
[![Dependencies](https://img.shields.io/badge/runtime_dependencies-0-2ea043)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-66_passing-2ea043)](tests)
[![Report](https://img.shields.io/badge/report-HTML%20%2B%20JSON-58a6ff)](../../docs/index.html)
[![Lint](https://img.shields.io/badge/ruff-clean-58a6ff)](pyproject.toml)

## Why it exists

Profile READMEs usually embed third-party stat widgets. Those go down, rate-limit,
leak your traffic, and cannot express metrics you actually care about. This engine
computes its own numbers, owns its own rendering, and commits the result — so the
profile is a *build artifact*, not a screenshot.

## Design

```text
GitHub GraphQL API
        │  paginated, retried, backoff-with-jitter
        ▼
   cache.ResponseCache  ◀──▶  TTL disk cache (fresh hit = zero API points,
        │                      stale hit = survives an outage)
        ▼
   github_api.GitHubClient ──▶ models.Profile        (frozen dataclasses, validated)
                                     │
                                     ▼
                          metrics.build_snapshot()   (pure functions, no I/O)
                                     │
                                     │
                       heatmap.build_heatmap()  (weekday x week projection)
                                     │
        ┌──────────────┬─────────────┴─────────────┬──────────────┐
        ▼              ▼                           ▼              ▼
 svg.stats_card   heatmap_svg()          readme.render_section  report.build_payload
 language_card    assets/generated/      idempotent marker            │
 assets/*.svg     heatmap.svg            injection            ┌───────┴────────┐
        │              │                        │             ▼                ▼
        └──────────────┴────────────────────────┴──────  docs/index.html  docs/profile-report.json
                                     │                   (interactive)     (schema v2)
                                     ▼
                       GitHub Actions commits the diff
                       GitHub Pages serves docs/
```

Every stage above is driven by one declarative file, [`profile-engine.toml`](profile-engine.toml):
which repositories participate, what counts as "active", where artefacts land.

### Engineering decisions worth defending

| Decision | Reason |
| --- | --- |
| **Zero runtime dependencies** | `urllib` + `json` only. The scheduled job cannot break because an upstream package published a bad release. |
| **Frozen, slotted dataclasses** | Nothing downstream can mutate a snapshot; `slots=True` keeps the object graph small. |
| **Pure metric layer** | `metrics.py` performs no I/O, so every number in the README is unit-testable without a network fixture. |
| **Idempotent injection** | The engine writes only between `PROFILE-ENGINE:START/END`. Hand-written prose outside the markers is preserved byte-for-byte; running it twice yields an identical file. |
| **Escaped SVG output** | Language names come from an external API and are interpolated into XML — every value passes through `html.escape`, and colors are validated against a hex whitelist. |
| **TTL response cache** | Repeat runs read the same repository pages. A content-addressed disk cache (`sha256(query+variables)`) serves them without spending rate-limit points, and an expired entry is replayed when GitHub is down rather than publishing a broken README. |
| **Backoff with jitter** | Secondary rate limits are handled with capped exponential backoff plus jitter, retrying `RATE_LIMITED` GraphQL errors while failing fast on fatal ones. |
| **Relative heatmap bucketing** | Colour levels are computed against the observed maximum, not fixed thresholds, so a quiet month and a heavy month are both readable instead of one washing the other out. |
| **One payload, two artefacts** | `report.build_payload()` is the single source of truth; the JSON *is* the HTML's data (embedded as `window.__REPORT__`). The page and the API can never disagree. |
| **Self-contained HTML** | No CDN, no bundler, no framework — inline CSS plus ~1 KB of vanilla JS. The dashboard loads offline, renders in one paint, and cannot break because a third-party script disappeared. |
| **Config that fails loudly** | An unknown TOML key raises `ConfigError` at load time. A typo'd option silently changing what gets published is the worst failure mode a scheduled job can have. |
| **Explainable score** | The 0–100 footprint score uses saturating weights that favour *sustained shipping* (commits, recent activity) over vanity stars. The formula is 10 lines and lives in `metrics.impact_score`. |

## Layout

| Path | Responsibility |
| --- | --- |
| `profile_engine/models.py` | Typed domain model + defensive GraphQL mapping |
| `profile_engine/github_api.py` | GraphQL transport, pagination, retry policy |
| `profile_engine/cache.py` | Content-addressed TTL cache, atomic writes, stale fallback |
| `profile_engine/metrics.py` | Language shares, streaks, ranking, footprint score |
| `profile_engine/heatmap.py` | Weekday x week projection, rhythm signals, SVG grid, markdown table |
| `profile_engine/report.py` | Canonical JSON payload + self-contained interactive HTML dashboard |
| `profile_engine/config.py` | Declarative TOML config: selection, thresholds, outputs, cache |
| `profile_engine/svg.py` | Dependency-free SVG cards (stats ring, language bar) |
| `profile_engine/readme.py` | Marker-based, idempotent README injection |
| `profile_engine/__main__.py` | CLI entry point |
| `profile-engine.toml` | The one file you edit to change behaviour |
| `tests/` | 66 unit tests: mapping, metrics, retries, caching, heatmap maths, report schema, XSS escaping, XML validity |

## Usage

```sh
cd tools/profile-engine
pip install -e ".[dev]"

export GITHUB_TOKEN=ghp_...            # read-only public_repo scope is enough
python -m profile_engine --login majid-alsakani --dry-run   # print, write nothing
python -m profile_engine --login majid-alsakani             # README + SVG + HTML + JSON
python -m profile_engine --report-only                      # regenerate docs/ only
python -m profile_engine --print-config                     # show the effective config
```

### Configuration

All behaviour lives in [`profile-engine.toml`](profile-engine.toml). Missing file =
built-in defaults; **unknown keys are a hard error**, so a typo can never silently
change what gets published.

```toml
login = "majid-alsakani"

[selection]              # which repositories take part
include = []             # allow-list; empty means every owned repository
exclude = ["scratch"]
exclude_forks = true
exclude_archived = false
require_topics = []      # e.g. ["ai"] keeps only repos carrying one of these
min_stars = 0

[thresholds]             # the numbers that turn counts into judgements
active_days = 30         # "active" = pushed within this window
top_repositories = 6
language_limit = 8
commits_ceiling = 400    # score saturation points
stars_ceiling = 100
active_ceiling = 6
repos_ceiling = 15
heatmap_buckets = 4

[output]                 # where artefacts land — defaults are Pages-ready
readme = "README.md"
assets_dir = "assets/generated"
report_dir = "docs"
write_readme = true
write_svg = true
write_json = true
write_html = true
json_name = "profile-report.json"
html_name = "index.html"
heatmap_name = "heatmap.svg"
site_title = "Engineering Report"
site_url = "https://majid-alsakani.github.io/majid-alsakani/"

[cache]
directory = ".cache/profile-engine"
ttl_seconds = 10800
enabled = true
```

Load order, later wins: **built-in defaults → TOML file → CLI flags**.
Point at any file with `--config path/to/file.toml`; an explicit path that does
not exist is an error rather than a silent fallback.

### Commit heatmap

`heatmap.build_heatmap()` projects the contribution calendar onto a
(week, weekday) plane and derives the signals a raw calendar cannot state:

| Signal | Meaning |
| --- | --- |
| `peak_weekday` / `quietest_weekday` | The day you actually ship on, and the one you do not |
| `consistency` | Percent of days in the window with at least one contribution |
| `weekend_share` | Percent of all contributions made on Sat/Sun |
| `daily_average` | Contributions per calendar day across the window |
| `busiest_day` | Single highest day, with its count |

Rendered three ways: `assets/generated/heatmap.svg` (every cell carries a
`<title>`, so hover and screen readers both report the exact date and count),
a markdown table with inline sparkline bars inside the README block, and a
clickable grid in the HTML dashboard.

### Reports and GitHub Pages

```sh
python -m profile_engine --report-dir docs        # default; Pages-ready
python -m profile_engine --no-report              # README + SVG only
```

Two files are written into `docs/` (plus `.nojekyll`):

| File | Purpose |
| --- | --- |
| `docs/index.html` | Interactive dashboard: animated counters, clickable heatmap, language bar, repo table. Ships full SEO metadata — canonical, Open Graph, Twitter cards and `Dataset` JSON-LD. |
| `docs/profile-report.json` | Canonical, sorted, diff-friendly payload (`schema_version: 2`) with totals, streak, languages, repositories and the full per-day heatmap series. |

Publish it in two clicks: **Settings → Pages → Source: `main` / `/docs`**. The
report then lives at `https://<user>.github.io/<repo>/` and refreshes itself on
every scheduled run. Because the JSON is a stable contract, anything else — a
portfolio site, a Grafana panel, another workflow — can consume the same data:

```sh
curl -s https://majid-alsakani.github.io/majid-alsakani/profile-report.json \
  | jq '.heatmap.peak_weekday, .totals.impact_score'
```

### Cache control

```sh
python -m profile_engine --cache-ttl 10800     # freshness window in seconds (default 3h)
python -m profile_engine --cache-dir .cache/pe # where entries live
python -m profile_engine --clear-cache         # drop expired entries first
python -m profile_engine --no-cache            # bypass the cache entirely
```

Environment equivalents: `PROFILE_CACHE_DIR`, `PROFILE_CACHE_TTL`. CI persists the
directory with `actions/cache`, so a re-run inside the TTL window costs **zero**
GraphQL points. Each run logs its hit rate and the remaining rate-limit budget:

```text
INFO profile_engine · Cache: 3 hit(s), 0 miss(es), 0 stale fallback(s), 0 write(s) — 100% hit rate
INFO profile_engine · Rate limit: 4996/5000 points remaining (resets 2026-08-01T17:00:00Z)
```

## Quality gates

```sh
ruff check .        # lint (E, F, I, UP, B, SIM, C4, RUF)
mypy profile_engine # strict typing
pytest              # 66 tests
```

CI runs all three on every push, and the scheduled job refuses to publish unless
they pass — see [`.github/workflows/profile-engine.yml`](../../.github/workflows/profile-engine.yml).

## Testing strategy

The GraphQL client is subclassed in tests to swap the transport, so pagination,
rate-limit retries and fatal-error handling are exercised without a network call.
The cache is driven by an injectable clock, so TTL expiry, stale fallback during a
simulated outage and atomic-write behaviour are all asserted deterministically —
no `sleep()` in the suite. SVG output is parsed with `xml.etree.ElementTree` to prove well-formedness, and a
hostile language name (`<script>"x"`) asserts the escaping path. The report layer
is fuzzed the same way: a repository named `<img src=x onerror=...>` must appear
escaped in the markup, and a payload containing `</script>` must not be able to
break out of the embedded `window.__REPORT__` block.

---

MIT · built by [Majid Al-Sakani](https://github.com/majid-alsakani)
