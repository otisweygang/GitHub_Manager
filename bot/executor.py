from __future__ import annotations

import logging

from .git_ops import GitOps
from .github_client import GitHubClient
from .models import CommitPlan, IssuePlan, PRPlan, RunState

log = logging.getLogger("bot.executor")


def apply_commit(
    plan: CommitPlan | None,
    git_ops: GitOps,
    state: RunState,
    dry_run: bool,
) -> None:
    """Write files and commit. No decisions — pure effect application."""
    if plan is None:
        state.skipped_reasons.append("heatmap: no commit plan (already done today or disabled)")
        return

    if dry_run:
        for fc in plan.changeset.files:
            log.info("[dry-run] Would write %s", fc.path)
        log.info("[dry-run] Would commit: %s", plan.commit_message.splitlines()[0])
        state.skipped_reasons.append(f"heatmap: dry-run, would commit '{plan.commit_type}'")
        return

    try:
        for fc in plan.changeset.files:
            git_ops.write_file(fc.path, fc.content)
            git_ops.stage(fc.path)
            log.info("Staged %s", fc.path)

        if not git_ops.has_staged_changes():
            state.skipped_reasons.append("heatmap: no staged changes after write (content unchanged)")
            return

        git_ops.commit(plan.commit_message)
        git_ops.pull_rebase()
        git_ops.push()

        for fc in plan.changeset.files:
            state.committed_files.append(fc.path)

    except Exception as exc:
        log.error("Commit failed: %s", exc)
        state.errors.append(f"commit error: {exc}")


def apply_issues(
    plans: list[IssuePlan],
    github_client: GitHubClient,
    state: RunState,
    dry_run: bool,
    repo_full_name: str,
) -> None:
    """Open GitHub issues. Skips any that already exist (deduplication via label)."""
    for plan in plans:
        fingerprint_label = f"check:{plan.fingerprint}"

        if github_client.issue_exists_with_label(fingerprint_label, full_name=repo_full_name):
            state.skipped_reasons.append(f"issue already open: {plan.title}")
            continue

        if dry_run:
            log.info("[dry-run] Would open issue: %s", plan.title)
            state.skipped_reasons.append(f"dry-run: would open issue '{plan.title}'")
            continue

        try:
            url = github_client.create_issue(
                title=plan.title,
                body=plan.body,
                labels=plan.labels + [fingerprint_label],
                full_name=repo_full_name,
            )
            state.created_issues.append(url)
        except Exception as exc:
            log.error("Failed to create issue '%s': %s", plan.title, exc)
            state.errors.append(f"issue error ({plan.title}): {exc}")


def apply_prs(
    plans: list[PRPlan],
    git_ops: GitOps,
    github_client: GitHubClient,
    state: RunState,
    dry_run: bool,
    repo_full_name: str,
    default_branch: str,
) -> None:
    """Create branches and open PRs. Skips duplicates."""
    for plan in plans:
        if github_client.pr_exists_for_branch(plan.branch, full_name=repo_full_name):
            state.skipped_reasons.append(f"PR already open for branch: {plan.branch}")
            continue

        if dry_run:
            log.info("[dry-run] Would open PR: %s (branch: %s)", plan.title, plan.branch)
            state.skipped_reasons.append(f"dry-run: would open PR '{plan.title}'")
            continue

        try:
            original_branch = git_ops.current_branch()
            git_ops.checkout_new_branch(plan.branch)

            for fc in plan.changeset.files:
                git_ops.write_file(fc.path, fc.content)
                git_ops.stage(fc.path)

            if git_ops.has_staged_changes():
                git_ops.commit(f"bot: {plan.title}")
                git_ops.push(branch=plan.branch)
                url = github_client.create_pr(
                    branch=plan.branch,
                    title=plan.title,
                    body=plan.body,
                    base=default_branch,
                    full_name=repo_full_name,
                )
                state.created_prs.append(url)
            else:
                state.skipped_reasons.append(f"PR: no changes to commit for '{plan.title}'")

            git_ops.checkout(original_branch)

        except Exception as exc:
            log.error("Failed to create PR '%s': %s", plan.title, exc)
            state.errors.append(f"pr error ({plan.title}): {exc}")
            try:
                git_ops.checkout(original_branch)
            except Exception:
                pass
