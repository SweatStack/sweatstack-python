"""Per-case setup and cleanup: the managed user that writing tasks use, and the workspaces."""

from __future__ import annotations

import shutil

from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import ReportCase, ReportCaseFailure

from sweatstack import Client

from . import harness
from .cases import EVAL_USER, AgentTask, CaseMeta
from .harness import AgentRun


class EvalLifecycle(CaseLifecycle[AgentTask, AgentRun, CaseMeta]):
    """Keeps a writing task's changes off everything but the managed user ``EVAL_USER``,
    removes what the task created, and keeps the workspace of a case that failed."""

    async def setup(self) -> None:
        self.created_before: set[tuple[str, str]] | None = None
        if not self._touches_account():
            return
        athlete = _eval_user_client()
        self.created_before = _record_ids(athlete)

    async def teardown(self, result: ReportCase | ReportCaseFailure | None) -> None:
        if self.created_before is not None:
            athlete = _eval_user_client()
            for resource, record_id in _record_ids(athlete) - self.created_before:
                getattr(athlete, resource).delete(record_id)
        if isinstance(result, ReportCase) and _passed(result):
            shutil.rmtree(result.output.workspace, ignore_errors=True)
        # Failed or interrupted: the workspace stays under runs/ for inspection.

    def _touches_account(self) -> bool:
        settings = harness.SETTINGS
        return bool(
            self.case.metadata
            and self.case.metadata.writes_data
            and settings
            and settings.run_programs
        )


def _eval_user_client() -> Client:
    client = Client()
    matches = [u for u in client.users.list(name=EVAL_USER) if u.display_name == EVAL_USER]
    if matches:
        return client.delegated_client(matches[0])
    first, last = EVAL_USER.split(" ", 1)
    return client.delegated_client(client.users.create(first_name=first, last_name=last).id)


def _record_ids(athlete: Client) -> set[tuple[str, str]]:
    """The eval user's tests and traces, as ``(resource, id)`` pairs."""
    tests = {("tests", test.id) for test in athlete.tests.list(limit=1000)}
    traces = {("traces", trace.id) for trace in athlete.traces.list(limit=1000)}
    return tests | traces


def _passed(case: ReportCase) -> bool:
    return all(bool(a.value) for a in case.assertions.values())
