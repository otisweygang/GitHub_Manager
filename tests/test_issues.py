from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot import issues
from bot.config import Config, ClaudeConfig, IssuesConfig, RepoConfig
from bot.health import HealthFinding


def _make_config(issues_enabled: bool = True) -> Config:
    return Config(
        repo=RepoConfig(owner="otisweygang", name="GitHub_Manager"),
        issues=IssuesConfig(enabled=issues_enabled, bot_label="bot-managed"),
        claude=ClaudeConfig(enabled=False),
    )


def _make_finding(fingerprint: str = "test-fp") -> HealthFinding:
    return HealthFinding(
        check="missing_files",
        title="Required file missing: README.md",
        detail="`README.md` does not exist.",
        fingerprint=fingerprint,
    )


def test_issues_disabled_returns_empty():
    cfg = _make_config(issues_enabled=False)
    gh = MagicMock()
    assert issues.plan([_make_finding()], gh, cfg) == []


def test_no_findings_returns_empty():
    cfg = _make_config()
    gh = MagicMock()
    assert issues.plan([], gh, cfg) == []


def test_plan_creates_issue_plan_for_finding():
    cfg = _make_config()
    gh = MagicMock()
    gh.issue_exists_with_label.return_value = False

    with patch("bot.issues.llm.generate", return_value="Issue body text"):
        result = issues.plan([_make_finding()], gh, cfg)

    assert len(result) == 1
    assert result[0].title == "Required file missing: README.md"
    assert result[0].fingerprint == "test-fp"
    assert "bot-managed" in result[0].labels


def test_plan_skips_if_issue_already_exists():
    cfg = _make_config()
    gh = MagicMock()
    gh.issue_exists_with_label.return_value = True  # already open

    result = issues.plan([_make_finding()], gh, cfg)

    assert result == []
    gh.issue_exists_with_label.assert_called_once_with("check:test-fp", full_name="otisweygang/GitHub_Manager")


def test_plan_uses_fallback_when_claude_disabled():
    cfg = _make_config()
    gh = MagicMock()
    gh.issue_exists_with_label.return_value = False

    result = issues.plan([_make_finding()], gh, cfg)

    assert len(result) == 1
    assert "`README.md` does not exist." in result[0].body


def test_multiple_findings_deduplicated_independently():
    cfg = _make_config()
    gh = MagicMock()
    # first finding already has an open issue, second does not
    gh.issue_exists_with_label.side_effect = [True, False]

    findings = [_make_finding("fp-1"), _make_finding("fp-2")]
    result = issues.plan(findings, gh, cfg)

    assert len(result) == 1
    assert result[0].fingerprint == "fp-2"
