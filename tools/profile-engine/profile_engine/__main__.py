"""CLI entry point: `python -m profile_engine --login <user> [--dry-run]`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .cache import DEFAULT_TTL_SECONDS, NullCache, ResponseCache
from .github_api import GitHubClient, GitHubError
from .metrics import build_snapshot
from .readme import inject, render_section
from .svg import language_card, stats_card

LOGGER = logging.getLogger("profile_engine")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile_engine",
        description="Recompute the live metrics block of a GitHub profile README.",
    )
    parser.add_argument("--login", default=os.environ.get("PROFILE_LOGIN", "majid-alsakani"))
    parser.add_argument("--readme", default="README.md", type=Path)
    parser.add_argument("--assets", default=Path("assets/generated"), type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Print, do not write.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("PROFILE_CACHE_DIR", ".cache/profile-engine")),
        help="Where GraphQL responses are stored between runs.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=int(os.environ.get("PROFILE_CACHE_TTL", DEFAULT_TTL_SECONDS)),
        help="Seconds a cached response stays fresh (default: 3 hours).",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass the cache entirely.")
    parser.add_argument(
        "--clear-cache", action="store_true", help="Delete expired entries before running."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s · %(message)s",
    )

    cache = NullCache() if args.no_cache else ResponseCache(args.cache_dir, ttl_seconds=args.cache_ttl)
    if args.clear_cache:
        cache.purge()

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        client = GitHubClient(token, cache=cache)
        profile = client.fetch_profile(args.login)
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


    snapshot = build_snapshot(profile)
    LOGGER.info(
        "%s · %d repos · %d commits · %d stars · score %d",
        snapshot.login,
        snapshot.public_repos,
        snapshot.total_commits,
        snapshot.total_stars,
        snapshot.impact_score,
    )

    section = render_section(snapshot)
    if args.dry_run:
        sys.stdout.write(section + "\n")
        return 0

    readme_path: Path = args.readme
    original = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    updated = inject(original, section)
    if updated != original:
        readme_path.write_text(updated, encoding="utf-8")
        LOGGER.info("README updated (%d bytes).", len(updated))
    else:
        LOGGER.info("README already current.")

    assets: Path = args.assets
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "stats.svg").write_text(stats_card(snapshot), encoding="utf-8")
    (assets / "languages.svg").write_text(language_card(snapshot.languages), encoding="utf-8")
    LOGGER.info("SVG cards written to %s", assets)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
