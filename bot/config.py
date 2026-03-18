from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RepoConfig:
    owner: str
    name: str
    default_branch: str = "main"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class HeatmapConfig:
    enabled: bool = True
    commit_types: list[str] = field(default_factory=lambda: ["run_history"])
    commits_per_day: int = 1
    idempotency_scan_depth: int = 50


@dataclass
class MissingFilesCheckConfig:
    enabled: bool = True
    required_files: list[str] = field(default_factory=list)


@dataclass
class StaleIssuesCheckConfig:
    enabled: bool = True
    stale_after_days: int = 14


@dataclass
class WorkflowFailuresCheckConfig:
    enabled: bool = True
    check_last_n_runs: int = 5


@dataclass
class HealthChecksConfig:
    missing_files: MissingFilesCheckConfig = field(default_factory=MissingFilesCheckConfig)
    stale_issues: StaleIssuesCheckConfig = field(default_factory=StaleIssuesCheckConfig)
    workflow_failures: WorkflowFailuresCheckConfig = field(default_factory=WorkflowFailuresCheckConfig)


@dataclass
class HealthConfig:
    enabled: bool = True
    checks: HealthChecksConfig = field(default_factory=HealthChecksConfig)


@dataclass
class IssuesConfig:
    enabled: bool = True
    bot_label: str = "bot-managed"
    auto_close_resolved: bool = True


@dataclass
class PullsConfig:
    enabled: bool = True
    auto_merge_safe: bool = False


@dataclass
class LockConfig:
    timeout_minutes: int = 30


@dataclass
class ClaudeStyleConfig:
    no_emojis: bool = True
    no_preamble: bool = True
    concise: bool = True
    tone: str = "professional"


@dataclass
class ClaudeConfig:
    enabled: bool = True
    model: str = "claude-opus-4-6"
    max_tokens: int = 256
    temperature: float = 0.2
    style: ClaudeStyleConfig = field(default_factory=ClaudeStyleConfig)


@dataclass
class DryRunConfig:
    default: bool = False


@dataclass
class LoggingConfig:
    level: str = "INFO"
    run_log_dir: str = "logs"


@dataclass
class Config:
    repo: RepoConfig
    heatmap: HeatmapConfig = field(default_factory=HeatmapConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    issues: IssuesConfig = field(default_factory=IssuesConfig)
    pulls: PullsConfig = field(default_factory=PullsConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    dry_run: DryRunConfig = field(default_factory=DryRunConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _get(d: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def load(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())

    repo_raw = raw.get("repo", {})
    repo = RepoConfig(
        owner=repo_raw["owner"],
        name=repo_raw["name"],
        default_branch=repo_raw.get("default_branch", "main"),
    )

    hm_raw = raw.get("heatmap", {})
    heatmap = HeatmapConfig(
        enabled=hm_raw.get("enabled", True),
        commit_types=hm_raw.get("commit_types", ["run_history"]),
        commits_per_day=hm_raw.get("commits_per_day", 1),
        idempotency_scan_depth=hm_raw.get("idempotency_scan_depth", 50),
    )

    checks_raw = _get(raw, "health", "checks", default={})
    mf_raw = checks_raw.get("missing_files", {})
    si_raw = checks_raw.get("stale_issues", {})
    wf_raw = checks_raw.get("workflow_failures", {})

    health = HealthConfig(
        enabled=_get(raw, "health", "enabled", default=True),
        checks=HealthChecksConfig(
            missing_files=MissingFilesCheckConfig(
                enabled=mf_raw.get("enabled", True),
                required_files=mf_raw.get("required_files", []),
            ),
            stale_issues=StaleIssuesCheckConfig(
                enabled=si_raw.get("enabled", True),
                stale_after_days=si_raw.get("stale_after_days", 14),
            ),
            workflow_failures=WorkflowFailuresCheckConfig(
                enabled=wf_raw.get("enabled", True),
                check_last_n_runs=wf_raw.get("check_last_n_runs", 5),
            ),
        ),
    )

    issues_raw = raw.get("issues", {})
    issues = IssuesConfig(
        enabled=issues_raw.get("enabled", True),
        bot_label=issues_raw.get("bot_label", "bot-managed"),
        auto_close_resolved=issues_raw.get("auto_close_resolved", True),
    )

    pulls_raw = raw.get("pulls", {})
    pulls = PullsConfig(
        enabled=pulls_raw.get("enabled", True),
        auto_merge_safe=pulls_raw.get("auto_merge_safe", False),
    )

    lock_raw = raw.get("lock", {})
    lock = LockConfig(timeout_minutes=lock_raw.get("timeout_minutes", 30))

    claude_raw = raw.get("claude", {})
    style_raw = claude_raw.get("style", {})
    claude = ClaudeConfig(
        enabled=claude_raw.get("enabled", True),
        model=claude_raw.get("model", "claude-opus-4-6"),
        max_tokens=claude_raw.get("max_tokens", 256),
        temperature=claude_raw.get("temperature", 0.2),
        style=ClaudeStyleConfig(
            no_emojis=style_raw.get("no_emojis", True),
            no_preamble=style_raw.get("no_preamble", True),
            concise=style_raw.get("concise", True),
            tone=style_raw.get("tone", "professional"),
        ),
    )

    dr_raw = raw.get("dry_run", {})
    dry_run = DryRunConfig(default=dr_raw.get("default", False))

    log_raw = raw.get("logging", {})
    logging = LoggingConfig(
        level=log_raw.get("level", "INFO"),
        run_log_dir=log_raw.get("run_log_dir", "logs"),
    )

    return Config(
        repo=repo,
        heatmap=heatmap,
        health=health,
        issues=issues,
        pulls=pulls,
        lock=lock,
        claude=claude,
        dry_run=dry_run,
        logging=logging,
    )
