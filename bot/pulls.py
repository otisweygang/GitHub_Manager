from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import ChangeSet, ImprovementFinding, IssuePlan, PRPlan

if TYPE_CHECKING:
    from .config import Config
    from .github_client import GitHubClient

log = logging.getLogger("bot.pulls")


def plan(
    findings: list[ImprovementFinding],
    github_client: "GitHubClient",
    config: "Config",
    today: str,
) -> tuple[list[PRPlan], list[IssuePlan]]:
    """Pure planning function — no side effects.

    Routes each ImprovementFinding to either a PRPlan or an IssuePlan.
    Applies rate limiting and deduplication.
    """
    si_cfg = config.pulls.self_improve
    if not findings:
        return [], []

    pr_plans: list[PRPlan] = []
    issue_plans: list[IssuePlan] = []
    pr_count = 0
    issue_count = 0

    for finding in findings:
        if finding.action == "pr":
            if pr_count >= si_cfg.max_prs_per_day:
                log.info("PR rate limit reached (%d), skipping: %s", si_cfg.max_prs_per_day, finding.title)
                continue
            branch = _branch_name(finding, today)
            if github_client.pr_exists_for_branch(branch, full_name=config.repo.full_name):
                log.info("PR already open for branch %s, skipping", branch)
                continue
            pr_plans.append(_finding_to_pr_plan(finding, today))
            pr_count += 1
            log.info("Planned PR: %s (branch: %s)", finding.title, branch)

        else:  # action == "issue"
            if issue_count >= si_cfg.max_issues_per_day:
                log.info("Issue rate limit reached (%d), skipping: %s", si_cfg.max_issues_per_day, finding.title)
                continue
            # Dedup label checked again in executor, but check here too to avoid unnecessary plans
            label = f"check:self-improve-{finding.fingerprint}"
            if github_client.issue_exists_with_label(label, full_name=config.repo.full_name):
                log.info("Issue already open for self-improve-%s, skipping", finding.fingerprint)
                continue
            issue_plans.append(_finding_to_issue_plan(finding, config))
            issue_count += 1
            log.info("Planned issue: %s", finding.title)

    return pr_plans, issue_plans


def _branch_name(finding: ImprovementFinding, today: str) -> str:
    return f"bot/{today}-self-improve-{finding.fingerprint}"


def _finding_to_pr_plan(finding: ImprovementFinding, today: str) -> PRPlan:
    branch = _branch_name(finding, today)
    return PRPlan(
        branch=branch,
        title=f"self-improve: {finding.title}",
        body=(
            f"{finding.body}\n\n"
            f"---\n"
            f"*Bot self-improvement | Category: `{finding.category}` | Risk: `{finding.risk}`*"
        ),
        changeset=ChangeSet(
            files=finding.file_changes,
            reason=finding.title,
            risk=finding.risk,
            source="self_improve",
        ),
        risk=finding.risk,
    )


def _finding_to_issue_plan(finding: ImprovementFinding, config: "Config") -> IssuePlan:
    fp = f"self-improve-{finding.fingerprint}"
    return IssuePlan(
        title=f"self-improve: {finding.title}",
        body=(
            f"{finding.body}\n\n"
            f"---\n"
            f"*Opened automatically by the self-improve bot. Category: `{finding.category}`*"
        ),
        labels=[config.issues.bot_label, "self-improve", f"self-improve:{finding.fingerprint}"],
        fingerprint=fp,
    )
