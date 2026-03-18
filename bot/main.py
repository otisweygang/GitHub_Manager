"""GitHub Manager Bot — entry point.

Usage:
    python -m bot.main [--dry-run] [--force] [--only=SUBSYSTEM] [--config=PATH] [--verbose] [--no-claude]

Subsystems: heatmap, health, issues, pulls
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_module
from . import executor, heatmap, logger
from .git_ops import GitOps
from .github_client import GitHubClient
from .models import RunState

ALL_PLANNERS = {"heatmap", "health", "issues", "pulls"}
LOCK_PATH = Path(".bot/last_run.json")


def main() -> int:
    args = _parse_args()

    cfg = config_module.load(args.config)

    log_level = "DEBUG" if args.verbose else cfg.logging.level
    log = logger.setup(level=log_level, run_log_dir=cfg.logging.run_log_dir)

    # --no-claude overrides config
    if args.no_claude:
        cfg.claude.enabled = False

    dry_run: bool = args.dry_run if args.dry_run is not None else cfg.dry_run.default
    force: bool = args.force
    active_planners = {args.only} if args.only else ALL_PLANNERS

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = RunState(date=today, dry_run=dry_run)

    log.info("=== GitHub Manager Bot — %s%s ===", today, " [DRY RUN]" if dry_run else "")
    log.info("Active planners: %s", active_planners)

    # ------------------------------------------------------------------
    # LOCK
    # ------------------------------------------------------------------
    if not _acquire_lock(today, dry_run, cfg.lock.timeout_minutes, log):
        return 1

    git_ops = GitOps()
    github_client = GitHubClient(repo_full_name=cfg.repo.full_name)

    try:
        # --------------------------------------------------------------
        # PLAN PHASE — pure, no side effects
        # --------------------------------------------------------------
        commit_plan = None
        issue_plans = []
        pr_plans = []

        if "heatmap" in active_planners:
            log.info("Planning: heatmap%s", " [force]" if force else "")
            commit_plan = heatmap.plan(cfg, git_ops, force=force)

        # health / issues / pulls — stubs for v1.1
        if "health" in active_planners and cfg.health.enabled:
            log.debug("health planner: not yet implemented (v1.1)")

        if "issues" in active_planners and cfg.issues.enabled:
            log.debug("issues planner: not yet implemented (v1.1)")

        if "pulls" in active_planners and cfg.pulls.enabled:
            log.debug("pulls planner: not yet implemented (v1.1)")

        # --------------------------------------------------------------
        # EXECUTE PHASE — all side effects, no decisions
        # --------------------------------------------------------------
        executor.apply_commit(commit_plan, git_ops, state, dry_run=dry_run)
        executor.apply_issues(issue_plans, github_client, state, dry_run=dry_run, repo_full_name=cfg.repo.full_name)
        executor.apply_prs(
            pr_plans, git_ops, github_client, state,
            dry_run=dry_run,
            repo_full_name=cfg.repo.full_name,
            default_branch=cfg.repo.default_branch,
        )

    except Exception as exc:
        log.error("Unexpected error: %s", exc, exc_info=True)
        state.errors.append(f"unexpected: {exc}")

    # ------------------------------------------------------------------
    # REPORT — always runs
    # ------------------------------------------------------------------
    log_path = logger.write_run_log(state.to_dict(), run_log_dir=cfg.logging.run_log_dir)
    log.info("Run log written to %s", log_path)

    if not dry_run:
        try:
            git_ops.stage(str(log_path))
            if git_ops.has_staged_changes():
                git_ops.commit(f"bot: run log — {today}")
                git_ops.push()
                log.info("Run log committed and pushed")
        except Exception as exc:
            log.error("Failed to commit run log: %s", exc)
            state.errors.append(f"run log commit error: {exc}")

    _release_lock(state, today, dry_run)

    if args.verbose or dry_run:
        _print_state(state, log)

    exit_code = 1 if state.errors else 0
    log.info("=== Bot run complete (exit %d) ===", exit_code)
    return exit_code


# ------------------------------------------------------------------
# Lock helpers
# ------------------------------------------------------------------

def _acquire_lock(today: str, dry_run: bool, timeout_minutes: int, log) -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    if LOCK_PATH.exists():
        try:
            existing = json.loads(LOCK_PATH.read_text())
            if existing.get("status") == "running":
                started = datetime.fromisoformat(existing.get("started_at", "2000-01-01T00:00:00Z").replace("Z", "+00:00"))
                age_minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
                if age_minutes < timeout_minutes:
                    log.error(
                        "Lock held by a running process (started %.1f min ago). Aborting. "
                        "If this is a ghost lock, delete .bot/last_run.json manually.",
                        age_minutes,
                    )
                    return False
                log.warning("Stale lock detected (%.1f min old), overriding", age_minutes)
        except (json.JSONDecodeError, KeyError):
            log.warning("Could not parse existing lock file, overriding")

    if not dry_run:
        LOCK_PATH.write_text(json.dumps({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "date": today,
        }, indent=2))
    return True


def _release_lock(state: RunState, today: str, dry_run: bool) -> None:
    if dry_run:
        return
    LOCK_PATH.write_text(json.dumps({
        "status": "failed" if state.errors else "complete",
        "date": today,
        "committed_files": state.committed_files,
        "issues_created": state.created_issues,
        "prs_created": state.created_prs,
        "errors": state.errors,
    }, indent=2))


# ------------------------------------------------------------------
# CLI / display helpers
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub Manager Bot")
    parser.add_argument("--dry-run", action="store_true", default=None, help="No writes, no pushes")
    parser.add_argument("--only", choices=list(ALL_PLANNERS), default=None, help="Run only one subsystem")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--verbose", action="store_true", help="Force DEBUG logging")
    parser.add_argument("--no-claude", action="store_true", help="Use template fallbacks only")
    parser.add_argument("--force", action="store_true", help="Bypass idempotency check and rerun regardless")
    return parser.parse_args()


def _print_state(state: RunState, log) -> None:
    log.info("--- RunState ---")
    log.info("committed_files  : %s", state.committed_files)
    log.info("created_issues   : %s", state.created_issues)
    log.info("created_prs      : %s", state.created_prs)
    log.info("skipped_reasons  : %s", state.skipped_reasons)
    log.info("errors           : %s", state.errors)


if __name__ == "__main__":
    sys.exit(main())
