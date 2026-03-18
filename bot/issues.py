from __future__ import annotations

import logging

from . import llm
from .config import Config
from .github_client import GitHubClient
from .health import HealthFinding
from .models import IssuePlan

log = logging.getLogger("bot.issues")


def plan(findings: list[HealthFinding], github_client: GitHubClient, config: Config) -> list[IssuePlan]:
    """Pure planning function — no side effects.

    For each health finding, returns an IssuePlan unless an issue already exists.
    """
    if not config.issues.enabled:
        log.info("Issues disabled in config, skipping")
        return []

    plans: list[IssuePlan] = []
    for finding in findings:
        fingerprint_label = f"check:{finding.fingerprint}"

        if github_client.issue_exists_with_label(fingerprint_label, full_name=config.repo.full_name):
            log.info("Issue already open for %s, skipping", finding.fingerprint)
            continue

        body = llm.generate(
            intent="Write a GitHub issue body describing this health finding. Be concise and actionable.",
            context={
                "check": finding.check,
                "title": finding.title,
                "detail": finding.detail,
            },
            fallback=f"{finding.detail}\n\n*Opened automatically by the bot.*",
            claude_config=config.claude,
        )

        plans.append(IssuePlan(
            title=finding.title,
            body=body,
            labels=[config.issues.bot_label, finding.check],
            fingerprint=finding.fingerprint,
        ))
        log.info("Planned issue: %s", finding.title)

    return plans
