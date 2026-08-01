"""Declarative configuration for the engine.

Everything the pipeline can be told to do lives in one TOML file
(``profile-engine.toml``) so a behaviour change is a config commit, not a code
commit. Parsing uses :mod:`tomllib` from the standard library (Python 3.11+),
so the workflow still installs nothing.

Design rules:

* **Defaults are complete.** A missing file is not an error — the engine runs
  with the shipped defaults.
* **Unknown keys are reported, not silently swallowed.** A typo in a config key
  is the single most common way a "working" pipeline quietly stops doing what
  you asked.
* **Values are validated at load time**, so a bad threshold fails before any
  network call rather than halfway through rendering.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger("profile_engine.config")

DEFAULT_CONFIG_NAMES = ("profile-engine.toml", ".profile-engine.toml")


class ConfigError(ValueError):
    """Raised when the config file exists but cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Which repositories take part in the analysis."""

    include: tuple[str, ...] = ()
    """Explicit allow-list. Empty means "every owned repository"."""

    exclude: tuple[str, ...] = ()
    exclude_forks: bool = True
    exclude_archived: bool = False
    require_topics: tuple[str, ...] = ()
    min_stars: int = 0

    def accepts(self, *, name: str, is_fork: bool, is_archived: bool, stars: int, topics: tuple[str, ...]) -> bool:
        if self.include and name not in self.include:
            return False
        if name in self.exclude:
            return False
        if self.exclude_forks and is_fork:
            return False
        if self.exclude_archived and is_archived:
            return False
        if stars < self.min_stars:
            return False
        if self.require_topics and not set(self.require_topics) & set(topics):
            return False
        return True


@dataclass(frozen=True, slots=True)
class ThresholdConfig:
    """The numbers that turn raw counts into judgements."""

    active_days: int = 30
    """A repository is "active" when it was pushed within this many days."""

    top_repositories: int = 6
    language_limit: int = 8
    commits_ceiling: int = 400
    stars_ceiling: int = 100
    active_ceiling: int = 6
    repos_ceiling: int = 15
    heatmap_buckets: int = 4

    def validate(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or value <= 0:
                raise ConfigError(f"thresholds.{item.name} must be a positive integer, got {value!r}")


@dataclass(frozen=True, slots=True)
class OutputConfig:
    """Where artefacts land. Defaults are GitHub-Pages ready."""

    readme: str = "README.md"
    assets_dir: str = "assets/generated"
    report_dir: str = "docs"
    """`docs/` is one of the two folders GitHub Pages can serve with zero config."""

    write_readme: bool = True
    write_svg: bool = True
    write_json: bool = True
    write_html: bool = True
    json_name: str = "profile-report.json"
    html_name: str = "index.html"
    heatmap_name: str = "heatmap.svg"
    site_title: str = "Engineering Report"
    site_url: str = ""
    """Absolute URL of the published report; used for canonical + OG tags."""


@dataclass(frozen=True, slots=True)
class CacheConfig:
    directory: str = ".cache/profile-engine"
    ttl_seconds: int = 60 * 60 * 3
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """The whole configuration surface, in one object."""

    login: str = "majid-alsakani"
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    source_path: str | None = None

    def validate(self) -> EngineConfig:
        if not self.login.strip():
            raise ConfigError("login must not be empty")
        self.thresholds.validate()
        if self.cache.ttl_seconds < 0:
            raise ConfigError("cache.ttl_seconds must not be negative")
        return self


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table")
    return value


def _build(cls: type, raw: Mapping[str, Any], label: str) -> Any:
    known = {item.name for item in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"[{label}] has unknown key(s): {', '.join(sorted(unknown))}")

    kwargs: dict[str, Any] = {}
    for item in fields(cls):
        if item.name not in raw:
            continue
        value = raw[item.name]
        if item.type.startswith("tuple") or isinstance(getattr(cls(), item.name, None), tuple):
            if not isinstance(value, list):
                raise ConfigError(f"{label}.{item.name} must be an array")
            kwargs[item.name] = tuple(str(entry) for entry in value)
        else:
            kwargs[item.name] = value
    return cls(**kwargs)


def from_mapping(raw: Mapping[str, Any], *, source: str | None = None) -> EngineConfig:
    """Build a validated config from an already-parsed mapping."""
    top_level_known = {"login", "selection", "thresholds", "output", "cache"}
    unknown = set(raw) - top_level_known
    if unknown:
        raise ConfigError(f"unknown top-level key(s): {', '.join(sorted(unknown))}")

    config = EngineConfig(
        login=str(raw.get("login", EngineConfig.login)),
        selection=_build(SelectionConfig, _section(raw, "selection"), "selection"),
        thresholds=_build(ThresholdConfig, _section(raw, "thresholds"), "thresholds"),
        output=_build(OutputConfig, _section(raw, "output"), "output"),
        cache=_build(CacheConfig, _section(raw, "cache"), "cache"),
        source_path=source,
    )
    return config.validate()


def load(path: Path | None = None, *, search_from: Path | None = None) -> EngineConfig:
    """Load the config file, or fall back to defaults when none exists.

    When ``path`` is given the file must exist — an explicit path that silently
    resolves to defaults is a debugging nightmare.
    """
    if path is not None:
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        return _read(path)

    root = search_from or Path.cwd()
    for name in DEFAULT_CONFIG_NAMES:
        candidate = root / name
        if candidate.exists():
            return _read(candidate)

    LOGGER.debug("No config file found; using built-in defaults.")
    return EngineConfig().validate()


def _read(path: Path) -> EngineConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - message passthrough
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    LOGGER.info("Loaded configuration from %s", path)
    return from_mapping(raw, source=str(path))


def with_overrides(config: EngineConfig, **overrides: Any) -> EngineConfig:
    """Apply non-``None`` CLI overrides on top of the file config."""
    clean = {key: value for key, value in overrides.items() if value is not None}
    if not clean:
        return config
    output_keys = {item.name for item in fields(OutputConfig)}
    cache_keys = {item.name for item in fields(CacheConfig)}

    top: dict[str, Any] = {}
    out: dict[str, Any] = {}
    cache: dict[str, Any] = {}
    for key, value in clean.items():
        if key in output_keys:
            out[key] = value
        elif key in cache_keys:
            cache[key] = value
        else:
            top[key] = value

    updated = replace(config, **top)
    if out:
        updated = replace(updated, output=replace(updated.output, **out))
    if cache:
        updated = replace(updated, cache=replace(updated.cache, **cache))
    return updated.validate()
