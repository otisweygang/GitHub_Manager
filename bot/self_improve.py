from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from . import llm as llm_module
from .models import FileChange, ImprovementFinding

if TYPE_CHECKING:
    from .config import Config, SelfImproveScope
    from .github_client import GitHubClient

log = logging.getLogger("bot.self_improve")


def analyze(config: "Config", github_client: "GitHubClient", today: str) -> list[ImprovementFinding]:
    """Pure planning function — no side effects.

    Reads codebase files + open issues, sends to Claude, returns structured findings.
    Returns [] if disabled, Claude unavailable, or output unparseable.
    """
    si_cfg = config.pulls.self_improve
    if not si_cfg.enabled:
        log.info("Self-improve disabled in config, skipping")
        return []

    if not config.claude.enabled:
        log.info("Claude disabled — self-improve requires Claude, skipping")
        return []

    log.info("Self-improve: collecting codebase context...")
    file_context = _collect_context(config.pulls.scope)
    open_issues_text = _collect_open_issues(github_client, config.repo.full_name)

    prompt = _build_prompt(file_context, open_issues_text, config)

    log.info("Self-improve: calling Claude (%d files in context)...", len(file_context))
    raw = _call_claude(prompt, config)
    if not raw:
        log.warning("Self-improve: Claude returned empty response, skipping")
        return []

    findings = _parse_findings(raw, config.pulls.scope)
    log.info("Self-improve: %d finding(s) parsed", len(findings))
    return findings


def _collect_context(scope: "SelfImproveScope") -> dict[str, str]:
    """Read files matching readable_paths globs. Returns {path: content}."""
    import fnmatch

    result: dict[str, str] = {}
    for pattern in scope.readable_paths:
        for path in sorted(Path(".").glob(pattern)):
            if path.is_file():
                try:
                    result[str(path)] = path.read_text(encoding="utf-8")
                except Exception as exc:
                    log.warning("Could not read %s: %s", path, exc)
    return result


def _collect_open_issues(github_client: "GitHubClient", repo_full_name: str) -> str:
    """Returns markdown-formatted list of open issue titles for Claude context."""
    try:
        issues = github_client.get_open_issues(full_name=repo_full_name)
        if not issues:
            return "No open issues."
        lines = [f"- #{i.number}: {i.title}" for i in issues if not i.pull_request]
        return "\n".join(lines) if lines else "No open issues."
    except Exception as exc:
        log.warning("Could not fetch open issues: %s", exc)
        return "Could not fetch open issues."


def _build_prompt(
    file_context: dict[str, str],
    open_issues_text: str,
    config: "Config",
) -> str:
    si_cfg = config.pulls.self_improve
    max_findings = si_cfg.max_prs_per_day + si_cfg.max_issues_per_day
    writable = ", ".join(config.pulls.scope.writable_paths)

    codebase_block = "\n\n".join(
        f"## File: {path}\n```\n{content}\n```"
        for path, content in file_context.items()
    )

    return f"""<codebase>
{codebase_block}
</codebase>

<open_issues>
{open_issues_text}
</open_issues>

<task>
You are a self-improvement agent for an autonomous GitHub bot. Analyze the codebase above and identify bugs, improvements, documentation gaps, or missing features.

Rules:
- Output ONLY a valid JSON array. No explanation, no markdown fences, no prose.
- For action "pr": include COMPLETE new file content. Only use "pr" for small, targeted fixes (< 100 lines changed). The file_changes array must be non-empty.
- For action "issue": use for larger improvements, architectural changes, or anything requiring discussion. Set file_changes to [].
- When in doubt between "pr" and "issue", prefer "issue" to keep output size manageable.
- Only propose changes to files matching these patterns: {writable}
- Do not raise findings for things already tracked in the open issues listed above.
- Maximum {max_findings} total findings. Be conservative — only raise findings you are confident about.
- If you find nothing worth flagging, return [].

Each finding must match this schema:
{{
  "category": "bug" | "improvement" | "docs" | "missing_feature",
  "title": "Short title, max 80 characters",
  "body": "Detailed markdown description with context and rationale",
  "action": "pr" | "issue",
  "file_changes": [{{"path": "relative/path.py", "content": "FULL new file content"}}]
}}
</task>"""


def _call_claude(prompt: str, config: "Config") -> str:
    """Direct Anthropic API call with self_improve-specific max_tokens.

    Does NOT use llm.generate() — needs different max_tokens and no fallback string.
    Returns raw response string or "" on any failure.
    """
    si_cfg = config.pulls.self_improve
    model = si_cfg.model or config.claude.model

    try:
        client = llm_module._get_client()
        message = client.messages.create(
            model=model,
            max_tokens=si_cfg.max_tokens,
            temperature=config.claude.temperature,
            system=(
                "You are a self-improvement agent for an autonomous GitHub bot. "
                "Output only valid JSON. No explanation, no markdown fences."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        log.warning("Self-improve Claude call failed: %s", exc)
        return ""


def _parse_findings(raw: str, scope: "SelfImproveScope") -> list[ImprovementFinding]:
    """Parse Claude's JSON output into ImprovementFinding list.

    Validates paths against writable_paths. Enforces always_review_paths risk.
    Returns [] if JSON is malformed or empty.
    """
    import fnmatch

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Self-improve: could not parse Claude JSON: %s", exc)
        return []

    if not isinstance(data, list):
        log.warning("Self-improve: expected JSON array, got %s", type(data).__name__)
        return []

    findings: list[ImprovementFinding] = []
    for item in data:
        try:
            category = item["category"]
            title = item["title"]
            body = item["body"]
            action = item["action"]
            raw_changes = item.get("file_changes", [])

            if action not in ("pr", "issue"):
                log.warning("Self-improve: invalid action %r, skipping", action)
                continue

            file_changes: list[FileChange] = []
            for fc in raw_changes:
                path = fc["path"]
                # Validate path is within writable_paths
                if not any(fnmatch.fnmatch(path, pattern) for pattern in scope.writable_paths):
                    log.warning("Self-improve: path %r not in writable_paths, dropping finding", path)
                    file_changes = []
                    break
                file_changes.append(FileChange(path=path, content=fc["content"]))

            if action == "pr" and not file_changes:
                log.warning("Self-improve: PR finding has no valid file_changes, skipping: %s", title)
                continue

            risk = _determine_risk(file_changes, scope.always_review_paths)
            fp = _fingerprint(category, title)

            findings.append(ImprovementFinding(
                category=category,
                title=title[:80],
                body=body,
                action=action,
                file_changes=file_changes,
                fingerprint=fp,
                risk=risk,
            ))
        except (KeyError, TypeError) as exc:
            log.warning("Self-improve: malformed finding, skipping: %s", exc)

    return findings


def _determine_risk(
    file_changes: list[FileChange],
    always_review_paths: list[str],
) -> str:
    """Returns NEEDS_REVIEW if any file path starts with an always_review prefix."""
    for fc in file_changes:
        for prefix in always_review_paths:
            if fc.path.startswith(prefix):
                return "NEEDS_REVIEW"
    return "SAFE"


def _fingerprint(category: str, title: str) -> str:
    """Stable sha1[:10] identifier for a finding."""
    return hashlib.sha1(f"{category}:{title}".encode()).hexdigest()[:10]
