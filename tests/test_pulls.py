from __future__ import annotations

from unittest.mock import MagicMock

from bot import pulls
from bot.config import Config, IssuesConfig, PullsConfig, RepoConfig, SelfImproveConfig, SelfImproveScope
from bot.models import FileChange, ImprovementFinding


def _make_config() -> Config:
    return Config(
        repo=RepoConfig(owner="otisweygang", name="GitHub_Manager"),
        issues=IssuesConfig(bot_label="bot-managed"),
        pulls=PullsConfig(
            enabled=True,
            self_improve=SelfImproveConfig(max_prs_per_day=2, max_issues_per_day=3),
            scope=SelfImproveScope(),
        ),
    )


def _make_gh() -> MagicMock:
    gh = MagicMock()
    gh.pr_exists_for_branch.return_value = False
    gh.issue_exists_with_label.return_value = False
    return gh


def _make_finding(action: str = "pr", fingerprint: str = "abc123") -> ImprovementFinding:
    return ImprovementFinding(
        category="bug",
        title="Fix something",
        body="Detailed description",
        action=action,
        file_changes=[FileChange(path="bot/heatmap.py", content="# fixed")] if action == "pr" else [],
        fingerprint=fingerprint,
        risk="SAFE",
    )


def test_empty_findings_returns_empty():
    cfg = _make_config()
    gh = _make_gh()
    pr_plans, issue_plans = pulls.plan([], gh, cfg, "2026-03-18")
    assert pr_plans == []
    assert issue_plans == []


def test_pr_finding_produces_pr_plan():
    cfg = _make_config()
    gh = _make_gh()
    finding = _make_finding(action="pr")
    pr_plans, issue_plans = pulls.plan([finding], gh, cfg, "2026-03-18")
    assert len(pr_plans) == 1
    assert issue_plans == []
    assert pr_plans[0].branch == "bot/2026-03-18-self-improve-abc123"
    assert "self-improve: Fix something" == pr_plans[0].title


def test_issue_finding_produces_issue_plan():
    cfg = _make_config()
    gh = _make_gh()
    finding = _make_finding(action="issue")
    pr_plans, issue_plans = pulls.plan([finding], gh, cfg, "2026-03-18")
    assert pr_plans == []
    assert len(issue_plans) == 1
    assert issue_plans[0].title == "self-improve: Fix something"
    assert "self-improve:abc123" in issue_plans[0].labels


def test_pr_deduplication_skips_existing_branch():
    cfg = _make_config()
    gh = _make_gh()
    gh.pr_exists_for_branch.return_value = True
    finding = _make_finding(action="pr")
    pr_plans, _ = pulls.plan([finding], gh, cfg, "2026-03-18")
    assert pr_plans == []


def test_issue_deduplication_skips_existing_issue():
    cfg = _make_config()
    gh = _make_gh()
    gh.issue_exists_with_label.return_value = True
    finding = _make_finding(action="issue")
    _, issue_plans = pulls.plan([finding], gh, cfg, "2026-03-18")
    assert issue_plans == []


def test_pr_rate_limit():
    cfg = _make_config()
    cfg.pulls.self_improve.max_prs_per_day = 1
    gh = _make_gh()
    findings = [_make_finding(action="pr", fingerprint=f"fp{i}") for i in range(3)]
    pr_plans, _ = pulls.plan(findings, gh, cfg, "2026-03-18")
    assert len(pr_plans) == 1


def test_issue_rate_limit():
    cfg = _make_config()
    cfg.pulls.self_improve.max_issues_per_day = 2
    gh = _make_gh()
    findings = [_make_finding(action="issue", fingerprint=f"fp{i}") for i in range(4)]
    _, issue_plans = pulls.plan(findings, gh, cfg, "2026-03-18")
    assert len(issue_plans) == 2
