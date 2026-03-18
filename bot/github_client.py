from __future__ import annotations

import logging
import os
from typing import Any

from github import Github, GithubException
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.WorkflowRun import WorkflowRun

log = logging.getLogger("bot.github")


class GitHubClient:
    def __init__(self, token: str | None = None, repo_full_name: str | None = None):
        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN not set")
        self._gh = Github(token)
        self._repo: Repository | None = None
        self._repo_full_name = repo_full_name

    def repo(self, full_name: str | None = None) -> Repository:
        name = full_name or self._repo_full_name
        if name is None:
            raise ValueError("repo full_name required")
        if self._repo is None or self._repo.full_name != name:
            self._repo = self._gh.get_repo(name)
        return self._repo

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def get_open_issues(self, full_name: str | None = None) -> list[Issue]:
        return list(self.repo(full_name).get_issues(state="open"))

    def issue_exists_with_label(self, label: str, full_name: str | None = None) -> bool:
        issues = self.repo(full_name).get_issues(state="open", labels=[label])
        return issues.totalCount > 0

    def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
        full_name: str | None = None,
    ) -> str:
        r = self.repo(full_name)
        existing_labels = {lbl.name for lbl in r.get_labels()}
        for lbl in labels:
            if lbl not in existing_labels:
                try:
                    r.create_label(name=lbl, color="0075ca")
                except GithubException:
                    pass  # race or already exists
        issue = r.create_issue(title=title, body=body, labels=labels)
        log.info("Created issue #%d: %s", issue.number, title)
        return issue.html_url

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    def pr_exists_for_branch(self, branch: str, full_name: str | None = None) -> bool:
        prs = self.repo(full_name).get_pulls(state="open", head=branch)
        return prs.totalCount > 0

    def create_pr(
        self,
        branch: str,
        title: str,
        body: str,
        base: str = "main",
        full_name: str | None = None,
    ) -> str:
        pr = self.repo(full_name).create_pull(
            title=title,
            body=body,
            head=branch,
            base=base,
        )
        log.info("Created PR #%d: %s", pr.number, title)
        return pr.html_url

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    def get_recent_workflow_runs(
        self, workflow_filename: str, n: int = 5, full_name: str | None = None
    ) -> list[WorkflowRun]:
        r = self.repo(full_name)
        try:
            workflow = r.get_workflow(workflow_filename)
            runs = list(workflow.get_runs()[:n])
            return runs
        except GithubException as exc:
            log.warning("Could not fetch workflow runs: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def file_exists(self, path: str, full_name: str | None = None) -> bool:
        try:
            self.repo(full_name).get_contents(path)
            return True
        except GithubException:
            return False
