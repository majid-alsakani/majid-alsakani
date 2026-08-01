from __future__ import annotations

import json
from datetime import timezone

import pytest

from profile_engine.github_api import GitHubClient, GitHubError
from profile_engine.models import parse_iso8601, repository_from_graphql

UTC = timezone.utc

NODE = {
    "name": "joobea-platform",
    "description": "AI recruitment platform",
    "url": "https://github.com/u/joobea-platform",
    "diskUsage": 1629,
    "forkCount": 3,
    "isFork": False,
    "isArchived": False,
    "createdAt": "2026-06-08T18:55:30Z",
    "pushedAt": "2026-08-01T14:40:28Z",
    "stargazers": {"totalCount": 2},
    "watchers": {"totalCount": 1},
    "issues": {"totalCount": 0},
    "repositoryTopics": {"nodes": [{"topic": {"name": "fastapi"}}]},
    "languages": {"edges": [{"size": 400, "node": {"name": "Python", "color": "#3572A5"}}]},
    "defaultBranchRef": {"target": {"history": {"totalCount": 94}}},
}


def test_parse_iso8601_is_utc_aware():
    parsed = parse_iso8601("2026-08-01T14:40:28Z")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_repository_mapping():
    repo = repository_from_graphql(NODE)
    assert repo.name == "joobea-platform"
    assert repo.commits == 94
    assert repo.topics == ("fastapi",)
    assert repo.primary_language == "Python"


def test_repository_mapping_survives_missing_fields():
    repo = repository_from_graphql({"name": "bare"})
    assert repo.commits == 0
    assert repo.primary_language == "Other"
    assert repo.languages == ()


def test_client_requires_token():
    with pytest.raises(GitHubError):
        GitHubClient("")


class FakeClient(GitHubClient):
    def __init__(self, responses):
        super().__init__("token", sleep=lambda _: None)
        self._responses = list(responses)
        self.calls = 0

    def _post(self, payload):  # type: ignore[override]
        self.calls += 1
        return self._responses.pop(0)


def test_execute_retries_on_rate_limit_then_succeeds():
    client = FakeClient(
        [
            {"errors": [{"type": "RATE_LIMITED", "message": "slow down"}]},
            {"data": {"ok": True}},
        ]
    )
    assert client.execute("query {}", {}) == {"ok": True}
    assert client.calls == 2


def test_execute_raises_on_fatal_error():
    client = FakeClient([{"errors": [{"type": "NOT_FOUND", "message": "missing"}]}])
    with pytest.raises(GitHubError, match="missing"):
        client.execute("query {}", {})


def test_fetch_profile_follows_pagination():
    page_one = {
        "data": {
            "user": {
                "login": "u",
                "name": "U",
                "bio": "b",
                "createdAt": "2020-01-01T00:00:00Z",
                "followers": {"totalCount": 9},
                "following": {"totalCount": 1},
                "contributionsCollection": {
                    "contributionCalendar": {
                        "weeks": [
                            {"contributionDays": [{"date": "2026-07-31", "contributionCount": 3}]}
                        ]
                    }
                },
                "repositories": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    "nodes": [NODE],
                },
            }
        }
    }
    page_two = json.loads(json.dumps(page_one))
    page_two["data"]["user"]["repositories"]["pageInfo"] = {"hasNextPage": False, "endCursor": None}
    page_two["data"]["user"]["repositories"]["nodes"] = [{**NODE, "name": "second"}]

    client = FakeClient([page_one, page_two])
    profile = client.fetch_profile("u")
    assert [repo.name for repo in profile.repositories] == ["joobea-platform", "second"]
    assert profile.followers == 9
    assert profile.contributions[0].count == 3


def test_fetch_profile_unknown_user():
    client = FakeClient([{"data": {"user": None}}])
    with pytest.raises(GitHubError, match="No such user"):
        client.fetch_profile("ghost")
