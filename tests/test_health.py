from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from bot import health
from bot.config import Config, HealthConfig, HealthChecksConfig, MissingFilesCheckConfig, StaleIssuesCheckConfig, WorkflowFailuresCheckConfig, RepoConfig


def _make_config(**health_kwargs) -> Config:
    return Config(
        repo=RepoConfig(owner="otisweygang", name="GitHub_Manager"),
        health=HealthConfig(**health_kwargs) if health_kwargs else HealthConfig(),
    )


def _make_github_client() -> MagicMock:
    gh = MagicMock()
    gh.file_exists.return_value = True
    gh.get_open_issues.return_value = []
    gh.get_recent_workflow_runs.return_value = []
    return gh


def test_health_disabled_returns_empty():
    cfg = _make_config(enabled=False)
    gh = _make_github_client()
    assert health.check(cfg, gh) == []


def test_missing_file_detected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no files exist locally
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=True, required_files=["README.md"]),
            stale_issues=StaleIssuesCheckConfig(enabled=False),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=False),
        )
    )
    gh = _make_github_client()
    gh.file_exists.return_value = False  # also not on GitHub

    findings = health.check(cfg, gh)

    assert len(findings) == 1
    assert findings[0].check == "missing_files"
    assert "README.md" in findings[0].title


def test_no_finding_when_file_exists_on_github(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=True, required_files=["README.md"]),
            stale_issues=StaleIssuesCheckConfig(enabled=False),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=False),
        )
    )
    gh = _make_github_client()
    gh.file_exists.return_value = True  # exists on GitHub

    findings = health.check(cfg, gh)
    assert findings == []


def test_stale_issue_detected():
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=False),
            stale_issues=StaleIssuesCheckConfig(enabled=True, stale_after_days=14),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=False),
        )
    )
    gh = _make_github_client()
    stale_issue = MagicMock()
    stale_issue.pull_request = None
    stale_issue.number = 42
    stale_issue.title = "Old bug"
    stale_issue.updated_at = datetime.now(timezone.utc) - timedelta(days=20)
    gh.get_open_issues.return_value = [stale_issue]

    findings = health.check(cfg, gh)

    assert len(findings) == 1
    assert findings[0].check == "stale_issues"
    assert "42" in findings[0].title


def test_fresh_issue_not_flagged():
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=False),
            stale_issues=StaleIssuesCheckConfig(enabled=True, stale_after_days=14),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=False),
        )
    )
    gh = _make_github_client()
    fresh_issue = MagicMock()
    fresh_issue.pull_request = None
    fresh_issue.number = 1
    fresh_issue.title = "Recent issue"
    fresh_issue.updated_at = datetime.now(timezone.utc) - timedelta(days=3)
    gh.get_open_issues.return_value = [fresh_issue]

    findings = health.check(cfg, gh)
    assert findings == []


def test_workflow_failure_detected():
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=False),
            stale_issues=StaleIssuesCheckConfig(enabled=False),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=True, check_last_n_runs=3),
        )
    )
    gh = _make_github_client()
    failed_run = MagicMock()
    failed_run.conclusion = "failure"
    failed_run.run_number = 99
    failed_run.html_url = "https://github.com/test/runs/99"
    failed_run.created_at = datetime.now(timezone.utc)
    gh.get_recent_workflow_runs.return_value = [failed_run]

    findings = health.check(cfg, gh)

    assert len(findings) == 1
    assert findings[0].check == "workflow_failures"


def test_successful_runs_not_flagged():
    cfg = _make_config(
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(enabled=False),
            stale_issues=StaleIssuesCheckConfig(enabled=False),
            workflow_failures=WorkflowFailuresCheckConfig(enabled=True, check_last_n_runs=3),
        )
    )
    gh = _make_github_client()
    success_run = MagicMock()
    success_run.conclusion = "success"
    gh.get_recent_workflow_runs.return_value = [success_run]

    findings = health.check(cfg, gh)
    assert findings == []
