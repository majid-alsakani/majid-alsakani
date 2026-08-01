"""CLI entry point: `python -m profile_engine [--config profile-engine.toml]`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .cache import NullCache, ResponseCache
from .config import ConfigError, EngineConfig, load as load_config, with_overrides
from .github_api import GitHubClient, GitHubError
from .heatmap import build_heatmap, heatmap_svg
from .metrics import build_snapshot
from .readme import inject, render_section
from .report import build_payload, render_html, render_json
from .svg import language_card, stats_card

LOGGER = logging.getLogger("profile_engine")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile_engine",
        description="Recompute the live metrics block, SVG cards and HTML/JSON report of a GitHub profile.",
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to profile-engine.toml.")
    parser.add_argument("--login", default=os.environ.get("PROFILE_LOGIN") or None)
    parser.add_argument("--readme", default=None)
    parser.add_argument("--assets", dest="assets_dir", default=None)
    parser.add_argument("--report-dir", dest="report_dir", default=None,
                        help="Directory for the HTML/JSON report (GitHub Pages ready).")
    parser.add_argument("--no-report", action="store_true", help="Skip HTML and JSON output.")
    parser.add_argument("--report-only", action="store_true", help="Only write the report; leave README and SVGs alone.")
    parser.add_argument("--dry-run", action="store_true", help="Print, do not write.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--print-config", action="store_true", help="Show the effective configuration and exit.")
    parser.add_argument("--cache-dir", dest="directory", type=str, default=None,
                        help="Where GraphQL responses are stored between runs.")
    parser.add_argument("--cache-ttl", dest="ttl_seconds", type=int, default=None,
                        help="Seconds a cached response stays fresh.")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the response cache entirely.")
    parser.add_argument("--clear-cache", action="store_true", help="Purge cached responses before running.")
    return parser


def resolve_config(args: argparse.Namespace) -> EngineConfig:
    search_roots = [Path.cwd(), Path(__file__).resolve().parent.parent]
    config = EngineConfig()
    if args.config is not None:
        config = load_config(args.config)
    else:
        for root in search_roots:
            candidate = load_config(search_from=root)
            if candidate.source_path:
                config = candidate
                break
        else:
            config = load_config()

    return with_overrides(
        config,
        login=args.login,
        readme=args.readme,
        assets_dir=args.assets_dir,
        report_dir=args.report_dir,
        directory=args.directory,
        ttl_seconds=args.ttl_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s · %(message)s",
    )

    try:
        config = resolve_config(args)
    except ConfigError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 2

    if args.print_config:
        sys.stdout.write(f"{config}\n")
        return 0

    use_cache = config.cache.enabled and not args.no_cache
    cache = (
        ResponseCache(Path(config.cache.directory), ttl_seconds=config.cache.ttl_seconds)
        if use_cache
        else NullCache()
    )
    if args.clear_cache:
        cache.purge()

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        client = GitHubClient(token, cache=cache)
        profile = client.fetch_profile(config.login)
    except GitHubError as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info("Cache: %s", cache.stats.describe())
    if client.rate_limit:
        LOGGER.info(
            "Rate limit: %s/%s points remaining (resets %s)",
            client.rate_limit.get("remaining"),
            client.rate_limit.get("limit"),
            client.rate_limit.get("resetAt"),
        )

    selected = tuple(
        repo
        for repo in profile.repositories
        if config.selection.accepts(
            name=repo.name,
            is_fork=repo.is_fork,
            is_archived=repo.is_archived,
            stars=repo.stars,
            topics=repo.topics,
        )
    )
    skipped = len(profile.repositories) - len(selected)
    if skipped:
        LOGGER.info("Selection filters excluded %d repositor%s.", skipped, "y" if skipped == 1 else "ies")

    from dataclasses import replace as _replace

    profile = _replace(profile, repositories=selected)
    snapshot = build_snapshot(profile, top=config.thresholds.top_repositories)
    heatmap = build_heatmap(profile.contributions)

    LOGGER.info(
        "%s · %d repos · %d commits · %d stars · score %d · heatmap %d weeks / %d contributions (peak %s)",
        snapshot.login,
        snapshot.public_repos,
        snapshot.total_commits,
        snapshot.total_stars,
        snapshot.impact_score,
        heatmap.weeks,
        heatmap.total,
        heatmap.peak_weekday,
    )

    report_dir = Path(config.output.report_dir)
    section = render_section(
        snapshot,
        heatmap=heatmap,
        report_url=f"{report_dir.as_posix()}/{config.output.html_name}",
        heatmap_asset=f"{Path(config.output.assets_dir).as_posix()}/{config.output.heatmap_name}",
        cache_stats=cache.stats.as_dict() if hasattr(cache.stats, "as_dict") else None,
    )

    if args.dry_run:
        sys.stdout.write(section + "\n")
        return 0

    if config.output.write_readme and not args.report_only:
        readme_path = Path(config.output.readme)
        original = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
        updated = inject(original, section)
        if updated != original:
            readme_path.write_text(updated, encoding="utf-8")
            LOGGER.info("README updated (%d bytes).", len(updated))
        else:
            LOGGER.info("README already current.")

    if config.output.write_svg and not args.report_only:
        assets = Path(config.output.assets_dir)
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "stats.svg").write_text(stats_card(snapshot), encoding="utf-8")
        (assets / "languages.svg").write_text(language_card(snapshot.languages), encoding="utf-8")
        (assets / config.output.heatmap_name).write_text(heatmap_svg(heatmap), encoding="utf-8")
        LOGGER.info("SVG cards written to %s", assets)

    if not args.no_report and (config.output.write_json or config.output.write_html):
        payload = build_payload(
            snapshot,
            heatmap,
            config=config,
            cache_stats=cache.stats.as_dict() if hasattr(cache.stats, "as_dict") else None,
        )
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / ".nojekyll").write_text("", encoding="utf-8")
        if config.output.write_json:
            (report_dir / config.output.json_name).write_text(render_json(payload), encoding="utf-8")
        if config.output.write_html:
            (report_dir / config.output.html_name).write_text(
                render_html(payload, config=config), encoding="utf-8"
            )
        LOGGER.info("Report written to %s/", report_dir)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
