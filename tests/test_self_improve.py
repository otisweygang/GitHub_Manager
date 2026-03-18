from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bot import self_improve
from bot.config import (
    ClaudeConfig, Config, PullsConfig, RepoConfig,
    SelfImproveConfig, SelfImproveScope,
)


def _make_config(si_enabled: bool = True) -> Config:
    return Config(
        repo=RepoConfig(owner="otisweygang", name="GitHub_Manager"),
        claude=ClaudeConfig(enabled=True, model="claude-opus-4-6"),
        pulls=PullsConfig(
            enabled=True,
            self_improve=SelfImproveConfig(
                enabled=si_enabled,
                max_prs_per_day=2,
                max_issues_per_day=3,
                max_tokens=8192,
            ),
            scope=SelfImproveScope(
                writable_paths=["bot/*.py", "docs/*.md"],
                always_review_paths=["tests/", ".github/"],
            ),
        ),
    )


def _make_gh() -> MagicMock:
    gh = MagicMock()
    gh.get_open_issues.return_value = []
    return gh


def test_analyze_disabled_returns_empty():
    cfg = _make_config(si_enabled=False)
    gh = _make_gh()
    assert self_improve.analyze(cfg, gh, "2026-03-18") == []


def test_analyze_claude_disabled_returns_empty():
    cfg = _make_config()
    cfg.claude.enabled = False
    gh = _make_gh()
    assert self_improve.analyze(cfg, gh, "2026-03-18") == []


def test_analyze_empty_claude_response_returns_empty():
    cfg = _make_config()
    gh = _make_gh()
    with patch("bot.self_improve._call_claude", return_value=""):
        with patch("bot.self_improve._collect_context", return_value={}):
            result = self_improve.analyze(cfg, gh, "2026-03-18")
    assert result == []


def test_analyze_returns_parsed_findings():
    cfg = _make_config()
    gh = _make_gh()
    raw = json.dumps([{
        "category": "bug",
        "title": "Fix heatmap edge case",
        "body": "The heatmap misses edge cases.",
        "action": "issue",
        "file_changes": [],
    }])
    with patch("bot.self_improve._call_claude", return_value=raw):
        with patch("bot.self_improve._collect_context", return_value={}):
            result = self_improve.analyze(cfg, gh, "2026-03-18")
    assert len(result) == 1
    assert result[0].title == "Fix heatmap edge case"
    assert result[0].action == "issue"


def test_parse_findings_invalid_json_returns_empty():
    scope = SelfImproveScope()
    result = self_improve._parse_findings("not json", scope)
    assert result == []


def test_parse_findings_drops_out_of_scope_paths():
    scope = SelfImproveScope(writable_paths=["bot/*.py"])
    raw = json.dumps([{
        "category": "improvement",
        "title": "Change test file",
        "body": "body",
        "action": "pr",
        "file_changes": [{"path": "tests/test_foo.py", "content": "# new"}],
    }])
    result = self_improve._parse_findings(raw, scope)
    assert result == []


def test_parse_findings_marks_always_review_paths_as_needs_review():
    scope = SelfImproveScope(
        writable_paths=["bot/*.py", "tests/*.py"],
        always_review_paths=["tests/"],
    )
    raw = json.dumps([{
        "category": "bug",
        "title": "Fix test",
        "body": "body",
        "action": "pr",
        "file_changes": [{"path": "tests/test_foo.py", "content": "# fixed"}],
    }])
    result = self_improve._parse_findings(raw, scope)
    assert len(result) == 1
    assert result[0].risk == "NEEDS_REVIEW"


def test_fingerprint_is_stable():
    fp1 = self_improve._fingerprint("bug", "Fix something")
    fp2 = self_improve._fingerprint("bug", "Fix something")
    assert fp1 == fp2
    assert len(fp1) == 10


def test_fingerprint_differs_for_different_inputs():
    fp1 = self_improve._fingerprint("bug", "Fix A")
    fp2 = self_improve._fingerprint("bug", "Fix B")
    assert fp1 != fp2
