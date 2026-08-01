# profile-engine

> A self-updating analytics pipeline that recomputes this profile's engineering
> metrics from the GitHub GraphQL API, renders the charts as hand-built SVG, and
> rewrites a single marked block of `README.md` — four times a day, with zero
> runtime dependencies.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3572A5)](https://www.python.org)
[![Dependencies](https://img.shields.io/badge/runtime_dependencies-0-2ea043)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-47_passing-2ea043)](tests)
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
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
        svg.stats_card / language_card       readme.render_section
          assets/generated/*.svg          idempotent marker injection
                    └────────────────┬────────────────┘
                                     ▼
                       GitHub Actions commits the diff
```

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
| **Explainable score** | The 0–100 footprint score uses saturating weights that favour *sustained shipping* (commits, recent activity) over vanity stars. The formula is 10 lines and lives in `metrics.impact_score`. |

## Layout

| Path | Responsibility |
| --- | --- |
| `profile_engine/models.py` | Typed domain model + defensive GraphQL mapping |
| `profile_engine/github_api.py` | GraphQL transport, pagination, retry policy |
| `profile_engine/cache.py` | Content-addressed TTL cache, atomic writes, stale fallback |
| `profile_engine/metrics.py` | Language shares, streaks, ranking, footprint score |
| `profile_engine/svg.py` | Dependency-free SVG cards (stats ring, language bar) |
| `profile_engine/readme.py` | Marker-based, idempotent README injection |
| `profile_engine/__main__.py` | CLI entry point |
| `tests/` | 47 unit tests: mapping, metrics, retries, caching, XML validity, escaping |

## Usage

```sh
cd tools/profile-engine
pip install -e ".[dev]"

export GITHUB_TOKEN=ghp_...            # read-only public_repo scope is enough
python -m profile_engine --login majid-alsakani --dry-run   # print, write nothing
python -m profile_engine --login majid-alsakani             # update README + SVG
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
pytest              # 47 tests
```

CI runs all three on every push, and the scheduled job refuses to publish unless
they pass — see [`.github/workflows/profile-engine.yml`](../../.github/workflows/profile-engine.yml).

## Testing strategy

The GraphQL client is subclassed in tests to swap the transport, so pagination,
rate-limit retries and fatal-error handling are exercised without a network call.
The cache is driven by an injectable clock, so TTL expiry, stale fallback during a
simulated outage and atomic-write behaviour are all asserted deterministically —
no `sleep()` in the suite. SVG output is parsed with `xml.etree.ElementTree` to prove well-formedness, and a
hostile language name (`<script>"x"`) asserts the escaping path.

---

MIT · built by [Majid Al-Sakani](https://github.com/majid-alsakani)
