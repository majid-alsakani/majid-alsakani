"""Tests for the declarative configuration layer."""

from __future__ import annotations

import pytest

from profile_engine.config import (
    ConfigError,
    EngineConfig,
    SelectionConfig,
    from_mapping,
    load,
    with_overrides,
)


def test_defaults_are_complete_and_valid() -> None:
    config = EngineConfig().validate()
    assert config.output.report_dir == "docs"
    assert config.thresholds.top_repositories == 6
    assert config.cache.enabled is True


def test_missing_file_falls_back_to_defaults(tmp_path) -> None:
    config = load(search_from=tmp_path)
    assert config.source_path is None
    assert config.login


def test_explicit_missing_path_is_an_error(tmp_path) -> None:
    with pytest.raises(ConfigError):
        load(tmp_path / "nope.toml")


def test_file_is_parsed_and_arrays_become_tuples(tmp_path) -> None:
    path = tmp_path / "profile-engine.toml"
    path.write_text(
        """
login = "octocat"

[selection]
include = ["a", "b"]
min_stars = 3

[thresholds]
top_repositories = 4

[output]
report_dir = "site"
""",
        encoding="utf-8",
    )
    config = load(search_from=tmp_path)
    assert config.login == "octocat"
    assert config.selection.include == ("a", "b")
    assert config.thresholds.top_repositories == 4
    assert config.output.report_dir == "site"
    assert config.source_path == str(path)


def test_unknown_keys_fail_loudly() -> None:
    with pytest.raises(ConfigError):
        from_mapping({"selection": {"includes": ["a"]}})
    with pytest.raises(ConfigError):
        from_mapping({"nonsense": 1})


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ConfigError):
        from_mapping({"thresholds": {"top_repositories": 0}})


def test_selection_filters() -> None:
    selection = SelectionConfig(exclude=("junk",), min_stars=2, require_topics=("ai",))
    common = {"is_fork": False, "is_archived": False}
    assert selection.accepts(name="good", stars=5, topics=("ai",), **common)
    assert not selection.accepts(name="junk", stars=5, topics=("ai",), **common)
    assert not selection.accepts(name="low", stars=1, topics=("ai",), **common)
    assert not selection.accepts(name="offtopic", stars=5, topics=("web",), **common)
    assert not selection.accepts(name="fork", stars=5, topics=("ai",), is_fork=True, is_archived=False)


def test_overrides_route_to_the_right_section() -> None:
    config = with_overrides(EngineConfig(), login="new", report_dir="out", ttl_seconds=60, readme=None)
    assert config.login == "new"
    assert config.output.report_dir == "out"
    assert config.cache.ttl_seconds == 60
    assert config.output.readme == "README.md"
