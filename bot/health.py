from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .github_client import GitHubClient

log = logging.getLogger("bot.health")


@dataclass
class HealthFinding:
    check: str          # "missing_files" | "stale_issues" | "workflow_failures"
    title: str
    detail: str
    fingerprint: str    # used for issue deduplication


def check(config: Config, github_client: GitHubClient) -> list[HealthFinding]:
    """Pure health check — no side effects. Returns list of findings."""
    if not config.health.enabled:
        log.info("Health checks disabled in config, skipping")
        return []

    findings: list[HealthFinding] = []
    checks = config.health.checks

    if checks.missing_files.enabled:
        findings.extend(_check_missing_files(checks.missing_files.required_files, github_client, config))

    if checks.stale_issues.enabled:
        findings.extend(_check_stale_issues(checks.stale_issues.stale_after_days, github_client, config))

    if checks.workflow_failures.enabled:
        findings.extend(_check_workflow_failures(checks.workflow_failures.check_last_n_runs, github_client, config))

    log.info("Health check complete: %d finding(s)", len(findings))
    return findings


def _check_missing_files(required_files: list[str], github_client: GitHubClient, config: Config) -> list[HealthFinding]:
    findings = []
    for path in required_files:
        if not Path(path).exists() and not github_client.file_exists(path, full_name=config.repo.full_name):
            log.warning("Missing required file: %s", path)
            findings.append(HealthFinding(
                check="missing_files",
                title=f"Required file missing: {path}",
                detail=f"`{path}` is listed as required in config but does not exist in the repository.",
                fingerprint=f"missing-file-{path.replace('/', '-')}",
            ))
    return findings


def _check_stale_issues(stale_after_days: int, github_client: GitHubClient, config: Config) -> list[HealthFinding]:
    findings = []
    try:
        issues = github_client.get_open_issues(full_name=config.repo.full_name)
        now = datetime.now(timezone.utc)
        for issue in issues:
            if issue.pull_request:
                continue  # skip PRs which also appear as issues
            updated = issue.updated_at.replace(tzinfo=timezone.utc) if issue.updated_at.tzinfo is None else issue.updated_at
            age_days = (now - updated).days
            if age_days >= stale_after_days:
                log.warning("Stale issue #%d: %s (%d days)", issue.number, issue.title, age_days)
                findings.append(HealthFinding(
                    check="stale_issues",
                    title=f"Stale issue: #{issue.number}",
                    detail=f"Issue #{issue.number} — \"{issue.title}\" has had no activity for {age_days} days.",
                    fingerprint=f"stale-issue-{issue.number}",
                ))
    except Exception as exc:
        log.warning("stale_issues check failed: %s", exc)
    return findings


def _check_workflow_failures(check_last_n: int, github_client: GitHubClient, config: Config) -> list[HealthFinding]:
    findings = []
    try:
        runs = github_client.get_recent_workflow_runs(
            "bot.yml", n=check_last_n, full_name=config.repo.full_name
        )
        failed = [r for r in runs if r.conclusion == "failure"]
        if failed:
            log.warning("%d recent workflow failure(s) detected", len(failed))
            findings.append(HealthFinding(
                check="workflow_failures",
                title=f"Bot workflow failures detected ({len(failed)} of last {check_last_n} runs)",
                detail="\n".join(
                    f"- Run [{r.run_number}]({r.html_url}) failed at {r.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                    for r in failed
                ),
                fingerprint="workflow-failures-bot",
            ))
    except Exception as exc:
        log.warning("workflow_failures check failed: %s", exc)
    return findings
