from bot.models import ChangeSet, CommitPlan, FileChange, RunState


def test_run_state_defaults():
    state = RunState(date="2026-03-18", dry_run=False)
    assert state.committed_files == []
    assert state.errors == []


def test_run_state_to_dict():
    state = RunState(date="2026-03-18", dry_run=True)
    state.committed_files.append("CHANGELOG.md")
    d = state.to_dict()
    assert d["date"] == "2026-03-18"
    assert d["dry_run"] is True
    assert d["committed_files"] == ["CHANGELOG.md"]


def test_changeset_fields():
    cs = ChangeSet(
        files=[FileChange(path="CHANGELOG.md", content="# Changelog\n")],
        reason="test",
        risk="SAFE",
        source="heatmap",
    )
    assert cs.risk == "SAFE"
    assert cs.files[0].path == "CHANGELOG.md"


def test_commit_plan_fields():
    cs = ChangeSet(files=[], reason="r", risk="SAFE", source="heatmap")
    plan = CommitPlan(
        changeset=cs,
        commit_message="bot: changelog entry — 2026-03-18\n\nBot-Run-Id: 2026-03-18\nBot-Commit-Type: changelog_entry",
        commit_type="changelog_entry",
        idempotency_marker="Bot-Run-Id: 2026-03-18\nBot-Commit-Type: changelog_entry",
    )
    assert "Bot-Run-Id" in plan.idempotency_marker
    assert plan.commit_type == "changelog_entry"
