from unittest.mock import MagicMock, call

from bot.executor import apply_commit, apply_issues
from bot.models import ChangeSet, CommitPlan, FileChange, IssuePlan, RunState


def _make_commit_plan(commit_type: str = "changelog_entry") -> CommitPlan:
    cs = ChangeSet(
        files=[FileChange(path="CHANGELOG.md", content="# Changelog\n")],
        reason="test",
        risk="SAFE",
        source="heatmap",
    )
    return CommitPlan(
        changeset=cs,
        commit_message=f"bot: {commit_type}\n\nBot-Run-Id: 2026-03-18\nBot-Commit-Type: {commit_type}",
        commit_type=commit_type,
        idempotency_marker=f"Bot-Run-Id: 2026-03-18\nBot-Commit-Type: {commit_type}",
    )


def test_apply_commit_dry_run_does_not_write():
    plan = _make_commit_plan()
    git = MagicMock()
    state = RunState(date="2026-03-18", dry_run=True)

    apply_commit(plan, git, state, dry_run=True)

    git.write_file.assert_not_called()
    git.commit.assert_not_called()
    git.push.assert_not_called()
    assert len(state.skipped_reasons) == 1


def test_apply_commit_none_plan_adds_skip_reason():
    git = MagicMock()
    state = RunState(date="2026-03-18", dry_run=False)

    apply_commit(None, git, state, dry_run=False)

    git.commit.assert_not_called()
    assert any("heatmap" in r for r in state.skipped_reasons)


def test_apply_commit_real_run_writes_and_commits():
    plan = _make_commit_plan()
    git = MagicMock()
    git.has_staged_changes.return_value = True
    state = RunState(date="2026-03-18", dry_run=False)

    apply_commit(plan, git, state, dry_run=False)

    git.write_file.assert_called_once_with("CHANGELOG.md", "# Changelog\n")
    git.stage.assert_called_once_with("CHANGELOG.md")
    git.commit.assert_called_once()
    git.push.assert_called_once()
    assert "CHANGELOG.md" in state.committed_files


def test_apply_issues_dry_run_skips():
    plan = IssuePlan(
        title="Test issue",
        body="body",
        labels=["bot-managed"],
        fingerprint="test-fingerprint",
    )
    gh = MagicMock()
    gh.issue_exists_with_label.return_value = False
    state = RunState(date="2026-03-18", dry_run=True)

    apply_issues([plan], gh, state, dry_run=True, repo_full_name="owner/repo")

    gh.create_issue.assert_not_called()
    assert len(state.skipped_reasons) == 1


def test_apply_issues_deduplicates():
    plan = IssuePlan(
        title="Already open issue",
        body="body",
        labels=["bot-managed"],
        fingerprint="existing-fp",
    )
    gh = MagicMock()
    gh.issue_exists_with_label.return_value = True  # already exists
    state = RunState(date="2026-03-18", dry_run=False)

    apply_issues([plan], gh, state, dry_run=False, repo_full_name="owner/repo")

    gh.create_issue.assert_not_called()
    assert any("already open" in r for r in state.skipped_reasons)
